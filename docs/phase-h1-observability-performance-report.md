# Codex Reset Radar — Phase H.1 Observability Performance & Storage Stabilization

报告日期：2026-09-08（Asia/Shanghai）

## 1. 执行结论

H.1 的代码、查询边界、存储重构和回归测试已完成。隔离环境验证表明，新的 `/health`、`/api/radar`、Observability summary 和 errors 查询均保持毫秒级，且大文件 tail reader 不再调用 `read_text().splitlines()`。

生产 8787 当前仍有 2026-09-03 启动的旧 Backend 实例。已按正常流程执行 `stop-backend.bat`，但 Windows 拒绝非强制结束其 Uvicorn 子进程；本轮没有擅自使用 `-Force`，因此不能把隔离测试冒充成生产切换后的 30–60 分钟验收。生产切换需要用户确认后执行：

```powershell
.\scripts\stop-backend.ps1 -Force
.\start-radar.bat
```

SQLite 数据不会因该重启被删除。

## 2. Root Cause

H.1 前的主要退化链路是：

```text
大型 backend.jsonl
  → read_text().splitlines()
  → 单次读入接近 1 GB
  → Python 内存峰值约 1.85 GB
  → event loop lag
  → SQLite 长读事务 / writer lock 竞争
  → heartbeat 写入失败、/health 和 /api/radar 变慢
```

历史事件统计也确认了重复成功日志是主要增长来源：每条诊断写入都会额外生成 `DB_OPERATION_COMPLETED`，普通 HTTP 请求同时生成 started/completed 两条事件。SQLite 诊断表也已增长到约 80 万行，旧 trace 查询存在全表读取路径。

这不是 Collector、Radar、DeepSeek、Mirror cadence 或通知规则本身的问题。

## 3. 修复前基线

任务书给出的基线：

| 指标 | 修复前 |
|---|---:|
| `radar.db` | 约 676.8 MB |
| `heartbeat_history` | 46,667 行 |
| `monitor_diagnostic_events` | 699,984 行 |
| Backend unified JSONL | 约 894.3 MB |
| Backend RSS 峰值 | 约 1.85 GB |
| 最大 event-loop lag | 约 139 秒 |
| `/health`、`/api/radar` | 曾出现 5–8 秒无响应 |
| 已观察到的异常 | `database is locked`、`BACKEND_HEARTBEAT_DB_WRITE_FAILED` |

本轮离线流式盘点到的当前存储规模（不会作为运行时查询路径）：

| 指标 | 当前盘点值 |
|---|---:|
| `radar.db` | 864,026,624 bytes |
| `heartbeat_history` | 56,818 行 |
| `monitor_diagnostic_events` | 808,789 行 |
| 事件记录总数 | 2,038,448 条 |
| 事件 JSONL 总字节数 | 1,108,555,347 bytes |
| 最大旧归档 | 1,097,314,325 bytes |

最大的旧归档是历史单文件，已经被改名保存，不会被新查询器当作日分片读取，也没有被删除。

## 4. JSONL Top 20

以下统计是一次离线、逐行流式盘点，结果只用于容量分析；运行时 API 不会执行这次全文件扫描。

| 事件类型 | 数量 | 字节估算 |
|---|---:|---:|
| `DB_OPERATION_COMPLETED` | 652,238 | 345,678,872 |
| `HTTP_REQUEST_STARTED` | 387,149 | 204,512,063 |
| `HTTP_REQUEST_COMPLETED` | 382,712 | 199,675,164 |
| `TWEET_PROCESSING_STARTED` | 204,106 | 94,090,776 |
| `TWEET_CLASSIFICATION_SKIPPED` | 204,009 | 108,124,050 |
| `HEARTBEAT_DB_COMMITTED` | 56,902 | 49,644,182 |
| `HEARTBEAT_BACKEND_RECEIVED` | 50,831 | 33,175,364 |
| `TWEETS_INGESTED` | 22,583 | 20,282,284 |
| `SLOW_HTTP_REQUEST` | 16,447 | 8,185,518 |
| `DB_SLOW_OPERATION` | 15,311 | 8,134,547 |
| `BACKEND_HEARTBEAT_TICK` | 6,657 | 3,796,170 |
| `BACKEND_HEARTBEAT_DB_WRITE_STARTED` | 6,657 | 3,366,228 |
| `BACKEND_HEARTBEAT_DB_WRITE_SUCCESS` | 6,507 | 3,336,962 |
| `HEARTBEAT_SEQUENCE_GAP` | 6,265 | 3,489,241 |
| `HTTP_REQUEST_FAILED` | 4,437 | 7,132,967 |
| `DB_OPERATION_FAILED` | 4,130 | 6,585,524 |
| `PUBLIC_MIRROR_SYNC_FAILED` | 2,040 | 1,945,180 |
| `PUBLIC_MIRROR_RETRY_SCHEDULED` | 1,608 | 1,591,335 |
| `PUBLIC_MIRROR_CYCLE_STARTED` | 1,197 | 812,048 |
| `PUBLIC_MIRROR_EXPORT_COMPLETED` | 1,188 | 881,308 |

