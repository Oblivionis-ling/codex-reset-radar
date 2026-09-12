# Codex Reset Radar 项目全面运行与开发状态报告

报告日期：2026-09-07 16:31（Asia/Shanghai）  
巡检范围：Backend、Edge Extension、Profile / Replies / Search、SQLite、Mirror、Dashboard、GitHub Pages、CI、阶段交付物与测试结果。  
本轮原则：只读巡检；没有重启 Backend、reload Extension、刷新 X 页面或修改 SQLite。报告文件本身是本轮唯一新增交付物。

## 1. 总体结论

项目的主要功能链路已经实现，Phase A–H 的代码、报告和自动化验证基本齐全；GitHub Pages 与 data branch 也在运行。但当前不能判定为“全链路健康”，原因如下：

1. **Backend 进程仍在，但当前应用层已处于 degraded / 无响应状态。** 进程和 8787 listener 存在；在巡检后续复测中 `/health`、`/api/radar` 均在 8 秒内无响应。运行日志同时出现事件循环延迟和 SQLite `database is locked`。
2. **Replies Monitor 仍为 offline。** 最后可读状态来自旧 Content Script instance，最后 heartbeat 是 2026-09-03 10:42:35.975Z，sequence=8；不能把当前系统称为四路全健康。
3. **Mirror scheduler 在运行，但公开成功发布不稳定。** 配置窗口为 300 秒，GitHub 网络失败导致成功发布间隔仍可能超过 7 分钟甚至 15 分钟。
4. **Dashboard 线上入口正常，公开数据在本次取样时 fresh。** Pages 返回 HTTP 200；data branch 的公开 `meta.json` 最近一次 `published_at` 为 2026-09-07 08:22:40Z，取样时间约 08:31Z，尚未超过 15 分钟阈值。
5. **本地开发状态与 GitHub 远端不一致。** 本地 `main` 为 `b901c30`，比 `origin/main=2d46f7e` 超前 3 个提交，但工作树仍有大量未提交的 Backend / Extension / Dashboard / Observability / Mirror 改动。因此本地已完成的最新修复不能视为已经部署到远端。

## 2. 当前运行矩阵

以下状态以“最后一次成功读取本地 `/api/health` 的快照”为准；随后 Backend 被慢的 Observability 查询拖入无响应，所以 Profile / Search 的年龄不是最终实时值。

| 组件 | 取样状态 | 证据 | 判断 |
|---|---|---|---|
| Backend | 进程 alive；应用层 degraded | `start-radar.bat` → venv Python → Uvicorn；8787 仅 1 个 listener；随后 `/health` 8 秒超时 | **不健康，需要恢复** |
| Profile Monitor | 最后快照 healthy | instance `profile-cs-4fd80914-cdb2-45cf-ac56-ed6ce1fa29e5`，seq=2041，last heartbeat `08:16:47.443Z`；DOM、Observer、tab 状态均正常 | **最后已知正常；当前需 Backend 恢复后复核** |
| Replies Monitor | offline | instance `replies-cs-8378c8ad-50ba-4cc7-8f64-fa704be1053c`，seq=8；last heartbeat `2026-09-03T10:42:35.975Z` | **当前明确异常** |
| Search Backfill | 最后快照 healthy | instance `page-cs-1f0f2adb-a412-411b-a957-fa04277b1cc3`，seq=3；last heartbeat `08:12:39.078Z` | **最后已知正常；当前需复核** |
| GitHub Mirror | scheduler / retry 有运行证据 | 最近成功 `08:22:43Z`；最近 cycle 配置 300 秒；日志存在 network retry | **功能运行但可靠性不足** |
| GitHub Pages | HTTP 200 | `https://oblivionis-ling.github.io/codex-reset-radar/` 返回页面和 JS/CSS | **线上可访问** |

Backend 进程链路如下：

```text
start-radar.bat
  └─ cmd.exe PID 10644
      └─ backend\.venv\Scripts\python.exe PID 23284
          └─ uvicorn app.main:app PID 12252
```

