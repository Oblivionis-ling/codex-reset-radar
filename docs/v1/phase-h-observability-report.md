# Codex Reset Radar — Phase H 全链路可观测性阶段报告

报告日期：2026-09-03

本轮收尾状态：代码与隔离 smoke test 已通过；8787 上原有 Backend 仍是旧进程，尚未加载本次 Phase H 代码。当前 Windows 执行策略拒绝停止该 PID，因此本报告不把隔离 8788 验证冒充为生产实例已切换；重启步骤见第 7 节。

## 1. Before

改造前日志分散在 Backend stdout、SQLite 当前状态、浏览器 Console、Mirror JSONL、Notification JSONL 和 Dashboard localStorage。主要问题是 Backend stdout 不持久化、heartbeat 没有历史、各层没有统一 trace、GET health 有副作用、通知测试与生产记录混合。

## 2. 已实现架构

```text
Content Script
  → Service Worker
  → Backend HTTP middleware
  → SQLite heartbeat_history / monitor_health
  → Health Evaluator / Alert Manager

Tweet
  → ingest trace
  → classification / Radar / notification trace
  → Mirror trace + snapshot_id
  → Dashboard refresh_id + source_snapshot_id
```

底层时间统一 UTC ISO-8601；页面显示仍可使用北京时间。

## 3. 已实现内容

- 新增统一 `append_event()` 和共同事件 envelope。
- 新增 `backend/data/observability/runtime/backend-runtime.log`，Console 与按天 rotating file 双写，runtime backup 保留 14 天。
- Backend 生成稳定 `backend_instance_id`，记录 STARTED、READY、SHUTDOWN 和 unclean-exit evidence。
- 新增 `TaskSupervisor`，记录长期 task 的 STARTED / STOPPED / FAILED。
- 新增 event-loop watchdog；lag 超过 2 秒记录 WARNING，超过 10 秒记录 ERROR。
- Backend heartbeat loop 增加 tick、schedule drift、DB write started / success / failed / committed 记录。
- Heartbeat 事件同时保留 Content/Service Worker `instance_id` 与 Backend `backend_instance_id`；状态转移关联最近 heartbeat 的 `trace_id`，Failure Breadcrumb 带最近 lag / DB / HTTP 错误上下文。
- 新增 SQLite `heartbeat_history`，保留 client、Backend、DB 三段时间、sequence、trace、request 和 metadata。
- 新增 `health_state_history`、`HEALTH_STATE_CHANGED`、`FAILURE_BREADCRUMB`、`COMPONENT_RECOVERED`。
- `GET /health` 与 `GET /api/health` 改为读取接口；Health Evaluator 后台执行状态计算。
- Extension 增加 Service Worker / Content Script instance ID、heartbeat sequence、trace ID、request ID 和 500 条 `chrome.storage.local` offline ring buffer。
- Extension 增加 `HEARTBEAT_CREATED`、`HEARTBEAT_SW_RECEIVED`、`HEARTBEAT_HTTP_STARTED/SUCCESS/FAILED`，Backend 恢复后按最多 50 条批量回补诊断。
- Mirror 接入统一 envelope，保持 `PUBLIC_MIRROR_*` 事件、bounded retry 和旧日志路径兼容；export 增加 `snapshot_id`。
- Notification 增加 trace 与 environment；测试和 diagnostic 日志不再写入生产 notification log。
- Tweet processing trace 覆盖分类、翻译、Radar 与 notification correlation，翻译成功、跳过和失败均有结构化事件。
- Dashboard 增加 `dashboard_instance_id`、`refresh_id`、`source_snapshot_id`、`source_age_ms` 和 `network_duration_ms`，保留静态站点本地存储原则。
- 新增本地只读 API：summary、trace、component、errors。
- 新增 `scripts/diagnose.py`：summary、backend、component、trace、outage。
- 新增 runtime / event / heartbeat retention；SQLite journal mode 已观测为 `delete`，本阶段没有未经测试切换生产数据库。

## 4. Trace 示例

一次 Profile heartbeat 现在可以按一个 trace 查询：

```text
HEARTBEAT_CREATED
HEARTBEAT_SW_RECEIVED
HEARTBEAT_HTTP_STARTED
HEARTBEAT_BACKEND_RECEIVED
HEARTBEAT_DB_COMMITTED
```

