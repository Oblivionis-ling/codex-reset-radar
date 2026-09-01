# Codex Reset Radar — Live Mirror Cadence Fix Report

报告时间：2026-09-01（Asia/Shanghai）  
验收范围：Backend GitHub data mirror scheduler、公开 data branch、GitHub Pages Dashboard。

## 1. 结论

修复已完成并通过真实运行验收。

- `GITHUB_MIRROR_ENABLED=True`；实际 interval 为 `300s`。
- scheduler 现在按绝对 scheduled deadline 运行，不再从上一次 cycle 完成后重新等待 5 分钟。
- event-triggered sync 不会把下一次 scheduled window 推迟到 15–20 分钟后。
- `no_changes`、`failed`、`published` 已分开统计；60 秒 heartbeat 不会因此产生每分钟 Git commit。
- 网络正常后连续 4 次 successful publish 的间隔均小于 7 分钟，实际约 5 分钟。
- Dashboard freshness threshold 保持 `15 分钟`，未通过放宽阈值掩盖问题。

## 2. Root Cause

历史代码使用如下结构：

```python
await asyncio.wait_for(mirror_event.wait(), timeout=interval)
await asyncio.to_thread(_run_public_mirror_sync, settings)
```

这意味着下一次 timeout 在同步完成后才重新开始计算。它不是一个固定的绝对 scheduled deadline；当 export、clone、commit、push 或 retry 变慢时，调度周期会随 cycle 完成时间漂移。

同时，长期运行的 Backend 进程是旧进程：

- PID `23360` / `19176` 于 2026-08-31 04:23:09 启动；
- 当时进程早于 E.5 scheduler 代码；
- `.env` 没有显式设置 mirror 两项，但代码默认值为 enabled / 300s，因此不是 interval 配置成 20 分钟。

data branch 历史也不是稳定的 20 分钟固定周期：已统计 99 个成功间隔，最短 `5.08min`、最长 `34.37min`、平均 `9.56min`；其中 39 次超过 7 分钟、21 次超过 15 分钟。这与完成后计时、失败周期和外部 push/clone 异常叠加的表现一致。

本次真实验收进一步捕获了两次明确的 GitHub 网络失败：

- `17:21:12Z` scheduled cycle：export `754ms`，clone 两次均在约 `21.1s` 后连接 `github.com:443` 失败，最终 cycle `43.405s` 失败；
- `17:26:12Z` scheduled cycle：同类失败，最终 cycle `43.435s` 失败。

失败后 scheduler 没有停止；下一 scheduled cycle 仍然约 300 秒后启动。网络恢复后 `git ls-remote` 约 `1.2s` 成功，随后 push 恢复正常。

未发现：

- 独立 sync lock 导致的 lock busy；
- 10/15 分钟 min publish interval 或 cooldown；
- heartbeat 每分钟触发 Git commit；
- Backend SQLite 损坏；
- event sync 重置 scheduled deadline 的旧逻辑之外的额外 debounce。

## 3. 修复内容

### Backend scheduler

`backend/app/main.py` 现在维护 `next_scheduled_at` 单调 deadline：

- scheduled cycle 到期时先消费当前 deadline，再执行同步；
- event cycle 只提前执行，不移动 scheduled deadline；
- sync 过程跨过后续 scheduled window 时，只记录明确的 `PUBLIC_MIRROR_SYNC_SKIPPED`，不会立即 burst；
- 记录实际 cycle interval、scheduled cycle interval、successful publish interval、trigger 和 duration。

同时修正了一个验收统计问题：脚本返回 `no_changes` 时，上层不再误记为 successful publish，而是记录为 `skipped`。

### Mirror script instrumentation

`scripts/sync-github-data.ps1` 增加了：

- `PUBLIC_MIRROR_EXPORT_COMPLETED`
- `PUBLIC_MIRROR_PUSH_STARTED`
- `PUBLIC_MIRROR_SYNC_SUCCESS`
- `PUBLIC_MIRROR_SYNC_FAILED`
- `PUBLIC_MIRROR_SYNC_SKIPPED`

Backend 增加了 `PUBLIC_MIRROR_CYCLE_STARTED`，并对 mirror 子进程输出做 credential redaction。日志至少包含 cycle start、finish、duration、previous success、seconds since previous success、trigger、result 和 push attempt。