本次没有发现第二个 8787 listener，也没有执行不在正常工作流中的 Backend。

## 3. Backend 与本轮发现的运行风险

### 3.1 Backend 版本与启动方式

当前 `/health` 曾返回 `ready=true` 和：

```text
backend_instance_id=backend-20260903T103939-3f8b74
```

这说明当前常驻进程已经加载 Phase H observability 代码，不是 Phase H 报告中所说的旧版生产进程。进程由仓库根目录的 `start-radar.bat` 启动，符合项目约定的唯一启动方式。

### 3.2 Observability API 的阻塞问题

代码中的 `backend/app/observability.py` 使用：

```python
path.read_text(...).splitlines()[-limit:]
```

也就是先读取整个 JSONL 文件，再截取尾部。`/api/observability/summary` 会读取 Backend event stream；当前该文件约 **894.3 MB**。`/api/observability/trace` 与 `/api/observability/errors` 也使用同类全量读取路径。

本轮证据：

- 首轮轻量接口曾返回 200：`/health`、`/api/health`、`/api/radar`。
- `/api/tweets` 在 8 秒内超时。
- 调用 Observability 查询后，随后 `/health`、`/api/radar` 在 5–8 秒窗口内均无响应。
- Backend runtime log 出现最高约 **139 秒** 的 `EVENT_LOOP_LAG_DETECTED`。
- 同时出现多路 `BACKEND_HEARTBEAT_DB_WRITE_FAILED` 和 `sqlite3.OperationalError: database is locked`。
- Backend worker 进程工作集一度约 **1.85 GB**。

因此当前不是单纯的“诊断接口慢”，而是同步文件 I/O + SQLite 长读事务可能阻塞同一 Uvicorn event loop 和心跳提交，足以影响健康判定与采集接收。

这也解释了为什么当前 Backend 进程存在，但不能按 healthy 处理。需要后续单独修复：日志尾读、分页/时间窗口、索引查询、查询超时和诊断接口隔离；本轮未实施修复。

### 3.3 SQLite 与日志规模

只读统计得到：

| 项目 | 当前规模 |
|---|---:|
| `radar.db` | 676,790,272 bytes（约 676.8 MB） |
| journal mode | `delete` |
| Tweet | 222 |
| Classification 历史记录 | 1,342 |
| `heartbeat_history` | 46,667 |
| `monitor_diagnostic_events` | 699,984 |
| Backend unified event JSONL | 894,329,254 bytes（约 894.3 MB） |

数据库本身未发现数据删除迹象；但当前观测查询和写入竞争已造成 lock 错误，数据库锁竞争是当前最高优先级运行风险之一。

## 4. Mirror 与公开数据

### 4.1 当前 Mirror 统计

`backend/data/mirror-cadence.jsonl` 的累计记录约 9,300+ 条，关键事件包括：

- `PUBLIC_MIRROR_CYCLE_STARTED`
- `PUBLIC_MIRROR_EXPORT_COMPLETED`
- `PUBLIC_MIRROR_PUSH_STARTED`
- `PUBLIC_MIRROR_SYNC_SUCCESS`
- `PUBLIC_MIRROR_SYNC_FAILED`
- `PUBLIC_MIRROR_RETRY_SCHEDULED`
- `PUBLIC_MIRROR_SYNC_SKIPPED`

累计成功发布约 897 次。成功发布间隔统计为：

| 指标 | 结果 |
|---|---:|
| 平均 | 537.3 秒，约 8 分 57 秒 |
| 中位数 | 301.6 秒，约 5 分 02 秒 |
| P95 | 1502.5 秒，约 25 分 03 秒 |
| 最大 | 3350.6 秒，约 55 分 51 秒 |
| 超过 7 分钟 | 334 次 |
| 超过 15 分钟 | 163 次 |

最近成功发布时间序列（UTC）：

```text
08:01:12
08:15:58   间隔约 14m46s，attempt=4
08:22:43   间隔约 06m45s，attempt=1
```