修复后保留关键 heartbeat、失败、状态变化、Mirror、通知和 trace 边界；成功的单条诊断 DB 写入不再重复写入 Backend JSONL，权威记录仍保存在 `monitor_diagnostic_events`。

## 5. Storage redesign

- Backend、Mirror、Notification structured events 改为按 UTC 日期写入：`<stream>-YYYY-MM-DD.jsonl`。
- 启动时只将旧 `backend.jsonl` 做 O(1) 文件改名，例如 `backend-events-legacy-2026-09-08.jsonl`；不解析、不删除旧文件。
- 新增统一 `tail_jsonl()`，从文件尾按 block 读取，支持 limit、event、component、trace 和 since 过滤。
- 已知 trace 的每个分片读取有 16 MB 上限；没有把 trace 查询变成无限扫描。
- `prune_event_shards()` 通过文件日期删除过期分片，不解析当前大型 Backend 文件。
- 诊断批次改为一次 SQLite commit，而不是每条事件一次 commit。

保留策略：

| 数据 | 保留时间 |
|---|---:|
| Backend structured event shards | 14 天 |
| Heartbeat history | 14 天 |
| Extension diagnostic events | 14 天 |
| Health state history | 30 天 |
| Mirror / Notification logs | 30 天 |

## 6. API / SQLite query changes

以下本地 Observability API 现在统一限制最大 `limit=500`，并限制 `since` 最多回看 14 天；超出窗口返回 HTTP 400：

- `/api/observability/summary`
- `/api/observability/trace/{trace_id}`
- `/api/observability/component/{component}`
- `/api/observability/errors`

另外 `/api/diagnostics` 读取接口也使用有限 limit 和时间窗口。

具体改动：

- summary 只读取最近 20 条相关 Mirror、Notification 和 event-loop 事件；DB transaction 在文件读取前关闭。
- trace 先使用 bounded JSONL reader，再分别以 trace、时间窗口和 limit 查询 `heartbeat_history`。
- `monitor_diagnostic_events` 的 trace 查询必须同时满足 `details_json LIKE`, `created_at >= since`, `ORDER BY id DESC`, `LIMIT`，并在应用层再次确认精确 trace。
- component 查询同时限制 transitions、heartbeats 和 diagnostics 的时间窗口。
- errors 不再读取整套历史文件，只读取各 stream 的 bounded tail。
- Backend root `/health` 使用内存中的 tweet count，不查询 SQLite、不重建 trace、不读取大型 JSONL。
- CLI `scripts/diagnose.py` 已复用同一 tail abstraction，不再自行 `read_text().splitlines()`，trace 的 SQLite 查询也有时间窗和 limit。

新增/确保的索引：

```text
heartbeat_history(component, backend_received_at)
monitor_diagnostic_events(component, observed_at)
monitor_diagnostic_events(component, created_at)
monitor_diagnostic_events(created_at)
health_state_history(component, changed_at)
alerts(created_at)
```

索引既写入 SQLAlchemy model，也通过 `CREATE INDEX IF NOT EXISTS` 在已有 SQLite 上幂等补齐。`details_json` 内嵌的 trace_id 没有伪造独立列；因此 trace 的 details LIKE 仍然是受时间窗和 limit 保护的补充查询。

## 7. SQLite / lock policy

当前 journal mode 实测为：

```text
delete
```

本阶段没有切换 WAL，也没有因为理论上的并发收益直接改变生产数据库模式。

Heartbeat、tweet ingest、单条 diagnostic 和 diagnostic batch 的 SQLite lock 都会记录：

```text
SQLITE_LOCK_DETECTED
```

事件包含 operation、table、error_type、duration_ms 和 `suspected_contention=reader_or_writer_contention`。该字段明确表示推测，不能据此宣称确定是 reader 还是 writer；auth、业务错误等非 lock 错误仍保持原错误事件类型。

## 8. Isolated latency verification

使用临时 SQLite、临时 Observability 目录、关闭 Mirror/WxPusher 的新 H.1 app 进行了 12 次采样。所有响应均为 HTTP 200：

