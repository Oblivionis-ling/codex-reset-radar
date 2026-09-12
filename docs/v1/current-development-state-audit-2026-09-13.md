# Codex Reset Radar — Current Development State Audit

审计日期：2026-09-13  
时区：Asia/Shanghai  
审计范围：Backend、SQLite、Extension、Mirror、Dashboard、Pages、通知、Observability、Git/CI  
审计方式：只读检查；未重启 Backend，未 reload Extension，未刷新 X，未写入 SQLite、日志、GitHub 或通知系统。

状态标签：

- **CONFIRMED**：本次检查或可复核的历史记录直接证明。
- **INFERRED**：由源码、时间戳或多个证据推导，不能等同于当前实时观测。
- **UNKNOWN**：当前证据不足，不能安全下结论。

## 1. Executive Summary

### 总结

- **[CONFIRMED] 当前本地 Backend 未运行。** 8787 无监听，未发现使用项目虚拟环境并以 Uvicorn 启动 app.main:app 的 Python 进程；因此本机当前没有新的 heartbeat、Mirror scheduler 或通知处理。
- **[CONFIRMED] 线上 Dashboard 页面仍可访问，但公开数据已过期。** Pages 首页 HTTP 200；最近一次可核实的公开快照发布在 2026-09-09，距离本次审计已超过 15 分钟阈值。
- **[CONFIRMED] 项目功能面已覆盖 Phase A–H.1 的主要代码范围，但当前工作树不是可直接视作生产版本的干净发布物。** 当前 main 比 origin/main 超前 3 个 commit，同时有 20 个已跟踪文件修改、18 个未跟踪文件。
- **[CONFIRMED] 线上部署与本地构建存在版本漂移。** 线上 HTML 引用 index-3gL_p7Te.js，本地 dashboard/dist 引用 index-CplC2sAl.js；不能把本地当前代码等同于线上版本。
- **[CONFIRMED] 历史运行中存在实质性稳定性问题。** Mirror 成功发布间隔平均约 876.7 秒，p95 约 1449.2 秒，最长约 380713 秒；Backend 事件中存在大量网络失败、SQLite lock、事件循环延迟和不完整退出记录。
- **[CONFIRMED] 当前最重要的运行阻断点是 Backend 未启动；当前最重要的发布阻断点是公开数据没有继续成功发布。** 由于 Backend 当前关闭，无法把线上 stale 继续归因到某一个新的 Mirror 网络周期。
- **[UNKNOWN] Edge 中 Profile、Replies、Search Backfill 当前是否仍有 Tab、Content Script 或 Service Worker 活跃。** 本次环境只能发现 Codex In-app Browser，未能读取 Edge 窗口/标签页。

### 结论

当前项目应标记为：

> **代码与历史验收基础较完整；本地生产运行停止；线上 Dashboard 可访问但数据 stale；当前工作树存在大量未提交变更，尚未形成可确认的统一发布版本。**

## 2. Current Architecture

当前设计链路如下：

~~~text
X Profile page / Replies page / Search page
        ↓
MV3 Content Script
  ├─ MutationObserver / fallback scan
  ├─ 60s heartbeat timer
  └─ structured diagnostic event + heartbeat message
        ↓ chrome.runtime.sendMessage
MV3 Service Worker
  ├─ receive/forward heartbeat
  ├─ query tab state
  └─ forward to localhost Backend
        ↓ HTTP POST
Backend 127.0.0.1:8787
  ├─ SQLite heartbeat_history / monitor_health
  ├─ diagnostic events / health evaluator
  ├─ classification / translation / Radar
  ├─ WxPusher Alert Manager
  └─ scheduled/event-triggered GitHub Mirror
        ↓ sanitized export + git push
GitHub data branch / public-data
        ↓ static fetch
GitHub Pages Dashboard
~~~

- **[CONFIRMED]** Dashboard 生产数据源是公开 data branch / public-data 快照，不访问本机 Backend，不新增服务端或数据库。
- **[CONFIRMED]** Backend 是采集、处理、通知和镜像的运行核心；Backend 停止后，Dashboard 仍可能显示历史公开快照，但不会自动得到新数据。
- **[INFERRED]** Extension 侧的 heartbeat 是否经过 Content Script、Service Worker、HTTP、SQLite 四层，需要结合浏览器结构化事件判断；本次无法取得当前 Edge 侧证据。

## 3. Runtime Status

| 组件 | 当前状态 | 最近可确认状态 | 证据 |
|---|---|---|---|
| Backend | **OFFLINE [CONFIRMED]** | 2026-09-09 有 heartbeat | 8787 无 LISTEN，未发现目标 Python/Uvicorn 进程 |
| Profile Monitor | **UNKNOWN [UNKNOWN]** | 2026-09-09 healthy | Edge Tab/Content Script 当前不可读 |
| Replies Monitor | **UNKNOWN [UNKNOWN]** | 2026-09-09 healthy | Edge Tab/Content Script 当前不可读 |
| Search Backfill | **UNKNOWN [UNKNOWN]** | 2026-09-09 healthy | Backend 已关闭，当前无运行证明 |
| Mirror scheduler | **NOT RUNNING [INFERRED]** | 2026-09-09 有最后成功发布 | scheduler 隶属 Backend 生命周期 |
| Dashboard Pages | **HTTP reachable [CONFIRMED]** | 当前请求 HTTP 200 | 首页返回 HTML |
| Dashboard data | **STALE [CONFIRMED]** | published_at 2026-09-09 | 超过 15 分钟 freshness threshold |
| WxPusher | **历史可用，当前运行 UNKNOWN [UNKNOWN]** | DB 有 9 条 sent 记录 | Backend 当前不运行 |