## 4. Scheduler / Publish 实测结果

修复后 scheduled cycle start interval：

| Cycle | `cycle_started_at` | scheduler interval |
|---|---:|---:|
| C1 | 17:31:12.896Z | — |
| C2 | 17:36:12.882Z | 299.986s |
| C3 | 17:41:12.878Z | 299.995s |
| C4 | 17:46:12.888Z | 300.011s |

网络恢复后连续 4 个 successful publish：

| T | data branch `mirror_synced_at` | local sync success finish | 与上次 successful publish |
|---|---:|---:|---:|
| T1 | 17:31:13Z | 17:31:20.114Z | — |
| T2 | 17:36:13Z | 17:36:18.854Z | 298.741s（4.98min） |
| T3 | 17:41:13Z | 17:41:18.717Z | 299.863s（5.00min） |
| T4 | 17:46:13Z | 17:46:18.555Z | 299.838s（5.00min） |

验收结果：`T2-T1`、`T3-T2`、`T4-T3` 全部 `<= 7min`。

单次正常同步耗时：

- export 约 `0.75s`；
- push attempt=1；
- 从 cycle start 到应用层 success 约 `5.67–7.22s`；
- 成功周期没有 push retry。

## 5. Backend 版本与数据安全

旧常驻进程已精确停止，并按 `start-radar.bat` 重新启动；新进程使用 `backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:app`，`/health` 持续返回 HTTP 200。

重启前对 `backend/data/radar.db` 执行只读 `PRAGMA quick_check`，结果为 `ok`；未删除、迁移或重置 SQLite 数据。

当前 settings 实测：

```text
GITHUB_MIRROR_ENABLED=True
GITHUB_MIRROR_INTERVAL_SECONDS=300
TRANSLATION_VERSION=tibo-translation-v1
```

## 6. Dashboard freshness 验证

线上地址：<https://oblivionis-ling.github.io/codex-reset-radar/>

验证结果：

- Pages 首页 HTTP 200；
- 生产 bundle 使用 `https://raw.githubusercontent.com/Oblivionis-ling/codex-reset-radar/refs/heads/data/`；
- bundle 不包含 `127.0.0.1`、DeepSeek、WxPusher、GitHub Token 或 `.env`；
- 检查时 Raw `meta.json` 为 `17:46:13Z`，约 `4.3min`，按 15 分钟规则为 fresh；
- Raw `health.json` 的 backend、profile、replies、search_backfill 均报告 `healthy`；
- 页面运行时读取 data branch，Pages artifact 内的旧静态 fallback 不参与生产运行时 freshness 判断。

因此 Dashboard 没有把 stale threshold 改成 30 分钟；在正常 mirror cadence 下，页面保持 fresh。GitHub 网络异常期间，日志会明确显示 failed，Dashboard 仍按既定 15 分钟规则显示数据 freshness。

### Final runtime observation

在最后一次与最新代码对齐的 Backend 重启后，`2026-09-01T01:12:40Z` 的 scheduled cycle 仍按时启动；export 用时 `747ms`，随后两次 clone 都因 `github.com:443` 连接失败，最终 `43.485s` 后记录 `PUBLIC_MIRROR_SYNC_FAILED`。Backend `/health` 仍为 HTTP 200，scheduler 没有退出。

因此在该外部网络故障持续期间，线上最后成功镜像仍为 `2026-08-31T17:46:13Z`，会按 15 分钟规则进入 stale。这是失败发布的真实告警，不是通过修改 freshness threshold 隐藏的问题；网络恢复后，下一 scheduled cycle 会继续尝试发布。

## 7. 回归测试

| 检查 | 结果 |
|---|---|
| Backend pytest | 34 passed |
| Dashboard Vitest | 7 passed |
| Dashboard `npm run build` | passed |
| Extension Vitest | 12 passed |
| Extension `npm run build` | passed |
| PowerShell parser | passed |
| Python compileall | passed |
| SQLite `PRAGMA quick_check` | `ok` |
| Dashboard / Extension dist secret scan | passed |
| Dashboard 15 分钟 freshness tests | passed |

本阶段没有修改 Collector、health threshold、Radar、DeepSeek、WxPusher、数据库 schema，也没有实现自动 reload、自动重开 Tab 或 self-healing。