| Endpoint | p50 | p95 | max |
|---|---:|---:|---:|
| `/health` | 2.191 ms | 2.356 ms | 3.096 ms |
| `/api/radar` | 6.529 ms | 7.609 ms | 8.827 ms |
| `/api/observability/summary` | 9.160 ms | 9.776 ms | 16.682 ms |
| `/api/observability/errors?limit=100` | 9.428 ms | 12.605 ms | 13.983 ms |

专项测试还覆盖：

- 10,000 条、跨 64 KB block 的 JSONL tail：只返回请求的最后 N 条。
- monkeypatch `Path.read_text` 直接抛错：tail reader 仍通过。
- 日分片写入、legacy 文件归档、日期 retention。
- trace 诊断查询不会执行 `SELECT * ... ORDER BY id ASC` 全表路径。
- `limit=999999` 被限制在最大值，超过 14 天的 `since` 返回 400。
- 新索引存在，并用 `EXPLAIN QUERY PLAN` 验证 heartbeat 复合索引被使用。
- 诊断批量写入只进行一次 commit。

## 9. Regression results

| 范围 | 结果 |
|---|---:|
| Backend pytest | 57 passed |
| Extension Vitest | 12 passed |
| Extension MV3 build | passed |
| Dashboard Vitest | 8 passed |
| Dashboard TypeScript/Vite build | passed |
| Python compile check | passed |
| `git diff --check` | passed（仅有换行格式提示） |

未修改：Collector、Profile/Replies content script、Radar、DeepSeek、Translation、Alert Manager 规则、Mirror 5 分钟 interval、Dashboard refresh/stale threshold、self-healing。

## 10. 真实运行态验收状态

### 已确认

- 8787 当前只有一个 listener，实际 socket owner 为旧 Uvicorn worker PID 12252。
- 当前 live `/health` 返回 `ready=true`，但 `backend_instance_id=backend-20260903T103939-3f8b74`，说明尚未加载本轮 H.1 新代码。
- 当前系统状态读数：Backend healthy、Profile healthy、Search Backfill healthy、Replies offline；Replies 是既有独立问题，不在 H.1 修复范围。
- `stop-backend.bat` 能准确识别项目 venv Backend；正常 taskkill 因子进程权限返回失败，脚本没有自动升级为强杀。

### 尚未完成

由于旧 Backend 未能在不使用强制终止的情况下退出，本轮没有启动新的 8787 实例，也没有虚构以下指标：

- 生产新实例的 idle RSS、summary/trace RSS delta；
- 生产 30–60 分钟 log growth/hour；
- 新实例下 30–60 分钟 event-loop lag、SQLite lock、heartbeat interval；
- 新实例下 Mirror scheduler 与 Profile/Search 的联合验收。

因此 H.1 的“代码与隔离性能验收”通过，但“生产 30–60 分钟验收”仍是待切换项。

## 11. Restart / production acceptance checklist

用户确认可以结束旧进程后，按下面顺序执行：

```powershell
.\scripts\stop-backend.ps1 -Force
.\start-radar.bat
```

随后确认：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/health | ConvertTo-Json
Get-NetTCPConnection -LocalPort 8787 -State Listen
python .\scripts\diagnose.py summary
```

应看到新的 `backend_instance_id`、`ready=true`、单一 8787 listener 和 `backend-heartbeat` / `health-evaluator` / `event-loop-watchdog` / `observability-retention` 运行中。然后保持 30–60 分钟，持续记录：

- `/health`、`/api/radar`、summary、errors 的 p50/p95/max；
- Backend heartbeat 是否约 60 秒；
- `SQLITE_LOCK_DETECTED`、`BACKEND_HEARTBEAT_DB_WRITE_FAILED`；
- `EVENT_LOOP_LAG_DETECTED > 2s`；
- Mirror 300 秒 scheduler、Profile、Search Backfill；
- 新 daily shard 的 bytes/hour。

## 12. Remaining risks

- 最大旧归档仍占磁盘，这是可恢复保留，不是运行时内存问题；需由后续明确的归档策略处理，不能在本阶段删除。
- trace_id 当前仍嵌在 `details_json`；即使有 created_at 窗口，极大时间窗内的 LIKE 仍可能比结构化列慢。
- SQLite 仍是 `delete` journal mode；本阶段通过短事务、限量查询和索引降低竞争，没有宣称已经证明 WAL 更好。
- Windows 强制终止、断电或进程崩溃仍不能保证写出最后一条 shutdown event。
- 生产新实例尚未加载 H.1；在完成 restart checklist 前，不应宣称 observability 已在 8787 实际生效。

## 13. Final status

```text
H.1 code implementation: COMPLETE
Isolated regression and latency verification: PASS
Production restart: BLOCKED by old child-process permission
Production 30–60 minute acceptance: PENDING
```