### Backend 启动记录

- **[CONFIRMED]** 最近一次完整运行实例为 backend-20260908T080054-e1e1ad，PID 20860，commit b901c30；启动时间为 2026-09-08T08:00:54.668Z，最后事件为 2026-09-09T09:29:55.576Z，没有对应 BACKEND_SHUTDOWN_COMPLETED。
- **[CONFIRMED]** 2026-09-12T16:38:06 左右的一次启动记录约 1 秒后 process-exit。
- **[CONFIRMED]** 2026-09-12T16:40:37 左右的实例只有 BACKEND_PROCESS_STARTED 和 SQLITE_JOURNAL_MODE，没有 BACKEND_READY，随后进程消失。
- **[UNKNOWN]** 现有事件没有提供第二次启动失败的具体 Windows/Python stderr 根因；不能仅凭“没有 READY”判断是配置、依赖、端口、数据库或进程管理原因。

## 4. Git / Deployment Status

### 本地 Git

| 项目 | 结果 |
|---|---|
| Branch | main |
| Local HEAD | b901c3094bd40da58a1bb32f04972b85e79bde30 |
| origin/main | 2a6b132f6b382dec0e8ee0bb110df127cecd56ca |
| Divergence | local 0 behind / 3 ahead |
| Stash | 无 |
| 工作树 | 20 个已跟踪文件 modified，18 个未跟踪文件 |
| 本轮提交/推送 | **没有 [CONFIRMED]** |

本地领先的 3 个 commit 为：

1. 82ef23f — fix: stabilize live mirror cadence
2. 9099423 — docs: record mirror network outage evidence
3. b901c30 — feat: add mirror and dashboard timing logs

**[CONFIRMED]** 工作树中还存在 Backend、Extension、Dashboard、Mirror、Observability、诊断 CLI、停止脚本和多份报告的未提交变更。它们属于现有工作区状态，本次审计未修改或清理。

### Pages / GitHub Actions

- **[CONFIRMED]** https://oblivionis-ling.github.io/codex-reset-radar/ 当前返回 HTTP 200。
- **[CONFIRMED]** GitHub Actions API 可访问；最近一次列出的 tests 与 Deploy dashboard run 在 2026-09-01 完成且 conclusion=success，head_sha 为 2d46f7ef80d871bbf8cc02f069636a52671bbdae。
- **[CONFIRMED]** 线上 HTML 引用 assets/index-3gL_p7Te.js；本地 dist/index.html 引用 assets/index-CplC2sAl.js。
- **[INFERRED]** 线上 bundle 与当前本地工作树/构建物不一致；不能把本地修改宣称为已部署或生产已验证。
- **[UNKNOWN]** 本次对 raw GitHub meta.json 的直接请求出现 HttpRequestException；远程数据内容依据此前成功读取的快照记录，不能把这次失败请求当作远端不存在。

## 5. Backend

### 设计与实现

- **[CONFIRMED]** start-radar.bat 会切换到项目根目录，优先使用 backend/.venv/Scripts/python.exe，以 -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8787 启动。
- **[CONFIRMED]** stop-backend.bat / scripts/stop-backend.ps1 只匹配项目虚拟环境中的 Python/Pythonw、app.main:app、backend app-dir、8787 端口；不会删除 SQLite。
- **[CONFIRMED]** 配置源码默认 GITHUB_MIRROR_ENABLED=true、GITHUB_MIRROR_INTERVAL_SECONDS=300；当前 .env 未设置这两个覆盖项，因此按源码默认值推导。
- **[INFERRED]** 实际运行时是否曾被环境变量覆盖，只有 Backend 启动时加载的环境快照才能完全证明；当前 Backend 已关闭，不能获得新的运行态配置快照。

### 历史运行证据

- structured event 约 2,928,272 行，未发现 malformed JSONL。
- HTTP_REQUEST_FAILED：4594。
- DB_OPERATION_FAILED：4234。
- HEALTH_EVALUATOR_CYCLE_FAILED：2170。
- EVENT_LOOP_LAG_DETECTED：517，最大事件循环延迟约 213735ms。
- SQLITE_LOCK_DETECTED：218。
- BACKEND_HEARTBEAT_DB_WRITE_FAILED：279。
- PREVIOUS_BACKEND_INSTANCE_UNCLEAN_EXIT：14。
- TASK_FAILED：0。

以上为历史事件统计，**[CONFIRMED]** 证明历史运行存在故障压力；不代表这些错误在当前已关闭进程中仍正在发生。