最近日志显示 scheduler 的配置窗口仍为 `300s`；失败主要是 `network_connect`，另有 `network_reset`、`network_timeout`、`git_conflict` 和少量 unknown。已有同一 snapshot 复用和最多 4 次 bounded retry 的证据，说明可靠性修复代码已经在运行，但无法消除 GitHub 网络本身的瓶颈。

### 4.2 线上 data branch 与 Dashboard

本次直接读取公开 data branch 成功：

```text
index.generated_at   = 2026-09-07T08:20:14Z
meta.generated_at    = 2026-09-07T08:20:14Z
meta.published_at    = 2026-09-07T08:22:40.1632092+00:00
last_sync_status      = success
snapshot_id           = snap-20260907T082014Z-0e86b8
tweet_count           = 222
```

线上 Pages 页面返回 HTTP 200，页面仍是中文默认界面，bundle 中包含中文/英文切换、Dashboard refresh log 和 `mirror_synced_at` 相关字段；敏感信息扫描未发现 DeepSeek、WxPusher、GitHub token 或 token-like key。

注意：仓库工作区内的 `public-data/` 文件最后修改时间仍主要是 2026-08-31，属于本地旧 fixture；线上 Dashboard 运行时从公开 `data` branch 读取，因此两者不能混为同一份快照。

## 5. Dashboard / GitHub 部署状态

- Pages workflow：`.github/workflows/pages.yml` 存在，执行 dashboard test、build、upload artifact 和 deploy-pages。
- CI workflow：`.github/workflows/ci.yml` 存在，包含 Backend pytest、Extension test、Extension TypeScript check 和 MV3 build。
- GitHub 最近可见的成功 workflow 仍对应远端 `main` 的 `2d46f7e`，不是本地 `b901c30`。
- Pages 当前可访问，但不能据此证明本地未提交的 Phase H / Mirror 最新改动已经部署。
- Dashboard freshness 规则仍为：`fresh <= 15min`、`stale > 15min`；Dashboard refresh 仍为 60 秒，本轮没有发现代码改成 30 分钟的证据。

## 6. 各阶段开发状态

| 阶段 | 开发状态 | 当前说明 |
|---|---|---|
| Phase A | 基础链路已实现 | Backend、Extension、Profile、Replies、Search 基础采集已建立；原报告中的页面刷新、Backend 重启、7 天低频回归仍不是完整长期验收项。 |
| Phase B | 已完成 | Rule classifier、DeepSeek、Context、Resolver、Radar state 已实现；数据库保留分类历史。 |
| Phase B.5 | 已验收 | 分类校准、Gold Set、人工复核和真实 DeepSeek backfill 已完成。 |
| Phase C | 已完成 | WxPusher 真实测试曾由用户确认收到；通知/告警链路已通过测试。 |
| Phase D | 已完成 | 公开仓库、安全数据 allow-list、脱敏和 data branch mirror 已建立。 |
| Phase E | 已完成 | GitHub Pages Dashboard、base path、请求失败/缺字段降级、移动布局代码已完成并上线。 |
| Phase E.5 | 已完成 | live data mirror、health semantics、15 分钟 freshness 语义已实现。 |
| Phase F | 本地已完成，远端部署需以 commit 为准 | 中文优先、英文切换、Forecast、Usage Advice、`#/tweets`、`#/resets` 已在本地实现。 |
| Phase G | 已完成并有线上版本 | Grid Ops Dashboard 视觉、响应式和可访问性已完成；线上远端仍以 GitHub main 为准。 |
| Phase H | 代码与测试基本完成，但运行态有严重性能缺陷 | 统一事件、trace、runtime、诊断 CLI、retention 已实现；当前大日志导致 Observability 查询阻塞 Backend，不能标记为生产稳定。 |
| Profile / Replies 诊断与 SPA Fix | 根因和修复代码已完成，运行验收未全绿 | 已定位 `/status/<id>` route classification 问题并实现继承前序 monitor source；当前 Profile 有新 heartbeat，Replies 仍使用旧 offline instance。 |
| Mirror cadence / reliability fix | 已实现，外部网络仍不稳定 | 300 秒 scheduler、absolute deadline、同 snapshot retry、single-flight、结构化失败类型均有证据；GitHub 网络失败仍造成长尾间隔。 |

