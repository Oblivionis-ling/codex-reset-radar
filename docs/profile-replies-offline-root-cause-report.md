# Codex Reset Radar — Profile / Replies Offline Root Cause Capture

报告时间：2026-09-03  
诊断时间窗：2026-09-03 10:42Z 起  
范围：Profile Monitor、Replies Monitor 在 10:42Z 后停止 heartbeat 的原因定位  
原则：本轮只诊断和留存证据；没有 reload 页面、重启 Extension、修改 Collector、修改 health threshold，也没有实现 self-healing。

## 1. 最终结论

本次 10:42Z 事件已经定位到 **Content Script / 页面执行上下文层**，但现有证据还不能把“上下文为什么终止”细分到 Edge discard、页面冻结、Extension reload 或其他浏览器生命周期事件。

最可靠的结论是：

> Profile 和 Replies 的 Content Script 在启动阶段由 MutationObserver 触发了连续 scan，并在几秒内生成 seq 1–8；最后一批 heartbeat 全部正常经过 Service Worker、localhost HTTP 和 SQLite commit。随后两条页面上下文同时不再产生任何可观测的 timer、fallback、lifecycle、scan 或 heartbeat 事件。掉线发生在 Content Script / 页面执行层，而不是 Backend、localhost HTTP 或 Service Worker forwarding 层。

根因置信度分层：

| 结论 | 置信度 | 说明 |
|---|---:|---|
| 故障边界在 Content Script / 页面执行上下文层 | 高 | 两个 instance 的最后 heartbeat 全链路成功；之后没有任何页面侧事件；Backend、Search Backfill、Tab snapshot 继续运行 |
| seq 1–8 是 MutationObserver → scan 触发的 heartbeat burst | 高 | 8 条 `client_observed_at` 本身相隔几百毫秒至数秒，且全部 `timer_source=scan` |
| 具体终止触发器是 Extension reload、Edge freeze、页面 refresh 或其他生命周期事件 | 不足 | 当前没有直接的 Content Script ping、浏览器冻结事件或 ring buffer 原始导出证据 |

Primary Root Cause：**Content Script / 页面执行上下文停止继续执行或停止产生可观测事件（B 层，兼有 F 层表现）**。由于 fallback scan 和 lifecycle 事件也一起消失，不能把它归因成“只有 heartbeat timer 停止”；B 比“单独 heartbeat timer bug”更符合现有时间线。

## 2. 当前监控链路

Profile 和 Replies 使用同一个 `extension/src/content.ts`，区别只是 `activeSource` 和 Backend component：

```text
X Profile / with_replies 页面
        ↓
content.ts
        ↓
MutationObserver / fallback scan / 60 秒 interval
        ↓
HEARTBEAT_CREATED
        ↓ chrome.runtime.sendMessage()
MV3 Service Worker background.ts
        ↓ POST http://127.0.0.1:8787/api/heartbeat
Backend record_heartbeat()
        ↓
monitor_health + heartbeat_history
        ↓
health evaluator → healthy / warning / offline
```

实现要点：

| 项目 | 当前实现 |
|---|---|
| heartbeat 从哪里发 | `content.ts` 的 `sendHeartbeat()` |
| heartbeat 定时器 | Content Script 内的 60 秒 `window.setInterval`；不是 Service Worker 定时 |
| scan 是否也会发 heartbeat | 是。`scan()` 成功或失败路径都会调用 `sendHeartbeat(..., "scan")` |
| MutationObserver | 初始化时观察 `document.body` 的 `childList + subtree` |
| fallback scan | Content Script 内独立的 60 秒定时器调用 `scheduleScan("fallback")` |
| Service Worker 职责 | 接收消息、读取 Tab 状态、转发 localhost HTTP；不负责 Profile / Replies heartbeat 的定时 |
| 15 / 30 分钟阈值 | 本轮未修改；warning 约 15 分钟，offline 约 30 分钟 |