### 已知源码 Bug

**[CONFIRMED]** backend/app/main.py:1483-1484 当前仍有：

~~~python
outage_started_at = previous_history.changed_at if previous_history else current_time
duration_ms = round((current_time - outage_started_at).total_seconds() * 1000, 3)
~~~

SQLite 读取的 changed_at 是 naive datetime，而 current_time 是 aware datetime；历史运行出现：

~~~text
TypeError: can't subtract offset-naive and offset-aware datetimes
~~~

这会触发 HEALTH_EVALUATOR_CYCLE_FAILED。该问题本次仅记录，没有修复。

## 6. Extension / Collector

### 已实现能力

- **[CONFIRMED]** Content Script 已包含 Profile、Replies、Search 的页面识别、60 秒 heartbeat/fallback timer、MutationObserver、fallback scan、SPA route classification、诊断 ring buffer。
- **[CONFIRMED]** Service Worker 已包含 heartbeat forwarding、HTTP 转发、tab state snapshot，并读取真实可用的 tab_id、url、active、status、discarded、autoDiscardable、pinned、windowId；frozen 字段仅在 API 实际提供时记录。
- **[CONFIRMED]** /thsottiaux/status/<id> 可继承当前 Profile 或 Replies source；Search 不继承，其他用户 status 不继承，直接打开 status 不猜测 monitor。
- **[CONFIRMED]** 相关 parser tests 已通过。

### 当前验证边界与缺口

- **[CONFIRMED]** Extension Vitest 12 passed。
- **[CONFIRMED]** Vite/MV3 build 曾通过，但该 build 不执行 TypeScript 类型检查。
- **[CONFIRMED]** TypeScript 检查失败：extension/src/background.ts:246 使用了类型未声明的 actual_heartbeat_elapsed_ms。
- **[CONFIRMED]** 当前尚未实现或不完整：PING_CONTENT_SCRIPT、HEARTBEAT_TIMER_REGISTERED、FIRST_TICK、pageshow、freeze、resume、context invalidation 的完整事件链，以及真正的 timer 唯一注册保护。
- **[UNKNOWN]** 当前 Edge 是否有两个监控 Tab、Content Script 是否可 ping、observer/timer 是否活跃，本次环境无法验证。

因此，Extension 当前应描述为：**功能主链已实现，生命周期诊断仍不完整，类型检查未通过，当前运行态未知。**

## 7. Classification / AI / Translation

SQLite 当前快照：

| 指标 | 数值 |
|---|---:|
| tweets | 242 |
| classifications | 1382 |
| rule classifications | 671 |
| final classifications | 671 |
| ai classifications | 40 |
| classification_pending=true | 11 |
| classification_conflict=true | 21 |

分类类别：

| category | count |
|---|---:|
| unrelated | 1138 |
| codex_related | 90 |
| reset_hint | 48 |
| quota_information | 46 |
| reset_announcement | 32 |
| reset_confirmed | 26 |
| reset_denial | 2 |

AI usage：

- **[CONFIRMED]** provider 为 deepseek；AI success 40，AI failure 1。
- **[CONFIRMED]** translation_success 135，translation_failure 9。
- **[CONFIRMED]** 最近记录使用 deepseek-v4-flash。
- **[INFERRED]** Phase F 的自动翻译逻辑已经写入代码并产生历史数据，但 Backend 当前不运行，所以没有当前实时翻译吞吐。
- **[UNKNOWN]** 当前 DeepSeek 配额、密钥有效性和下一次请求是否成功；本次没有发起 AI 请求。

## 8. Radar / Forecast / Reset

### 当前本地状态快照

- **[CONFIRMED]** radar_state 只有一条当前记录：state=CONFIRMED、confidence=0.99、urgency=now。
- **[CONFIRMED]** trigger_tweet_id=2091688655828246890。
- **[CONFIRMED]** updated_at=2026-09-09 05:48:23.010411；reason 为匹配“reset 或 limits 已完成”的语言。
- **[CONFIRMED]** radar_state_history 共 9 条历史状态，包含 QUIET、WATCH、LIKELY、ANNOUNCED、CONFIRMED 的转换。
- **[CONFIRMED]** reset_events 表当前行数为 0。

### 公开快照 / Forecast

- **[CONFIRMED]** 上一次成功读取的 data branch 快照为 generated_at=2026-09-09T09:20:56Z、published_at=2026-09-09T17:23:12.8803851+08:00、last_sync_status=success。
- **[CONFIRMED]** 该快照中 Radar 为 CONFIRMED、confidence=0.99、urgency=now；health 快照包含四路 healthy；resets sample_count=4。
- **[CONFIRMED]** forecast source 为 weekly_baseline，last_reset_at=2026-08-31T02:34:27Z，estimated_next_reset_at=2026-09-07T02:34:27Z。
- **[INFERRED]** 由于 estimated_next_reset_at 已早于本次审计日期且公开快照已 stale，当前 Forecast 只能视为历史估算，不能作为实时预测。
- **[UNKNOWN]** reset_events=0 与公开 resets sample_count=4 的生成映射没有在本次运行态中重新验证；这是需要保留的契约/数据一致性观察点。