## 7. 自动化验证结果

当前工作区已有的最近验证结果：

| 模块 | 结果 |
|---|---|
| Backend pytest | **51 passed** |
| Extension Vitest | **12 passed** |
| Extension TypeScript check | **通过** |
| Extension MV3 build | **通过** |
| Dashboard Vitest | **8 passed** |
| Dashboard TypeScript check | **通过** |
| Dashboard Vite build | **通过** |
| Git diff whitespace check | 未发现实际 whitespace error；仅有 Windows LF/CRLF 提示 |

测试通过说明代码回归面基本可用，但没有覆盖“生产规模 894MB JSONL + 700k SQLite diagnostic rows 下的 Observability API 性能”这一当前暴露的关键场景。

## 8. Git、提交与安全状态

当前 Git：

```text
branch: main
HEAD: b901c30 feat: add mirror and dashboard timing logs
origin/main: 2d46f7e...
ahead/behind: ahead 3, behind 0
```

工作树仍有大量未提交修改和未跟踪文件，覆盖：

- Backend observability、ingestion、alert/WxPusher、mirror 逻辑；
- Extension content/background/types；
- Dashboard data/UI 测试与实现；
- diagnose CLI、stop-backend 脚本；
- 多份阶段报告。

`.env` 未被 Git 跟踪并被 `.gitignore` 忽略；Backend data、日志、Dashboard/Extension dist 也未纳入 Git。已做的 tracked/bundle 扫描没有发现 Secret 泄漏。但在提交前仍应再次做一次全仓库 secret scan，并确认只提交源代码、脚本和脱敏报告。

## 9. 优先级建议

### P0：先恢复 Backend 可服务状态

在确认窗口执行项目规定的 `stop-backend.bat`，再从仓库根目录运行 `start-radar.bat`；不要直接杀无关 Python 进程。重启前后确认 `/health` 的 `ready=true`、新的 `backend_instance_id` 和 8787 唯一 listener。SQLite 数据不会因该脚本被删除。

### P0：修复 Observability 查询路径

禁止在请求线程中对大型 JSONL 使用 `read_text()` 全量加载。应改为安全 tail / 按时间窗口 / 分页；数据库诊断查询应限制时间范围并建立对应索引，且不应持有长事务阻塞 heartbeat commit。修复前不要把 `/api/observability/summary` 当作健康探针高频调用。

### P1：恢复并验收 Replies

Backend 恢复后，按既有工作流 reload Extension 并刷新 Replies X 页面，确认生成新的 `replies-cs-*` instance，连续至少 3 个 60 秒 heartbeat，再核对 `/api/health` 和 trace；本报告不把旧 instance 的 offline 状态推广为当前 route fix 失败。

### P1：继续观察 Mirror

继续记录 scheduler cycle、attempt、retry 和真实 `published_at`；目标是在 GitHub 网络正常时连续 4 个成功发布间隔均不超过 7 分钟。GitHub 网络连续不可达时保留 stale 展示，不修改 15 分钟阈值。

### P1：整理提交边界并部署

先审阅当前 dirty worktree，将 Phase H、Mirror reliability、Dashboard timing 等改动拆成可审计提交，再推送到 `origin/main`；只有远端 Pages workflow 成功后，才能把本地最新开发状态称为线上状态。

## 10. 最终判定

```text
开发状态：大部分阶段完成，仍有本地未提交开发成果
运行状态：不全绿
Backend：进程存在，但当前被诊断/SQLite 锁竞争拖至 degraded
Profile：最后已知 healthy
Replies：offline
Search Backfill：最后已知 healthy
Mirror：scheduler 正常，成功发布受 GitHub 网络影响
Dashboard：线上 HTTP 200，当前公开快照 fresh
```

在完成 Backend 恢复、Observability 性能修复和 Replies 三周期 heartbeat 验收前，项目应标记为：

> **功能基本完成、线上展示可用，但本地运行稳定性和全链路可观测性仍未达到最终验收。**