代码依据：`content.ts` 的 `scheduleScan()` 会在 MutationObserver 回调后安排 scan；`scan()` 完成后发送 `timer_source="scan"` 的 heartbeat；独立的 interval、fallback 和 lifecycle timer 在文件末尾注册。`background.ts` 的 heartbeat handler 负责 Service Worker 接收、HTTP started/success/failed 和响应返回。

## 3. 两个目标 instance 的身份和最后 heartbeat

所有时间均为 UTC。`heartbeat_history` 是按真实 heartbeat 的 `client_observed_at`、`backend_received_at` 和 `db_committed_at` 查询；没有把后续 ring backfill 副本当作新 heartbeat。

| Monitor | Content Script instance | Tab ID | 初始 URL | 最后 client observed | 最后 Backend received | 最后 DB committed | 最后 seq |
|---|---|---:|---|---|---|---|---:|
| Profile | `profile-cs-3cd63764-7cc8-41b2-ac29-a662033671ed` | 973162150 | `https://x.com/thsottiaux/` | 10:42:32.505Z | 10:42:32.777034Z | 10:42:33.232005Z | 8 |
| Replies | `replies-cs-8378c8ad-50ba-4cc7-8f64-fa704be1053c` | 973162737 | `https://x.com/thsottiaux/with_replies` | 10:42:35.975Z | 10:42:36.024406Z | 10:42:36.098039Z | 8 |

最后一条 HTTP 成功诊断事件分别为：

- Profile seq 8：`HEARTBEAT_HTTP_SUCCESS`，10:42:33.685749Z，HTTP 200。
- Replies seq 8：`HEARTBEAT_HTTP_SUCCESS`，10:42:36.129041Z，HTTP 200。

最后一条 Content Script 成功回执分别为：

- Profile seq 8：`CONTENT_SCRIPT_HEARTBEAT_SENT`，10:42:33.281Z（事件写入时间为 10:42:33.686749Z）。
- Replies seq 8：`CONTENT_SCRIPT_HEARTBEAT_SENT`，10:42:36.128Z。

诊断事件是异步上报的，个别 `observed_at` 与写入 `created_at` 不完全相同；判断链路时以同一 `trace_id` 和 `heartbeat_history` 三个时间戳为准。

## 4. 10:42Z 前后时间线

### 4.1 启动和 burst

| 时间 | 事件 | 证据 |
|---|---|---|
| 10:42:26.277Z | `SERVICE_WORKER_INIT` | `extension-sw-615587af-ad84-4c4b-a737-f9e0933e19f1` 初始化 |
| 10:42:28.789Z | Profile `CONTENT_SCRIPT_INIT` | URL 为 `/thsottiaux/`，初始 source=`profile_dom` |
| 10:42:31.559Z | Replies `CONTENT_SCRIPT_INIT` | URL 为 `/thsottiaux/with_replies`，初始 source=`with_replies` |
| 10:42:28.826Z 起 | Profile MutationObserver 触发 | 页面初始 DOM 构建产生多次 mutation |
| 10:42:31.587Z 起 | Replies MutationObserver 触发 | 页面初始 DOM 构建产生多次 mutation |
| 10:42:32.505Z | Profile seq 8 client observed | 之后不再出现该 instance 的新 heartbeat |
| 10:42:35.975Z | Replies seq 8 client observed | 之后不再出现该 instance 的新 heartbeat |
| 10:42:36.934Z | 新的 `SERVICE_WORKER_INIT` | 新 ID 为 `extension-sw-06756416-7215-4bc9-91d0-a6360fad2b27` |

### 4.2 掉线后的健康状态

| 时间 | 结果 |
|---|---|
| 10:43Z 起 | 两个目标 Content Script instance 都没有新的 diagnostic event 或 heartbeat |
| 10:43:37Z 起 | Service Worker 仍持续执行 alarm 并写入 Tab snapshot；Search Backfill 仍继续 |
| 10:57:40Z | Profile 从 healthy 进入 warning |
| 10:57 左右 | Replies 也进入 warning，健康年龄开始超过 15 分钟 |
| 11:12:41Z | Profile 由 warning 进入 offline |
| 11:12 左右 | Replies 由 warning 进入 offline |