## 9. Notification

- **[CONFIRMED]** WxPusher provider、Alert Manager、生产/测试/诊断日志分流代码已存在。
- **[CONFIRMED]** accepted_async 只表示 WxPusher API 接受请求，不表示微信客户端已经展示。
- **[CONFIRMED]** alerts 表共 9 条，channel=wxpusher 的 9 条全部 status=sent，无 DB failed 行；类型为 monitor_offline 3、monitor_recovered 4、test 2。
- **[CONFIRMED]** notification-delivery.jsonl 共 827 行、无 malformed 行，其中 WXPUSHER_REQUEST_FAILED 24、WXPUSHER_REQUEST_SUCCESS 3；该文件包含配置检查、抑制、测试和历史尝试，不能与 9 条 DB alert 一一等同。
- **[CONFIRMED]** 历史 Phase C/通知诊断记录显示用户曾收到真实 WxPusher 测试消息。
- **[CONFIRMED]** Windows Toast 代码存在，但当前配置为 disabled。
- **[UNKNOWN]** Backend 重新启动后的 WxPusher 当前可用性；本次没有发送测试或生产通知。

## 10. Mirror

### 设计与实现

- **[CONFIRMED]** 配置目标为 scheduler 300 秒，即 5 分钟。
- **[CONFIRMED]** Backend lifespan 在 github_mirror_enabled 时创建 mirror-scheduler task。
- **[CONFIRMED]** scheduler 使用 scheduled/event trigger、single-flight lock、event dirty 处理；PowerShell script 使用有限重试，延迟序列为 0、30、60、120 秒，最多 4 次。
- **[CONFIRMED]** 日志事件已覆盖 PUBLIC_MIRROR_CYCLE_STARTED、EXPORT_COMPLETED、PUSH_STARTED、SYNC_SUCCESS、SYNC_FAILED、RETRY_SCHEDULED、SYNC_SKIPPED，并设计了 trigger、cycle_started_at、duration、attempt、previous_success_at 等字段。
- **[CONFIRMED]** retry 复用同一次导出 snapshot；published_at 用来区分成功发布时刻，mirror_synced_at 保留为兼容字段。

### 历史统计

| 指标 | 数值 |
|---|---:|
| cycle started | 1539 |
| successful publish | 1021 |
| failed | 2526 |
| retry events | 1989 |
| successful interval average | 约 876.7 秒（14m36.7s） |
| median | 约 300.9 秒 |
| p95 | 约 1449.2 秒 |
| maximum | 约 380713 秒 |
| >7 分钟 | 356 次 |
| >15 分钟 | 162 次 |

失败类型：

- network_connect：1853
- network_reset：608
- network_timeout：36
- unknown：28
- push_failed：1

**[CONFIRMED]** 最后一次成功发布约为 2026-09-09T09:23:15Z。  
**[INFERRED]** 5 分钟 scheduler 与约 14m37s 平均成功发布间隔之间的差异主要来自 GitHub 网络失败和 retry/成功空窗，而不是单凭历史数据证明 scheduler 没有启动。  
**[CONFIRMED]** 当前 Backend 已关闭，因此本次不存在正在运行的 Mirror scheduler；不能宣称已经完成新的 4 周期成功发布验收。

## 11. Dashboard

### 功能

- **[CONFIRMED]** Dashboard 是静态 Vite 前端，使用 base="./"，读取 public-data 的 index、tweets、radar、health、resets、meta。
- **[CONFIRMED]** 首页包含 Current Radar、confidence、urgency、reason、更新时间、Latest Signal、Recent Tweets、Reset history、4 路 Health、Mirror freshness 和简单时间线/日历。
- **[CONFIRMED]** Dashboard 每 60 秒刷新一次；代码中 REFRESH_INTERVAL_MS=60_000。
- **[CONFIRMED]** freshness threshold 为 15 分钟；代码中 DATA_STALE_MS=15*60*1000。
- **[CONFIRMED]** freshness 优先使用 meta.published_at，其次 mirror_synced_at/generated_at；这与“成功发布时刻”语义一致。
- **[CONFIRMED]** refresh history 使用 localStorage key codex-reset-radar-refresh-log，最多保留 100 条；记录请求开始、各文件响应、dashboard_received_at、duration、source snapshot 和错误。
- **[CONFIRMED]** 中文为默认语言，localStorage 仅在明确保存 en 时恢复英文，并提供语言切换。
- **[CONFIRMED]** public-data 请求失败时有 Data unavailable/显示上次成功数据的降级路径；缺失字段会降级到 unknown/empty state。

### 当前线上状态

- **[CONFIRMED]** Pages HTML HTTP 200。
- **[CONFIRMED]** 线上公开数据最近可核实 published_at 在 2026-09-09；以 2026-09-13 审计时间计算，页面显示 stale 是正确行为。
- **[CONFIRMED]** 本地 public-data 目录文件时间主要为 2026-08-31，与 data branch 的 2026-09-09 快照也不一致。
- **[CONFIRMED]** 当前 Dashboard 不访问 localhost，因此 Backend 关闭不会让页面白屏，但会使数据不再前进。
- **[UNKNOWN]** 本次未在真实手机上做新的布局操作验收；移动端布局代码与历史测试存在，但当前线上 bundle 与本地 bundle 不同。

