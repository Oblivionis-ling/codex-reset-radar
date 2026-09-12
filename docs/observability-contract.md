# Codex Reset Radar — Observability Contract

本契约定义 Phase H 的本地全链路日志字段、时间语义、身份和错误分类。所有机器可读事件使用 UTC ISO-8601；Dashboard 仅在显示层转换为 Asia/Shanghai。

## 1. 统一事件 envelope

统一 JSONL 事件尽可能包含：

```json
{
  "timestamp": "2026-09-03T08:43:12.384Z",
  "event": "HEARTBEAT_DB_COMMITTED",
  "level": "INFO",
  "component": "profile_monitor",
  "instance_id": "profile-cs-...",
  "trace_id": "hb-profile-...-314",
  "request_id": "req-...",
  "sequence": 314,
  "duration_ms": 25,
  "result": "success",
  "error_type": null,
  "metadata": {}
}
```

字段可以为空，但不能改变含义。事件专用字段可以继续放在 envelope 顶层，`metadata` 保存不适合通用查询的上下文。

## 2. 时间字段

| 字段 | 含义 |
|---|---|
| `timestamp` | 该结构化事件写入时的 UTC 时间 |
| `observed_at` | 客户端或外部组件观察到事件的时间 |
| `received_at` / `backend_received_at` | Backend 收到请求的时间 |
| `started_at` / `push_started_at` | 操作开始时间 |
| `finished_at` / `sync_finished_at` | 操作完成时间；Mirror 成功时表示 push 返回后 |
| `generated_at` / `snapshot_generated_at` | 数据快照生成时间 |
| `published_at` | 数据被标记为公开发布的时间；严格成功证据仍看 `SYNC_SUCCESS.sync_finished_at` |
| `db_committed_at` | SQLite commit 完成时间 |
| `dashboard_received_at` | Dashboard 完成一轮公开文件请求并准备渲染的浏览器时间 |

`source_age_ms` 表示 `dashboard_received_at - published_at`；`network_duration_ms` 表示浏览器请求耗时。二者不能替代彼此，也不能直接当成 freshness。

## 3. Instance / sequence / trace / request

- `backend_instance_id`：Backend 进程每次启动生成，整个进程生命周期不变。
- `extension_instance_id`：MV3 Service Worker 每次生命周期生成。
- `content_instance_id`：Content Script 每次注入页面生成。
- `dashboard_instance_id`：Dashboard 页面 session 生成并保存在 `sessionStorage`。
- `sequence`：同一长期组件、同一 instance 内单调递增；缺号产生 `HEARTBEAT_SEQUENCE_GAP`。
- `trace_id`：一个业务动作的跨层 ID，例如 `hb-profile-...-314`、`mirror-...`、`tweet-...`。
- `request_id`：某一次 HTTP 请求的 ID；同一个 trace 可以有多个 request。

Profile / Replies heartbeat 的链路是：

```text
HEARTBEAT_CREATED
→ HEARTBEAT_SW_RECEIVED
→ HEARTBEAT_HTTP_STARTED
→ HEARTBEAT_BACKEND_RECEIVED
→ HEARTBEAT_DB_COMMITTED
```

Backend 自身 60 秒 heartbeat 另外使用
`BACKEND_HEARTBEAT_DB_WRITE_STARTED/SUCCESS/FAILED` 记录数据库写入边界；
`HEARTBEAT_DB_COMMITTED` 仍是跨层 heartbeat trace 的统一提交事件。

## 4. 日志级别

- `DEBUG`：正常调试细节
- `INFO`：重要生命周期和业务事件
- `WARNING`：异常但可恢复，例如状态变化、慢操作、event-loop lag
- `ERROR`：操作失败
- `CRITICAL`：进程或关键任务无法继续

正常的 60 秒 heartbeat 主要进入 `heartbeat_history` 和结构化事件，不重复污染 runtime INFO 文本日志。

## 5. 错误分类

统一大类：`PROCESS`、`TASK`、`EVENT_LOOP`、`HTTP`、`DATABASE`、`EXTENSION`、`MIRROR`、`GITHUB`、`NOTIFICATION`、`WXPUSHER`、`AI`、`DASHBOARD`。

Mirror 的细分类继续使用 `network_connect`、`network_timeout`、`network_reset`、`network_dns`、`clone_failed`、`fetch_failed`、`push_failed`、`git_conflict`、`auth_failed`、`unknown`。

任何 Token、Authorization、Cookie、UID 和 API Key 都必须脱敏；日志不得记录完整业务 payload 或 Tweet 正文。