10:43–11:15Z 的目标 instance 查询没有出现：

```text
CONTENT_SCRIPT_HEARTBEAT_TIMER_TICK
FALLBACK_TIMER_TICK
CONTENT_SCRIPT_LIFECYCLE_TICK
FALLBACK_SCAN_STARTED
FALLBACK_SCAN_COMPLETED
FALLBACK_SCAN_FAILED
HEARTBEAT_CREATED
HEARTBEAT_HTTP_FAILED
CONTENT_SCRIPT_HEARTBEAT_FAILED
```

因此不能证明只是一个 heartbeat POST 失败；页面侧的多个独立活动源都停止了可观测输出。

## 5. seq 1–8 burst 的真实原因

### 5.1 Client 时间戳证明不是 delayed backfill

Profile 的 8 条真实 heartbeat：

```text
seq 1  10:42:28.970Z
seq 2  10:42:29.314Z
seq 3  10:42:30.099Z
seq 4  10:42:30.395Z
seq 5  10:42:31.400Z
seq 6  10:42:31.687Z
seq 7  10:42:32.065Z
seq 8  10:42:32.505Z
```

总跨度约 3.535 秒。

Replies 的 8 条真实 heartbeat：

```text
seq 1  10:42:31.775Z
seq 2  10:42:32.115Z
seq 3  10:42:32.518Z
seq 4  10:42:32.737Z
seq 5  10:42:33.046Z
seq 6  10:42:33.497Z
seq 7  10:42:33.716Z
seq 8  10:42:35.975Z
```

总跨度约 4.200 秒。

每一条真实 heartbeat 的 `timer_source` 都是 `scan`，不是 `interval`。`client_observed_at` 本身已经集中在数秒内，所以不是“客户端每 60 秒生成、Backend 后来一次性接收”的 delayed backfill，也不是 Backend 把不同事件错误写成 heartbeat。

### 5.2 代码路径

当前路径是：

```text
初始 X DOM 构建
  → MutationObserver callback
  → scheduleScan("mutation")
  → 150ms 后 scan()
  → scan() 完成后 sendHeartbeat(..., "scan")
  → 新 mutation 再触发下一次 scan
```

`scanRunning` 只防止 scan 并发，不会阻止前一个 scan 完成后由新的 DOM mutation 排队下一次 scan。因此，初始化 DOM 的连续重建会造成多个顺序 scan，每个 scan 都发送 heartbeat。

结论：

```text
seq 1–8 burst = MutationObserver → repeated scan → scan heartbeat
```

不是：

- A. 旧 ring buffer backfill 造成的真实生成 burst；
- B. 已证实的多个 heartbeat timer 重复启动；
- C. retry loop 重复发送；
- D. Backend 把其他事件写成 heartbeat。

## 6. Client → Service Worker → HTTP → Backend 证据

Profile 和 Replies 的 seq 1–8 都能在目标 trace 中看到以下阶段：

```text
HEARTBEAT_CREATED
  → HEARTBEAT_SW_RECEIVED
  → HEARTBEAT_HTTP_STARTED
  → HEARTBEAT_HTTP_SUCCESS
  → heartbeat_history / DB committed
```

目标 instance 没有发现：

```text
HEARTBEAT_HTTP_FAILED
CONTENT_SCRIPT_HEARTBEAT_FAILED
SERVICE_WORKER_MESSAGE_FAILED（目标 heartbeat）
```

Backend 在相同窗口持续有 Backend heartbeat，Search Backfill 也持续健康；没有 event loop lag、DB error 或 localhost 接收异常与这两路停机对齐的证据。

因此，G（localhost Backend 接收问题）不是本次主因。