## 12. Observability

### 已实现能力

- **[CONFIRMED]** Backend instance_id、persistent runtime log、daily JSONL shard、bounded tail reader、时间窗口和查询 limit 已实现。
- **[CONFIRMED]** TaskSupervisor、event-loop watchdog、heartbeat history、health transition history、Failure Breadcrumb、trace/component 查询和 SQLite observability indexes 已实现。
- **[CONFIRMED]** H/H.1 相关代码、测试和文档均存在于当前工作树。
- **[CONFIRMED]** diagnose.py 支持 summary、backend、component、trace、outage；component 查询可组合 component、instance_id、trace_id 并合并 Backend event、diagnostic event、heartbeat/SQLite commit 证据。
- **[CONFIRMED]** retention loop、lock classification 和 /health 内存态读取代码存在。

### 仍然不能称为稳定生产能力的原因

- **[CONFIRMED]** 当前 Backend 未运行，观测系统没有当前实时写入。
- **[CONFIRMED]** 诊断 CLI 不支持 ping；无法通过 CLI 对当前 Content Script 执行 PING_CONTENT_SCRIPT。
- **[CONFIRMED]** H.5 生命周期事件仍不完整，无法覆盖所有 timer、freeze、resume、context invalidation 和 Content Script termination 场景。
- **[CONFIRMED]** 历史日志体量很大，且曾出现大量 SQLite lock、HTTP failure 和 event-loop lag。
- **[CONFIRMED]** health evaluator 的 naive/aware datetime Bug 仍在源码中。

## 13. Storage / Performance

### 当前本地数据规模

| 项目 | 数值 |
|---|---:|
| radar.db | 1,292,038,144 bytes，约 1.20 GiB |
| backend/data 全部文件 | 3,153,252,225 bytes，约 3.0 GB |
| heartbeat_history | 87,163 行 |
| monitor_diagnostic_events | 1,098,436 行 |
| health_state_history | 12 行 |
| alerts | 9 行 |
| ai_usage | 185 行 |
| tweet_sources | 326 行 |
| reset_events | 0 行 |
| sync_queue | 0 行 |

- **[CONFIRMED]** SQLite journal_mode 为 delete。
- **[CONFIRMED]** heartbeat、diagnostic、health transition、alerts 等复合索引已经存在。
- **[CONFIRMED]** 最大日志文件包括约 1.10 GB 的 legacy backend event、约 246.8 MiB 的 backend shard、约 147.2 MiB 的另一 backend shard；mirror-cadence.jsonl 约 9.87 MiB。
- **[INFERRED]** H.1 虽然加入 retention/性能机制，但历史数据规模仍说明 retention、运行周期或迁移策略尚未达到可称为“已稳定”的程度。
- **[UNKNOWN]** 当前数据库在 9 月 9 日之后是否能在健康运行下继续增长，以及 retention loop 是否会按预期回收；Backend 关闭期间无法验证。

## 14. Tests / CI

### 本地测试结果

| 范围 | 结果 |
|---|---|
| Backend 从仓库根目录运行 | **57 passed [CONFIRMED]** |
| Backend 按 backend 目录 README 运行 | **失败 [CONFIRMED]**：ModuleNotFoundError: No module named scripts |
| Extension Vitest | **12 passed [CONFIRMED]** |
| Extension TypeScript | **失败 [CONFIRMED]**：actual_heartbeat_elapsed_ms 类型缺失 |
| Extension Vite build | **通过 [CONFIRMED]**，但未执行 tsc |
| Dashboard Vitest | **8 passed [CONFIRMED]** |
| Dashboard TypeScript/build | **通过 [CONFIRMED]** |

**[INFERRED]** 这些结果覆盖了此前工作树快照；由于本轮禁止修改且未重新构建，不能把它们解释成“本次审计后所有未提交变更均已通过完整 CI”。

### GitHub Actions

- **[CONFIRMED]** 最近 API 返回的 tests 和 Deploy dashboard 工作流均有 success run。
- **[UNKNOWN]** GitHub Actions 是否已针对当前本地 HEAD b901c30 及所有未提交变更运行；当前本地改动并未被提交/推送。
- **[CONFIRMED]** 本次未触发任何 CI、Pages 部署或推送。

## 15. Documentation

- **[CONFIRMED]** docs 中存在 Phase A、B、B.5、C、D、E、E.5、F、G、H、H.1 报告。
- **[CONFIRMED]** 已存在 live-data mirror、mirror timing/reliability、public-data contract、observability architecture/contract、operations、troubleshooting、Profile/Replies diagnostic、WxPusher diagnostic 等文档。
- **[INFERRED]** 文档覆盖度较高，但多份阶段报告记录的是过去的运行/部署窗口；不能替代本次审计对当前 Backend、工作树和线上快照的结论。
- **[CONFIRMED]** 本文件是本次审计新增的唯一持久输出。

