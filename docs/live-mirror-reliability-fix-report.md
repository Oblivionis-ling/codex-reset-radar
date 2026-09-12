# Live Mirror Reliability Fix 报告

日期：2026-09-02（观测时间以 UTC 记录）  
项目：Codex Reset Radar  
范围：GitHub data mirror reliability；Dashboard freshness threshold 与 refresh cadence 未修改。

## 结论

本轮确认了两个相互独立的问题：

1. scheduler 本身正常按 300 秒窗口启动；此前约 20 分钟的成功发布空窗来自 GitHub `clone` / `push` 网络失败，而不是 scheduler 未启动。
2. 原实现缺少 retry delay 数组初始化，导致第一次新 cycle 在 retry 前异常退出。补齐后，临时网络错误可在同一个 mirror job 内按 30s、60s、120s 有限重试；retry 复用同一个已导出的 snapshot。

修复后的 60 分钟验收已完成。网络故障仍然存在，但已经从“失败后直接等下一个 scheduler 周期”变为“当前 job 内有限重试并明确记录，成功则立即恢复”。

## Root Cause

原先的 scheduler interval 配置为 300 秒，实际新进程日志中的正常 `scheduler_cycle_interval_seconds` 约为 300 秒。失败时观察到：

- `Failed to connect to github.com:443`
- `Recv failure: Connection was reset`
- `RPC failed; curl 28`
- GitHub clone / push 超时或连接失败

失败 job 的耗时由 GitHub 单次连接等待叠加造成；原先没有在同一个 job 内完成有限 retry，所以成功发布时间可能跨越多个 scheduler 周期。

本轮修复前还发现了一个实现遗漏：`scripts/sync-github-data.ps1` 使用 `$retryDelaysSeconds[...]`，但变量没有初始化，触发 `Cannot index into a null array`。该问题已补为：

```powershell
$retryDelaysSeconds = @(0, 30, 60, 120)
```

同时修正了 Backend 对 stdout 的处理：此前先把整段输出压成一行，可能把多个结构化事件污染到同一条记录；现在按原始行逐行脱敏、解析和持久化。

## 实施内容

- `backend/app/main.py`
  - mirror cycle / script event 结构化日志；
  - single-flight lock，阻止并发 Git worktree / push；
  - 区分 `network_connect`、`network_timeout`、`network_reset`、`network_dns`、`clone_failed`、`fetch_failed`、`push_failed`、`git_conflict`、`auth_failed`、`unknown`；
  - 仅把真正出现的 `PUBLIC_MIRROR_SYNC_SUCCESS` 当作成功；
  - scheduler deadline 被长 job 覆盖时记录 `job_already_running`，不并发启动第二个 job；
  - 保留 event dirty 状态，不丢失事件触发的后续发布。
- `scripts/sync-github-data.ps1`
  - 一次 export，retry 期间复用同一 export/worktree；
  - 四次上限：首次立即执行，后续间隔 30s、60s、120s；
  - `SYNC_SUCCESS` 只在 `git push` 成功返回后输出；
  - 记录 export、push、retry、失败分类和安全脱敏 reason。
- `dashboard/src/data.ts`、`dashboard/src/main.ts`
  - 优先使用 `meta.published_at`，旧数据回退到 `mirror_synced_at`；
  - 60 秒 refresh 与 15 分钟 freshness threshold 保持不变。

## 运行配置与进程

- `GITHUB_MIRROR_ENABLED`：已开启（默认值为 true，本次健康进程实际产生 scheduled cycle）。
- `GITHUB_MIRROR_INTERVAL_SECONDS`：300 秒。
- Backend：按项目原有 `start-radar.bat` 正常重启；SQLite 数据文件未删除、未 reset。
- 新进程启动后 `/health` 返回 HTTP 200；观测期间 Profile、Replies、Search Backfill heartbeat 仍持续写入，mirror 失败没有停止采集链路。
- Dashboard refresh：代码与测试仍为 60 秒；stale threshold 仍为 15 分钟。

## 60 分钟验收

观测区间：`2026-09-01T18:35:17Z` – `2026-09-01T19:35:20Z`，约 60 分 03 秒。

| 指标 | 结果 |
|---|---:|
| scheduler cycles | 9 |
| successful publishes | 8 |
| script failed attempts | 16 |
| retry scheduled events | 15 |
| job-already-running skips | 3 |
| 进入 retry 的 jobs | 6 |
| retry 后最终成功 | 5 |
| retry success rate | 83.3%（5/6） |
| successful publish interval 平均 | 478.669s，约 7m59s |
| successful publish interval P95 | 1193.487s，约 19m53s（nearest-rank，7 个样本） |
| successful publish interval 最大 | 1193.487s，约 19m53s |
| >15min successful interval | 1 |

成功时间线（均为 Backend 解析的 `PUBLIC_MIRROR_SYNC_SUCCESS.sync_finished_at`）：