## 7. Service Worker 检查

### 7.1 instance_id 变化的含义

10:42:26Z 的 worker 为：

```text
extension-sw-615587af-ad84-4c4b-a737-f9e0933e19f1
```

它处理了最后一批 Profile / Replies heartbeat。10:42:36Z 之后，诊断中出现新的 `extension-sw-*` ID，并大约每分钟出现一次 `SERVICE_WORKER_INIT`。

这是当前代码生成 `EXTENSION_INSTANCE_ID` 的方式和 MV3 生命周期共同造成的：ID 在 Service Worker 模块重新初始化时重新生成；alarm 唤醒可以启动新的 worker execution context。它说明 Service Worker 发生了多次启动/唤醒，但不能单独证明这些都是故障重启。

关键事实是：新 worker 继续执行了：

- 每分钟 retry alarm；
- Search Backfill 相关工作；
- 对 Tab 973162150 和 973162737 的状态快照。

如果 Service Worker 是掉线主因，后续应该能看到 Content Script 仍有 timer/scan 事件但 runtime message 或 HTTP 转发失败；实际情况是目标 Content Script 侧的事件先整体消失。因此 C 不支持作为 primary root cause。

### 7.2 Service Worker 错误的范围

10:42 前后存在少量 `SERVICE_WORKER_MESSAGE_FAILED`，但对应的是 Search 临时 Tab 的 `tabs.get`：

```text
No tab with id: <search-tab-id>
```

不是两个目标 Tab，也不是 Profile / Replies heartbeat 的 forwarding failure。当前诊断事件类型中没有单独的 `SERVICE_WORKER_MESSAGE_SUCCESS`；成功链路用 `SERVICE_WORKER_MESSAGE_SENT`、`HEARTBEAT_HTTP_SUCCESS` 和 heartbeat DB commit 表示。这是可观测性命名上的剩余缺口，不是本次失败证据。

## 8. Tab 状态检查

Service Worker 从 10:43:37Z 到 11:13:37Z 至少每分钟记录一次两个目标 Tab 的状态，共约 31 次快照。

| Tab | 最后观察到的状态 |
|---:|---|
| 973162150 | URL=`https://x.com/thsottiaux/`；`status=complete`；`discarded=false`；`frozen=false`；`active=false`；`windowId=973160908` |
| 973162737 | URL=`https://x.com/thsottiaux/with_replies`；`status=complete`；`discarded=false`；`frozen=false`；`active=false`；`windowId=973160908` |

`active=false` 只表示当前不是前台 Tab；两页在后台运行本身不是异常。`autoDiscardable=true` 表示浏览器允许自动 discard，但实际快照没有 `discarded=true`。

因此：

- A（Tab discarded）没有证据支持；
- A（Tab frozen）没有证据支持；
- Tab 本身仍存在，且 URL 没有跳到 `/status/<tweet_id>`。

本轮浏览器控制接口无法稳定接管当前页面对象，所以没有完成直接的 `PING_CONTENT_SCRIPT`。因此“Tab 存在”已由快照证实，但“当前 Content Script 能否 ping”没有直接证据。

## 9. Visibility、SPA route 与 DOM

### 9.1 Visibility

两页在启动阶段都出现了 `visible` / `hidden` 变化；其中一些 heartbeat 在 `document.visibilityState=hidden` 时仍然成功。没有证据表明 `hidden` 本身立即导致了这次停止。

### 9.2 本次 10:42 instance 没有 `/status` 路由证据

两个目标 instance 的初始化 URL 和最后 heartbeat metadata 都分别是：

```text
/thsottiaux/
/thsottiaux/with_replies
```

没有对应 instance 的 `LOCATION_CHANGED`，也没有 `HEARTBEAT_SKIPPED_NO_ACTIVE_SOURCE`。所以这次 10:42 事件不能归因成 `/status/<tweet_id>` SPA route guard。