## 16. Security / Secrets

- **[CONFIRMED]** .env 存在但被 .gitignore 忽略，git ls-files 确认 .env 未被跟踪；.env.example 被跟踪。
- **[CONFIRMED]** 本次没有读取、打印或写入 DeepSeek key、WxPusher token/UID、GitHub token 的值；仅以 redacted/presence 方式核对配置存在性。
- **[CONFIRMED]** 对已跟踪源文件、dashboard/dist、extension/dist 做的已知 token pattern 扫描为 PASS（0 matches）；没有在 bundle 中发现测试模式下的 DeepSeek/GitHub/WxPusher token。
- **[CONFIRMED]** Mirror 日志代码包含文本脱敏逻辑；Dashboard 不包含 Secret、OAuth 或登录系统。
- **[INFERRED]** 目前没有证据表明 Secret 被提交进仓库或前端 bundle。
- **[UNKNOWN]** 本地凭据管理器、Windows 环境变量、Git credential helper 等仓库外存储是否安全；本次没有输出其内容，也没有扩大检查范围。

## 17. Local vs Remote Matrix

| 层 | Local 当前 | Remote/线上当前 | 结论 |
|---|---|---|---|
| Backend process | 无 | 不适用 | **OFFLINE [CONFIRMED]** |
| SQLite | 存在，最后主要写入 9/9 | 不公开 | **历史本地状态 [CONFIRMED]** |
| Local public-data | 主要为 8/31 | data branch 快照至 9/9 | **不一致 [CONFIRMED]** |
| Local dashboard dist | index-CplC2sAl.js | Pages HTML 引用 index-3gL_p7Te.js | **bundle 漂移 [CONFIRMED]** |
| Pages HTML | 不适用 | HTTP 200 | **可访问 [CONFIRMED]** |
| Public snapshot | 不适用 | published_at 9/9 | **stale [CONFIRMED]** |
| Git main | b901c30，ahead 3 | origin/main 2a6b132 | **分叉 [CONFIRMED]** |
| Edge tabs | 本次不可见 | 不适用 | **UNKNOWN [UNKNOWN]** |

## 18. Phase Audit

下表严格区分设计、代码实现、测试、运行、提交、推送、部署和生产验证：

| 子系统 | designed | implemented | tested | committed | pushed | deployed | running | production verified |
|---|---|---|---|---|---|---|---|---|
| Phase A 基础采集/Backend | yes | yes | historical yes | baseline yes | historical yes | local process only | no | historical partial |
| Phase B/B.5 分类校准 | yes | yes | 57 backend tests + historical review | baseline yes; current changes dirty | historical yes | data reflected historically | no | historical partial |
| Phase C WxPusher | yes | yes | real test historically received | baseline plus current dirty changes | historical partial | no separate frontend deployment | no | historical test yes |
| Phase D GitHub data mirror | yes | yes | historical yes | baseline plus later dirty changes | historical partial | data branch historically | no | current no |
| Phase E Pages Dashboard | yes | yes | Dashboard tests/build | baseline yes; current UI changes dirty | historical yes | Pages yes | page online | current data freshness no |
| Phase E.5 live data/freshness | yes | yes | historical timing tests | current mirror/dashboard changes partly dirty | not current | data branch historical | no | current no |
| Phase F 中文/Forecast | yes | yes | Dashboard build/tests historical | current dashboard changes dirty | not current | online bundle may be older | no Backend | current no |
| Phase G Grid Ops UI | yes | yes | local build/tests historical | local current changes not all committed | historical deployment exists | Pages historical | page online | current bundle consistency no |
| Phase H Observability | yes | yes in worktree | H tests historical; current tsc issue remains in Extension | no for untracked H files | no | no | Backend no | no |
| Phase H.1 storage/performance | yes | yes in worktree | tests historical | no for untracked H.1 files | no | no | Backend no | no |
| Profile/Replies SPA fix | yes | yes | parser tests passed | current Extension changes dirty | no current | not applicable | Edge unknown | historical diagnostic only |

## 19. Known Bugs

1. **[CONFIRMED] Health evaluator datetime 类型错误**：backend/app/main.py:1483-1484 对 naive/aware datetime 直接相减，历史触发 HEALTH_EVALUATOR_CYCLE_FAILED。
2. **[CONFIRMED] Extension tsc 类型错误**：background.ts:246 使用 actual_heartbeat_elapsed_ms，但对应类型未声明。
3. **[CONFIRMED] Backend 工作目录测试入口不一致**：从仓库根目录可通过，从 backend 目录运行 README 方式缺少 scripts module path。
4. **[CONFIRMED] diagnose CLI 没有 ping 命令**：无法完成只读 PING_CONTENT_SCRIPT 诊断闭环。
5. **[CONFIRMED] Extension 生命周期诊断不完整**：缺少/不完整的 PING、timer registration/first tick、pageshow、freeze/resume、context invalidation 和 timer single-registration evidence。
6. **[CONFIRMED] 线上与本地 Dashboard bundle 不一致**：当前本地 dist asset 与线上 HTML asset 名不同。
7. **[CONFIRMED] Mirror 历史成功发布间隔不稳定**：存在 162 次超过 15 分钟的成功间隔，最大间隔约 105.8 小时。
8. **[CONFIRMED] Backend 启动失败证据不完整**：9/12 第二个启动实例没有 READY，但没有对应 stderr/root error。
9. **[INFERRED] public-data 的兼容时间字段仍有双语义风险**：mirror_synced_at 是 snapshot/export 时间，published_at 才是成功发布时间；当前 Dashboard 已优先使用 published_at，但旧消费者可能仍只看 mirror_synced_at。
10. **[UNKNOWN] Profile/Replies 当前掉线发生层级**：没有当前 Edge Tab、Content Script、Service Worker 的实时事件，不能新增归因。

