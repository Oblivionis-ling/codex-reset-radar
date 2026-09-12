# Codex Reset Radar — Unified Observability Architecture

## 1. 存储布局

```text
backend/data/observability/
├── runtime/
│   └── backend-runtime.log          # TimedRotatingFileHandler，14 天
└── events/
    ├── backend.jsonl                # 生命周期、HTTP、任务、DB、健康变化
    ├── mirror.jsonl                 # Mirror 统一事件
    ├── notifications.jsonl          # 生产通知统一事件
    ├── notifications-test.jsonl     # 测试环境
    └── notifications-diagnostic.jsonl # /api/alerts/test
```

兼容文件仍保留：

```text
backend/data/mirror-cadence.jsonl
backend/data/notification-delivery.jsonl
```

它们现在由统一 `append_event()` 写入，不再由各模块分别实现文件写入。运行时日志同时输出到 Console 和 rotating file。结构化事件保留 30 天，heartbeat history 保留 14 天。

## 2. 数据与事件归属

| 类型 | 归属 |
|---|---|
| 当前状态 | SQLite `monitor_health`、`radar_state` |
| 历史审计 | SQLite `heartbeat_history`、`health_state_history`、`monitor_diagnostic_events`、`radar_state_history`、`alerts` |
| 高吞吐/外部操作 | JSONL Mirror、Notification、Backend events |
| Python 生命周期与 traceback | `backend-runtime.log` |
| Extension 断线期间的证据 | `chrome.storage.local` ring buffer，最多 500 条 |
| Dashboard refresh history | 当前页面 `localStorage`，不上传用户浏览行为 |

## 3. Backend 生命周期

启动、ready、关闭和异常由 Backend instance 关联：

```text
BACKEND_PROCESS_STARTED
PREVIOUS_BACKEND_INSTANCE_UNCLEAN_EXIT  # 上次只有 STARTED 没有 SHUTDOWN_COMPLETED
BACKEND_READY
TASK_STARTED / TASK_STOPPED / TASK_FAILED
EVENT_LOOP_LAG_DETECTED
BACKEND_SHUTDOWN_STARTED / BACKEND_SHUTDOWN_COMPLETED
```

长期 asyncio task 由 `TaskSupervisor` 登记。当前策略是 bounded observability：发现并持久化 task death，不对所有任务无限自动重启。

## 4. Health

`monitor_health` 继续作为快速 current-state 表，新增 `heartbeat_history` 保存每次收到的 heartbeat：

```text
client_observed_at
backend_received_at
db_committed_at
component / instance_id / sequence / trace_id / request_id
```

`health_state_history` 只记录状态变化，并产生 `HEALTH_STATE_CHANGED`。进入 offline 时产生 `FAILURE_BREADCRUMB`，恢复时产生带 outage duration 的 `COMPONENT_RECOVERED`。

`GET /health` 和 `GET /api/health` 都是读取接口。Health Evaluator 在后台周期计算状态并触发 Alert Manager，查询本身不再改变 heartbeat 或 alerts。

## 5. 本地查询 API

```text
GET /api/observability/summary
GET /api/observability/trace/{trace_id}
GET /api/observability/component/{component}
GET /api/observability/errors
```

这些 API 仅绑定在本地 Backend 上，不暴露给 GitHub Pages。

## 6. Dashboard / Mirror

每次 export 生成 `snapshot_id`，随 `meta.json` 进入 data branch。Dashboard 每一轮刷新生成 `refresh_id`，保存：

```text
dashboard_instance_id
refresh_id
source_snapshot_id
source_age_ms
network_duration_ms
published_at
dashboard_received_at
```

这样可以把 Dashboard 当前看到的 snapshot 与 Mirror 的成功 push 关联起来，而不需要 Dashboard 访问本机 Backend。