如果只出现前三项，问题在 Service Worker 到 localhost Backend；如果出现 Backend Received 但没有 DB Committed，问题在 SQLite 写入层。

## 5. 故障演练与回归测试

已完成自动化验证：

- Backend pytest：51 passed。
- Extension Vitest：12 passed；MV3 production build passed。
- Dashboard Vitest：8 passed；TypeScript check 与 production build passed。
- `/health`、`/api/health` 连续读取不会新增 heartbeat history。
- heartbeat 带 instance / sequence / trace 后，可从 observability trace API 查询 Backend Received 和 DB Committed。
- 人为抛出长期 task 异常会产生 `TASK_FAILED`，不会静默消失。
- 既有 Mirror network error、retry、lock、secret redaction 测试继续通过。
- 既有 WxPusher HTTP、API response、sendRecordId、secret redaction 测试继续通过。
- Dashboard 既有 stale、empty signal、missing health、HTTP trace 测试继续通过。
- 测试 fixture 已将临时 TestClient 的 observability/runtime/notification 输出隔离到临时目录，避免回归测试污染生产日志。

本轮没有对生产 Backend 做强杀、真实 Edge freeze、真实 GitHub 断网或真实 WxPusher 失败演练，避免污染正在运行的业务数据；这些场景已在 runbook 中定义为后续安全演练步骤。

## 6. 当前盲区

仍无法凭应用日志保证记录以下事件：

- Windows 强制结束、SIGKILL、断电或机器崩溃前的 shutdown event；只能通过上一次 STARTED 无 COMPLETED 和下一次 STARTED 推断。
- 浏览器在页面 freeze / discard 前来不及写入 ring buffer 的最后瞬间。
- Dashboard 只保留在本地浏览器，不会把用户浏览行为上传 Backend。
- GitHub CDN / Raw 缓存层的可见时间仍可能晚于 push 成功时间。
- WxPusher `accepted_async` 不能证明微信客户端已经显示。

因此本阶段目标是“故障可解释”，不是宣称 100% 记录所有外部故障。

## 7. 激活与运行验收

隔离 smoke test 使用临时 SQLite、临时 observability 目录、8788 端口，并关闭 Mirror/WxPusher，确认新代码可以正常启动：

- `/health` 返回 `ready=true` 和 `backend_instance_id`。
- `/api/observability/summary` 返回 Backend uptime、4 类长期 task 和组件快照。
- `backend-heartbeat`、`health-evaluator`、`event-loop-watchdog`、`observability-retention` 均处于 `running`。
- smoke 目录已清理，没有写入生产 SQLite 或生产日志。

检查 8787 时发现现存进程仍返回旧版 `/health` 响应（没有 `ready` / `backend_instance_id`），说明它是在 Phase H 代码加载前启动的。请在方便时关闭该旧 Backend，然后从仓库根目录重新运行 `start-radar.bat`；SQLite 数据不会被删除。重启后应确认：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/health | ConvertTo-Json
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py summary
```

第一条应包含 `ready=true`、`backend_instance_id`；第二条的 task 状态应为 `running`。真实 30 分钟运行、Edge freeze/discard、GitHub 断网与 WxPusher 失败演练仍属于外部运行态验收，不在本轮隔离测试中伪造结论。

## 8. 性能与磁盘影响

本次检查时：

- SQLite `journal_mode=delete`，未改生产数据库模式。
- `backend-runtime.log` 约 86 KB。
- Unified backend events 约 245 KB，Mirror events 约 20 KB，Notification events 约 126 KB。
- 现有 `radar.db` 约 138 MB；heartbeat history 受 14 天 retention 限制。

正常 heartbeat 不写普通 INFO 文本日志；事件 JSONL 为追加写入，日志失败采用 best-effort，不应拖停 Collector、Radar 或 Alert Manager。

## 9. 结论

Phase H 已建立本地优先的 Unified Observability 基础：Backend 生命周期、task、event-loop、heartbeat、浏览器链路、Mirror、通知和 Dashboard 现在拥有统一身份与时间关联。代码和隔离 smoke 已验收；生产 8787 进程仍待用户按既有方式重启后才会实际使用这套日志。之后排查 Backend 或 Profile / Replies 掉线时，优先使用 `diagnose.py` 和 trace API，不再只依赖单个 `offline` 状态猜测原因。