## 20. Known Risks

- **[CONFIRMED] 运行风险**：Backend 停止会同时停止采集、健康状态更新、分类、通知和 Mirror scheduler。
- **[CONFIRMED] 数据新鲜度风险**：Dashboard freshness 逻辑正确，但数据源长时间无成功发布时会显示 stale；这不是前端误判。
- **[CONFIRMED] 网络风险**：历史 GitHub connect/reset/timeout 失败占 Mirror failure 的主要部分。
- **[CONFIRMED] 资源风险**：SQLite 约 1.20 GiB，backend/data 约 3.0 GB，诊断事件量超过百万行。
- **[CONFIRMED] 观测风险**：Backend shutdown/启动失败路径和 Edge lifecycle 仍存在 blind spot。
- **[INFERRED] 发布风险**：本地工作树的未提交改动较多，若不先整理版本边界，容易出现“本地已修复、线上仍旧版本”或误提交用户已有改动。
- **[UNKNOWN] 当前 Edge 是否有 discard/freeze 或扩展 reload 事件**：本次无法访问 Edge，不做推断。

## 21. Technical Debt

1. 统一 Backend 启动、停止、测试和工作目录的入口语义。
2. 修复 health evaluator datetime 类型边界。
3. 清理并定义旧 legacy event 与新 observability shard 的保留/归档策略。
4. 为 diagnose 增加 ping 及更完整的 Extension lifecycle 查询。
5. 解决 Extension 类型声明与实际 heartbeat metadata 的漂移。
6. 明确定义 generated_at、mirror_synced_at、published_at、dashboard_received_at 的消费者契约。
7. 建立从当前 commit 到 Pages bundle/data branch 的可追溯发布标识。
8. 将历史阶段报告与当前运行态分开，避免把“历史验收通过”误读为“当前正在运行”。

## 22. Product / UX Current Gaps

- **[CONFIRMED]** 用户能访问 Dashboard，但当前 stale 时需要依靠最后已知 Radar/Health；这符合设计，但不能提供新的实时状态。
- **[CONFIRMED]** Dashboard 有中文默认和英文切换，基本信息密度、Health、Mirror freshness、Signal、Reset history 均已具备。
- **[UNKNOWN]** 当前线上 bundle 是否已经包含本地最新的中文信息体验、Forecast 和 Grid Ops 全部改动；asset 不一致，无法直接确认。
- **[CONFIRMED]** Dashboard 没有登录、账号系统、复杂图表或本机 Backend 依赖，符合既定边界。
- **[INFERRED]** 对运维用户而言，当前最直接的体验缺口是无法在页面内区分“Backend 未运行”“GitHub mirror stale”“页面请求失败”这三种不同原因；现有公开数据只能显示最后快照和 freshness。

## 23. Manual Operational Requirements

当前正常工作流应保持：

1. 从项目根目录运行 start-radar.bat，确认出现 Uvicorn 启动并检查 http://127.0.0.1:8787/health。
2. 不使用不在工作流内的旧 Backend 进程；停止时使用 stop-backend.bat 或 scripts/stop-backend.ps1，仅针对项目虚拟环境和 8787 目标。
3. Edge 中保持 Profile、Replies、Search 页面和扩展运行；涉及扩展变更时由用户手动 reload/刷新页面。
4. 运行后观察 Backend ready、四路 heartbeat、Mirror cycle/success 和 public published_at。
5. Dashboard 只读取公开数据；不要把本机 localhost 配置、Secret 或通知凭据放进前端。
6. 发布前先审阅当前 dirty/untracked 文件，确认哪些属于本次变更，再提交和推送；本次审计没有代为提交。

以上是操作要求，不表示本次审计执行了启动、reload、刷新、提交或推送。

## 24. Recent Incident Timeline

| 时间 | 事件 | 状态 |
|---|---|---|
| 2026-09-08 08:00:54Z | backend-20260908T080054-e1e1ad 启动 | **CONFIRMED** |
| 2026-09-09 05:48:23Z | 本地 Radar 状态更新为 CONFIRMED 0.99 | **CONFIRMED** |
| 2026-09-09 09:20:56Z | 最近公开快照 generated_at | **CONFIRMED（上次成功读取）** |
| 2026-09-09 09:23:15Z | 最近一次 Mirror 成功发布附近时间 | **CONFIRMED（历史日志）** |
| 2026-09-09 09:29:55Z | 最近一次 Backend event/heartbeat | **CONFIRMED** |
| 2026-09-12 16:38:06 左右 | 一次启动后约 1 秒 process-exit | **CONFIRMED** |
| 2026-09-12 16:40:37 左右 | 一次启动只有 STARTED/JOURNAL，没有 READY | **CONFIRMED** |
| 2026-09-13 | 本次审计：8787 无监听，Pages HTTP 200 但数据 stale | **CONFIRMED** |

