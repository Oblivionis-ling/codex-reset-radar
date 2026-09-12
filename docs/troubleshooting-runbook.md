# Codex Reset Radar — Troubleshooting Runbook

所有命令从仓库根目录执行。诊断 CLI 只读，不会 reload Edge、修改阈值或写入业务数据。

## 1. Backend Offline

先执行：

```powershell
python scripts/diagnose.py backend
python scripts/diagnose.py summary
```

检查：

1. 最新 `BACKEND_PROCESS_STARTED`、`BACKEND_READY`。
2. 是否出现 `PREVIOUS_BACKEND_INSTANCE_UNCLEAN_EXIT`。
3. `TASK_FAILED` 是否指向 `backend-heartbeat`。
4. `EVENT_LOOP_LAG_DETECTED` 是否超过 2 秒或 10 秒。
5. `BACKEND_HEARTBEAT_DB_WRITE_FAILED`、`SQLITE_LOCK_DETECTED`。

如果有新 STARTED 但没有旧 SHUTDOWN_COMPLETED，说明上个进程是非正常结束；如果进程仍在而 heartbeat task failed，应按 task / DB / event-loop 记录继续判断。

## 2. Profile / Replies Offline

```powershell
python scripts/diagnose.py component profile
python scripts/diagnose.py component replies
```

按同一个 heartbeat 的 `trace_id` 检查：

```text
HEARTBEAT_CREATED
HEARTBEAT_SW_RECEIVED
HEARTBEAT_HTTP_STARTED
HEARTBEAT_HTTP_SUCCESS / HEARTBEAT_HTTP_FAILED
HEARTBEAT_BACKEND_RECEIVED
HEARTBEAT_DB_COMMITTED
```

判断顺序：

1. 没有新的 `HEARTBEAT_CREATED`：Content Script timer、页面 freeze 或 route guard。
2. 有 Created，没有 SW Received：Service Worker 生命周期或消息投递。
3. 有 HTTP Started，没有 Backend Received：localhost / Backend 网络层。
4. 有 Backend Received，没有 DB Committed：SQLite 写入或 commit。
5. heartbeat 仍有，但 `sequence` 缺号：检查 `HEARTBEAT_SEQUENCE_GAP`。
6. `LOCATION_CHANGED` 进入 `/status/<id>`、`activeSource` 变空：SPA route guard。
7. `FALLBACK_SCAN_COMPLETED` 仍在而 heartbeat 没有：heartbeat timer 独立停止。

## 3. Mirror Stale

```powershell
Get-Content .\backend\data\mirror-cadence.jsonl -Tail 100
python scripts/diagnose.py summary
```

检查同一 `trace_id` 的：

```text
PUBLIC_MIRROR_CYCLE_STARTED
PUBLIC_MIRROR_EXPORT_COMPLETED
PUBLIC_MIRROR_PUSH_STARTED
PUBLIC_MIRROR_RETRY_SCHEDULED
PUBLIC_MIRROR_SYNC_SUCCESS / PUBLIC_MIRROR_SYNC_FAILED
```

`SYNC_SUCCESS.sync_finished_at` 才是 push 成功证据；`mirror_synced_at` 是快照生成时间。看 `error_type` 区分 network、Git conflict、auth 等。

## 4. WxPusher Missing

```powershell
Get-Content .\backend\data\notification-delivery.jsonl -Tail 100
python scripts/diagnose.py summary
```

按 `trace_id` 查：

```text
ALERT_RECEIVED
ALERT_DISPATCH_STARTED
WXPUSHER_REQUEST_STARTED
WXPUSHER_REQUEST_SUCCESS / WXPUSHER_REQUEST_FAILED
WXPUSHER_RETRY_SCHEDULED
```

`accepted_async` 只表示 WxPusher API 接受请求，不表示微信客户端已经展示。测试 API 使用 `environment=diagnostic`，不会混入生产通知日志。

## 5. Dashboard Stale

在 Dashboard 当前浏览器 Console 执行：

```js
JSON.parse(localStorage.getItem("codex-reset-radar-refresh-log") || "[]").slice(-20)
```

比较：

```text
source_snapshot_id
published_at
source_age_ms
dashboard_received_at
network_duration_ms
```

HTTP 200 且 `network_duration_ms` 正常，但 `source_age_ms` 超过 15 分钟，说明公开 Mirror 没有新成功发布，不是 Dashboard 请求故障。

## 6. DeepSeek Failure

检查 Backend runtime log 与 `ai_usage`：

```text
TWEET_PROCESSING_FAILED
AI_CLASSIFICATION_FAILED
TWEET_TRANSLATION_FAILED
```

AI 失败应保留规则分类 fallback，不应导致 Collector、Radar 或通知进程退出。