此前已经稳定复现的 `/thsottiaux/status/<tweet_id>` route classification 问题是一个独立的历史问题：旧路径识别会把 `activeSource` 清空，进而跳过 heartbeat。当前源码已经保留 status route 的前一个 monitor context，并有对应 parser test；这不改变本次两个 instance 的证据结论，也不应把历史 route 根因错误推广到本次事件。

### 9.3 Observer

两个页面在初始化时都成功出现：

```text
MUTATION_OBSERVER_ATTACHED
observer_attached=true
observer_root_connected=true
```

停止前没有 `MUTATION_OBSERVER_DISCONNECTED` 或 `DOM_ROOT_CHANGED`。这排除了“已经明确记录的 Observer disconnect”作为主因，但不能证明页面执行上下文在浏览器内部一直存活。

## 10. Ring buffer 证据和数据质量

数据库中存在同一批事件的延迟写入副本：

| Instance | 10:42 实时事件 | 后续 ring backfill 副本 | backfill 写入窗口 |
|---|---:|---:|---|
| Profile | 8 条真实 heartbeat | 9 条诊断副本 | 约 10:48–10:51Z |
| Replies | 8 条真实 heartbeat | 8 条诊断副本 | 约 10:49–10:51Z |

这些记录的 `observed_at` 仍然指向 10:42，但数据库 `created_at` 在后面，说明 ring buffer backfill 会造成诊断事件重复；它不是 seq 1–8 burst 的原因。分析时必须优先使用：

1. heartbeat 的 `client_observed_at`；
2. Service Worker/HTTP 的 `observed_at`；
3. Backend `backend_received_at`；
4. SQLite `db_committed_at`；
5. 最后才参考诊断记录的 `created_at`。

按本任务要求，没有在 ring buffer 导出前 reload Extension。由于当前浏览器页面控制接口超时，本轮没有获得 `chrome.storage.local` 的原始 ring buffer 内容，也没有直接验证其中是否保存了 context termination error、未上传事件或 runtime.lastError。这是本报告的 Remaining Blind Spot。

## 11. A–H 判定

| 假设 | 本次判定 | 证据 |
|---|---|---|
| A. Edge Tab discard / freeze | 不支持为主因 | 31 次快照均显示目标 Tab 存在、`complete`、`discarded=false`、`frozen=false` |
| B. Content Script 失活 | **故障边界定位到此层，具体失活动作未直接捕获** | 两个页面同时停止所有 Content Script 事件；Backend/SW/Tab 快照继续 |
| C. MV3 Service Worker 生命周期 | 不支持为主因 | worker ID 虽变化，但 alarm、Search Backfill、Tab snapshot 继续；最后 heartbeat forwarding 成功 |
| D. X SPA / DOM route | 本次 instance 不支持；历史 route 问题独立存在 | 没有 `LOCATION_CHANGED`，URL 保持监控路径；历史 `/status` route guard 已单独复现 |
| E. X 页面本身异常 | 无直接证据 | 没有 page error、scan failed、Observer disconnect 或 DOM root changed |
| F. 只有 heartbeat timer 停止、采集仍存活 | 不支持为单独主因 | heartbeat timer、fallback timer、lifecycle、scan 事件都同时消失；只能说表现包含 F |
| G. localhost Backend 接收问题 | 排除为主因 | seq 1–8 HTTP 200 且 DB commit 完成；Backend 和 Search Backfill 持续 |
| H. 其他明确原因 | 尚未发现 | 需要当前页面 ping、原始 ring buffer 或浏览器生命周期日志才能继续细分 |

## 12. Primary Root Cause 与 Remaining Blind Spot

### Primary Root Cause

```text
Content Script / 页面执行上下文在启动 scan burst 后停止继续执行或停止产出诊断事件。
```

更具体地说：