## 25. Current System Health Matrix

| 维度 | 状态 | 说明 |
|---|---|---|
| Backend availability | **OFFLINE [CONFIRMED]** | 端口和进程均不存在 |
| Backend startup reliability | **WARNING [CONFIRMED]** | 9/12 有未 READY/快速退出记录，具体原因 UNKNOWN |
| SQLite availability | **PRESENT [CONFIRMED]** | 可只读查询；历史规模很大 |
| Profile | **UNKNOWN [UNKNOWN]** | 最近历史记录 healthy，当前 Edge 不可观测 |
| Replies | **UNKNOWN [UNKNOWN]** | 最近历史记录 healthy，当前 Edge 不可观测 |
| Search Backfill | **UNKNOWN [UNKNOWN]** | 最近历史记录 healthy，Backend 当前关闭 |
| Mirror scheduler | **STOPPED [INFERRED]** | 随 Backend 停止 |
| Mirror reliability | **DEGRADED [CONFIRMED]** | 历史失败多、成功间隔长 |
| Public data | **STALE [CONFIRMED]** | 最近成功 published_at 为 9/9 |
| Dashboard HTTP | **HEALTHY [CONFIRMED]** | Pages 返回 200 |
| Dashboard deployment consistency | **RISK [CONFIRMED]** | 线上/本地 asset 不同 |
| Radar snapshot | **LAST KNOWN CONFIRMED [CONFIRMED]** | 不是当前实时判断 |
| WxPusher | **HISTORICALLY WORKING [CONFIRMED]** | 当前 Backend 关闭，当前送达 UNKNOWN |
| Observability | **PARTIAL [CONFIRMED]** | 代码和历史数据存在，但生命周期与启动失败仍有盲区 |

## 26. Evidence Appendix

### 本次使用的只读证据

- Windows TCP/process 查询：8787 LISTENING 不存在；无目标 Uvicorn/Python process。
- Git status/log/rev-list：main、HEAD b901c30、origin/main 2a6b132、ahead 3、dirty/untracked 状态。
- SQLite read-only URI 查询：表结构、行数、Radar、classification、AI usage、alerts、health、heartbeat 时间戳。
- backend/data 文件清单：SQLite、runtime、structured events、Mirror、notification 日志体量。
- GitHub Actions API：最近 tests/Deploy dashboard run 的状态。
- Pages HTTP 请求：HTTP 200、线上 HTML asset。
- token pattern 扫描：tracked source/bundle 仅输出 PASS/RISK 结果，不输出 Secret。
- 源码静态检查：Backend config/lifespan/health evaluator/Mirror、Extension heartbeat/diagnostic、Dashboard freshness/language/base path。

### 关键本地文件

- backend/app/main.py：Backend lifespan、health evaluator、Mirror scheduler、HTTP/SQLite 处理。
- backend/app/config.py：Mirror 默认配置。
- backend/app/observability.py：统一 observability writer、retention、watchdog 和查询基础。
- extension/src/content.ts：Content Script timer、observer、fallback、heartbeat。
- extension/src/background.ts：Service Worker forwarding、HTTP、tab snapshot。
- extension/src/parser.ts：Profile/Replies/Search route classification。
- dashboard/src/main.ts：中文默认、60 秒刷新、Dashboard received log、页面渲染。
- dashboard/src/data.ts：15 分钟 freshness、public-data schema 降级。
- scripts/sync-github-data.ps1：public export、worktree、Git push、retry 和 mirror 日志。
- start-radar.bat / stop-backend.bat：规定的 Backend 启停入口。

### Remaining Blind Spots

1. **[UNKNOWN]** Edge 当前 Tab、discarded/frozen、Content Script ping、Service Worker instance 和 ring buffer 不能在本次环境读取。
2. **[UNKNOWN]** 2026-09-12 未 READY Backend 实例的 Windows/Python stderr 没有保存在现有 structured event 中。
3. **[UNKNOWN]** raw GitHub meta.json 本次请求失败；远程快照结论使用此前成功读取的 data branch 证据。
4. **[UNKNOWN]** 当前线上 bundle 是否对应本地未提交改动，无法由 asset 文件名之外的证据确认。
5. **[UNKNOWN]** 当前重新启动后 Mirror、DeepSeek 和 WxPusher 的实时可用性；本次没有启动或发送请求。

### 本轮变更审计

~~~text
Audit completed

New persistent file:
docs/current-development-state-audit-2026-09-13.md

Runtime modified:
no

Backend restarted:
no

Extension reloaded:
no

SQLite modified:
no

Production notification sent:
no
~~~