| 标记 | 成功时间 UTC | attempt | 与上一次成功 |
|---|---|---:|---:|
| T1 | 18:39:00.122 | 1 | — |
| T2 | 18:44:00.071 | 1 | 4m59.949s |
| T3 | 19:03:53.558 | 4 | 19m53.487s |
| T4 | 19:04:51.563 | 2 | 58.004s |
| T5 | 19:14:50.780 | 4 | 9m59.217s |
| T6 | 19:21:54.859 | 3 | 7m04.080s |
| T7 | 19:24:00.150 | 1 | 2m05.291s |
| T8 | 19:34:50.806 | 4 | 10m50.656s |

### 代表性 retry job

- `18:48:54` cycle：attempt 1/2/3/4 均失败，分类为 `network_reset` / `network_connect`，retry delay 为 30/60/120 秒；最终失败，耗时约 399.2 秒。下一 scheduled window 被记录为 `job_already_running`。
- `18:58:54` cycle：attempt 1/2/3 失败，attempt 4 成功于 `19:03:53`；snapshot 始终为 `2026-09-01T18:58:55Z`，没有重新 export SQLite。
- `19:03:54` cycle：attempt 1 失败，attempt 2 成功；耗时约 57.2 秒。
- `19:08:54` cycle：attempt 4 成功；耗时约 356.4 秒。
- `19:28:54` cycle：attempt 4 成功于 `19:34:50`；该成功已计入 60 分钟窗口。

## Export / push 时间

- 正常无 retry 的 export 约 0.75–0.83 秒。
- 正常成功 cycle 总耗时约 5.75–5.80 秒。
- 网络失败时，单次 GitHub 连接等待约 21 秒；完整 retry job 约 57 秒至 399 秒，耗时主要来自连接失败与设定的 retry delay，而不是 SQLite export。
- retry 使用同一 snapshot；例如 `18:58:54` job 的所有 attempt 都使用 `snapshot_generated_at=18:58:55Z`。

## `mirror_synced_at` / `published_at` 语义

- `mirror_synced_at` / `generated_at` 继续表示本次导出 snapshot 的生成时间，保持旧 public-data contract 兼容。
- `meta.published_at` 是写入 snapshot 的 push 前时间标记，只有该版本最终 push 成功才会出现在公开 data branch，因此它是一个保守的“公开时间下界”。
- 精确的 GitHub push 成功返回时间由本地 `PUBLIC_MIRROR_SYNC_SUCCESS.sync_finished_at` 记录；本轮 Dashboard freshness 优先使用 `published_at`，相对精确返回时间只提前数秒，不能把失败 job 的 export 时间误判为成功发布。

## Dashboard 联合验收

在观测结束后，用 cache-busting 请求检查：

- GitHub Pages 首页：HTTP 200，页面可加载；
- data branch 的 `index.json`、`tweets.json`、`radar.json`、`health.json`、`resets.json`、`meta.json`：全部 HTTP 200；
- 最后公开 `meta.json`：`generated_at=2026-09-01T19:28:55Z`，`published_at` 约为 `2026-09-01T19:34:47Z`，检查时 age 约 2.37 分钟，属于 fresh；
- 公开 health snapshot 中四路组件均为 `healthy`：Backend、Profile、Replies、Search Backfill；
- Dashboard 60 秒 refresh 和 15 分钟 stale/fresh 逻辑未改动，并通过本地 Dashboard 测试与构建。

本轮没有伪造 GitHub 连续不可达 15 分钟的 Dashboard stale 结果；已有失败 job 期间的 `published_at` 不会更新，若持续超过 15 分钟，页面按既有规则显示“数据过期”，这是预期行为。

## 回归测试

| 检查项 | 结果 |
|---|---:|
| Backend pytest | 46 passed |
| Dashboard Vitest | 8 passed |
| Dashboard TypeScript / Vite build | passed |
| Python compileall | passed |
| PowerShell parser | passed |
| 本地 bare Git mirror smoke test | passed |
| 结构化事件逐行解析 | 通过；验收日志未再出现多事件合并 |
| retry delay / same snapshot | 通过；真实观测出现 30/60/120 秒与固定 snapshot |
| Secret redaction | 通过；日志不记录 credential |

## 修复前后对比

| 指标 | 修复前基线 | 修复后本轮 |
|---|---:|---:|
| successful publish 平均间隔 | 约 9m37s | 约 7m59s（含网络故障样本） |
| >15min 间隔 | 10 次 | 1 次 |
| 最大间隔 | 35m | 19m53s |
| retry | 失败后等待下一个 scheduler | 同一 job 最多 4 次，30/60/120s |
| 网络失败可见性 | 连接错误混在普通输出中 | 结构化分类、attempt、retry、duration、reason |

本轮仍然存在 GitHub 网络瓶颈：60 分钟内多次出现连接 reset / connect failure，且一次 retry job 未恢复、产生 19m53s 成功间隔。修复已降低短时抖动的恢复延迟并提升可诊断性，但无法消除 GitHub 网络本身的不稳定。

## 停止点

本阶段已停止在 mirror reliability fix、日志、有限 retry、single-flight 和联合验收。没有修改 Dashboard 60 秒 refresh、15 分钟 freshness threshold、5 分钟 scheduler、Radar、DeepSeek、Translation、Alert Manager、SQLite schema 或 Collector；没有实现 self-healing。