1. startup MutationObserver 造成了重复 scan heartbeat；
2. seq 1–8 均正常发出并完成 Backend commit；
3. 10:42:36Z 后没有新的 Content Script 事件；
4. Service Worker 仍然工作，目标 Tab 仍然存在且未 discard/freeze；
5. 所以停止点在 Content Script / 页面执行层。

Confidence：

- **故障层级：高**；
- **具体终止机制：中低**；
- **MutationObserver burst：高**。

### Remaining Blind Spot

当前仍无法凭这批持久化记录回答以下问题：

- Content Script 是否还能被 `PING_CONTENT_SCRIPT` 唤醒并回应；
- `chrome.storage.local` ring buffer 中是否有未上传的 termination/runtime error；
- 页面是否在浏览器内部被 freeze，但 `tabs.Tab.frozen` 没有反映出来；
- 是否发生了用户不可见的 Extension reload 或 Content Script replacement；
- heartbeat interval 是否注册后从未第一次 tick，还是 tick 后页面执行上下文才终止。

因此报告不把 Extension reload、Edge freeze 或 X 页面异常写成已确认根因。

## 13. Recommended Fix（本轮未实施）

如果下一阶段授权修复，建议按最小范围处理：

1. **heartbeat 与 scan 解耦**：scan 只负责采集和上报 Tweet；Profile / Replies heartbeat 由唯一的 60 秒 interval 发送，避免 MutationObserver 产生 heartbeat flood。
2. **增加 timer registration 证据**：记录 timer 是否注册、第一次 tick、每次 tick 的 `expected_elapsed_ms` / `actual_elapsed_ms`，这样可以明确区分“未注册、停止、被 throttled、运行但消息失败”。
3. **补齐只读 ping**：由诊断命令对指定 Tab 做 `tabs.sendMessage({type:"PING_CONTENT_SCRIPT"})`，记录 ping success/failure、当前 instance、activeSource、observer 和 timer 状态；不要在诊断命令中自动 reload。
4. **补齐生命周期事件**：记录 `pagehide`、`pageshow`、`freeze`（浏览器实际提供时）、`resume` 和 Extension context invalidation；不把缺失的 API 字段伪造成 false。
5. **保留 route context 回归测试**：`/status/<tweet_id>` 的历史 classification 问题应保持独立测试，不能用它解释没有 `LOCATION_CHANGED` 的本次事件。
6. **保留三段时间戳**：继续同时保留 `client_observed_at`、`backend_received_at`、`db_committed_at`，并在 CLI 中显式标注诊断事件的 `observed_at` 与数据库 `created_at`，避免 backfill 副本被当成实时事件。

本轮没有实施上述任何修复，也没有加入自动 reload、自动重开 Tab 或 self-healing。

## 14. 诊断工具和验证

已使用只读命令核对两个 instance：

```powershell
backend\.venv\Scripts\python.exe scripts\diagnose.py component profile --instance-id profile-cs-3cd63764-7cc8-41b2-ac29-a662033671ed --limit 100
backend\.venv\Scripts\python.exe scripts\diagnose.py component replies --instance-id replies-cs-8378c8ad-50ba-4cc7-8f64-fa704be1053c --limit 100
```

CLI 当前合并展示：

- Extension diagnostic event；
- Backend JSONL event；
- SQLite heartbeat commit；
- `client_observed_at`、`backend_received_at`、`db_committed_at`；
- `component`、`instance_id`、`trace_id`、`sequence`。

本轮确认：

- 两个目标 instance 各 8 条真实 heartbeat；
- 两个目标 instance 的 seq 1–8 全部形成完整成功链路；
- 后续至少 31 次目标 Tab snapshot 持续存在；
- 没有目标 heartbeat HTTP failure；
- Backend warning/offline 时间与 heartbeat gap 对齐；
- 没有修改 SQLite 数据和健康阈值。

阶段状态：**诊断完成；故障边界已定位到 Content Script / 页面执行上下文层；具体生命周期触发器因当前页面 ping 和原始 ring buffer 不可取得而保持未决。**
