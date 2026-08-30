# Codex Reset Radar — Profile / Replies 掉线诊断报告

报告时间：2026-08-30 12:08（Asia/Shanghai）  
诊断范围：Profile Monitor、Replies Monitor 的掉线原因  
本阶段原则：只增加 instrumentation、观察能力和证据记录；不自动 reload Tab、不自动重开 Tab、不做 self-healing，不修改 15/30 分钟 health threshold，不改通知链路、Collector 架构、DeepSeek、Radar 或 Dashboard。

## 1. 当前结论

本报告完成了诊断 instrumentation 和 Backend 接收能力。第一轮观察中，新版本 Extension 曾在两个 X 页面上连续运行约 30 分钟；第二次 reload 后，两个页面都只在启动阶段发送了 heartbeat，随后约 3 分钟没有新 heartbeat。当前仍未超过 Backend 的 15/30 分钟阈值，因此页面显示 healthy 不能代表心跳仍在持续。

当前证据分级如下：

| 组件 / 假设 | 当前判断 | 证据 |
|---|---|---|
| Profile 的 SPA 导航到 Tweet 详情页（D） | **强支持（历史掉线）** | 生产库中 Profile 最后一次旧版 heartbeat 的 URL 是 https://x.com/thsottiaux/status/2093573991965557198，不是受监控的精确 Profile URL；现有 sourceForLocation() 对该路径返回 null。 |
| Profile heartbeat 被 guard 停止（F） | **强支持（代码路径）** | 现有 sendHeartbeat() 在 activeSource 为空时直接 return；路由切换到上述 status URL 后，两个页面 timer 即使仍在运行，也不会产生 Profile heartbeat。 |
| Replies 的 X 页面异常（E） | **可能，但未证实** | Replies 最后 URL 仍是 /thsottiaux/with_replies，旧 metadata 没有 last_error；此前有过 X reload error 现象，但没有与本次掉线时间线绑定。 |
| Tab discard / freeze（A） | **未证实** | 旧版没有 tab.discarded 或 tab 状态记录。 |
| Content Script 失活（B） | **新现象中强怀疑，机制待区分** | 第二次 reload 的 INIT 后，两个页面均没有后续 heartbeat；需要 timer/lifecycle tick 区分 content script 整体停止与单独 timer 停止。 |
| MV3 Service Worker 生命周期（C） | **未证实，暂不支持其为主因** | Content Script 通过 chrome.runtime.sendMessage 触发 Worker 的 onMessage；新版本会记录 Worker 转发成功/失败，旧版没有此证据。 |
| Backend 接收问题（G） | **当前不支持** | Backend 当前 healthy，Search Backfill heartbeat 持续更新；但旧版没有逐次 HTTP 转发成功/失败回执，所以不能排除短暂失败。 |
| 其他（H） | **仍待确认** | 第二次 reload 后两个页面近乎同时停止 heartbeat，可能存在共同页面执行/freeze 条件，但当前还没有 tab_frozen 或 timer tick 证据。 |

因此目前最可靠的阶段性结论是：

> Profile 的历史掉线已有强代码证据指向“SPA 离开受监控 Profile 路由后，activeSource=null，heartbeat 被跳过”。本次第二次 reload 又复现了“启动 heartbeat 后约 1–2 分钟停止”的现象，Backend 和 Tab discard 已排除为当前主因，但需要下一轮 tick 记录区分 B、C、F 或浏览器 freeze。

## 2. 当前监控链路

### Profile

~~~text
https://x.com/thsottiaux
        ↓
content.ts（run_at=document_idle）
        ↓
60 秒 setInterval heartbeat + scan 内 heartbeat
        ↓
chrome.runtime.sendMessage({ type: "HEARTBEAT", component: "profile_monitor" })
        ↓
background.ts 的 MV3 Service Worker onMessage
        ↓
POST http://127.0.0.1:8787/api/heartbeat
        ↓
record_heartbeat() → monitor_health.profile_monitor
        ↓
/api/health → derived_monitor_state()
~~~

### Replies

~~~text
https://x.com/thsottiaux/with_replies
        ↓
同一个 content.ts（activeSource = with_replies）
        ↓
60 秒 setInterval heartbeat + scan 内 heartbeat
        ↓
chrome.runtime.sendMessage({ type: "HEARTBEAT", component: "replies_monitor" })
        ↓
同一个 MV3 Service Worker
        ↓
POST http://127.0.0.1:8787/api/heartbeat
        ↓
record_heartbeat() → monitor_health.replies_monitor
        ↓
/api/health → derived_monitor_state()
~~~

关键实现梳理：

| 项目 | Profile | Replies |
|---|---|---|
| heartbeat 从哪里发 | extension/src/content.ts 的 sendHeartbeat() | 同上 |
| 谁定时 | 页面 content script 的 window.setInterval(..., 60_000)；不是 chrome.alarms | 同上 |
| content script 是否有独立 timer | 有：fallback scan timer 和 heartbeat timer 分开 | 有 |
| Service Worker 是否参与 | 参与转发和 localhost HTTP；不负责 Profile heartbeat 的定时 | 同上 |
| MutationObserver 绑定 | 初始化时绑定 document.body，childList + subtree | 同上 |
| fallback scan 谁触发 | content script 每 60 秒的 fallback timer | 同上 |
| Tab reload 后谁重新初始化 | 浏览器重新注入 content script，模块级状态、Observer、timer 重新建立 | 同上 |
| SPA navigation 后是否重新初始化 | 旧版每 2 秒检查 pathname，只有 source 改变时重新 scan；不会重建 content script/Observer | 同上 |
| Backend health | last_heartbeat 年龄 >15 min 为 warning，>30 min 为 offline；阈值本阶段未改 | 同上 |

### 已发现的 Profile 路由缺口

旧版 sourceForLocation() 只识别：

~~~text
/thsottiaux
/thsottiaux/with_replies
/search
~~~

但 Manifest 对 https://x.com/thsottiaux/* 会注入 content script。用户从 Profile 点击 Tweet 后，X SPA 可能进入：

~~~text
/thsottiaux/status/<id>
~~~

此时旧版路由检查会执行：

~~~text
activeSource = null
~~~

同时旧版 heartbeat 的第一行是：

~~~text
if (!activeSource) return;
~~~

所以该页面上的 timer 不一定停止，但 Profile Monitor 不再收到 heartbeat。这解释了为什么旧版最后 metadata 会保留一个 status URL，并且最终显示 offline。该发现只作为诊断证据记录，本阶段没有把它改成自动恢复逻辑。

## 3. 已加入的诊断 instrumentation

### Content Script

新版本会在浏览器控制台记录并（低频事件）写入 Backend 诊断时间线：

~~~text
CONTENT_SCRIPT_INIT
CONTENT_SCRIPT_HEARTBEAT_SENT
CONTENT_SCRIPT_HEARTBEAT_FAILED
CONTENT_SCRIPT_HEARTBEAT_TIMER_TICK
CONTENT_SCRIPT_LIFECYCLE_TICK
FALLBACK_TIMER_TICK
FALLBACK_SCAN_STARTED
FALLBACK_SCAN_COMPLETED
FALLBACK_SCAN_FAILED
MUTATION_OBSERVER_ATTACHED
MUTATION_OBSERVER_TRIGGERED
MUTATION_OBSERVER_DISCONNECTED
DOM_ROOT_CHANGED
LOCATION_CHANGED
PAGE_VISIBILITY_CHANGED
DOCUMENT_READY_STATE_CHANGED
SERVICE_WORKER_MESSAGE_SENT
SERVICE_WORKER_MESSAGE_FAILED
~~~

Mutation 事件在页面控制台逐次记录，写入 Backend 的事件做 30 秒节流，避免 X 的高频 DOM 变化污染数据库。

每次 heartbeat 附带：

~~~json
{
  "monitor": "profile",
  "timestamp": "客户端时间",
  "url": "当前 URL",
  "document_visibility": "visible 或 hidden",
  "document_ready_state": "当前 readyState",
  "has_target_dom": true,
  "observer_attached": true,
  "observer_root_is_document_body": true,
  "observer_root_connected": true,
  "last_scan_at": "最近 scan 时间",
  "last_scan_success": true,
  "expected_heartbeat_interval_ms": 60000,
  "actual_heartbeat_elapsed_ms": 60000,
  "heartbeat_timer_source": "interval 或 scan",
  "scan_running": false,
  "mutation_count": 0
}
~~~

Replies 将 monitor 设置为 replies。

### Service Worker

heartbeat 转发现在等待实际 HTTP 结果：

- Backend HTTP 成功：向 content script 返回 { ok: true }；
- Backend HTTP 失败或非 2xx：返回 { ok: false, error: ... }，content script 记录 CONTENT_SCRIPT_HEARTBEAT_FAILED；
- 不记录 Token、UID 或其他通知 Secret。

每分钟的现有 retry alarm 还会执行只读 tabs.query()，并记录真实可读取字段：

~~~text
tab_id
tab_url
tab_active
tab_status
tab_discarded
tab_frozen（仅当浏览器 API 实际提供）
tab_auto_discardable
tab_pinned
tab_window_id
~~~

如果浏览器 API 没有提供某字段，代码会省略该字段，不伪造值。

### Backend

新增：

~~~text
POST /api/diagnostics
GET  /api/diagnostics?component=profile_monitor&limit=100
GET  /api/health
~~~

诊断事件保存到 monitor_diagnostic_events，heartbeat 最新 metadata 保存于原有 monitor_health.metadata_json。/api/health 现在只读返回该 metadata；health 派生阈值和通知逻辑没有修改。

## 4. 新版本观察窗口

Backend 已重启并加载新增诊断表/接口。2026-08-30 12:12:54 至 12:43:42（Asia/Shanghai）的诊断事件显示：

| 组件 | 当前状态 | 观测 |
|---|---|---|
| Backend | healthy | /health 返回 ok，8787 正在监听 |
| Search Backfill | healthy | 最近 heartbeat 持续更新 |
| Profile Monitor | 首轮 healthy；第二次 reload 后 heartbeat 停止 | 首轮 70 次 heartbeat、28 次 fallback scan、30 次 Tab 快照；第二次 reload 的最后 heartbeat 为 12:47:30，之后约 3 分钟无新 heartbeat |
| Replies Monitor | 首轮 healthy；第二次 reload 后 heartbeat 停止 | 首轮 66 次 heartbeat、28 次 fallback scan、30 次 Tab 快照；第二次 reload 的最后 heartbeat 为 12:47:33，之后约 3 分钟无新 heartbeat |
| Heartbeat 间隔 | 正常 | 当前 metadata 的 interval source 实际间隔约 59.9 秒；期望 60 秒 |
| Tab discard | 未发生 | Profile/Replies 的 30 次快照均为 `tab_discarded=false`、`tab_status=complete` |
| 页面 / Observer | 正常 | heartbeat 中 `has_target_dom=true`、Observer attached、root connected |
| 失败事件 | 0 条 | 未出现 heartbeat、Service Worker、fallback scan 失败；但 timer/lifecycle tick 尚未加入本轮数据 |
| visibility | 关联但未导致掉线 | 两页多次为 `hidden`，仍持续 heartbeat；hidden 不是本次观察窗口的故障原因 |

旧版最后 metadata：

~~~text
Profile: https://x.com/thsottiaux/status/2093573991965557198, source=profile_dom
Replies: https://x.com/thsottiaux/with_replies, source=with_replies
~~~

此前旧 metadata 能支持 Profile 路由缺口，但不能提供 discarded、visibility、timer 间隔或 Worker HTTP 失败证据。第一轮新观察补齐了这些证据；第二次 reload 则产生了新的“content script heartbeat 停止”时间线，但因为当时尚未记录独立 timer tick，仍不能把 B 与 F 完全分开。

## 5. A–H 判定方法

| 假设 | 需要看到的证据 |
|---|---|
| A Tab discard/freeze | 掉线前后 TAB_STATE_SNAPSHOT 或 heartbeat metadata 中 tab_discarded=true，并与 heartbeat gap 对齐 |
| B Content Script 失活 | 有 CONTENT_SCRIPT_INIT 后事件停止，且 Worker 仍能做 Tab snapshot；或页面重新注入后再次出现 INIT |
| C MV3 Worker 生命周期 | content script 仍有 timer/scan/lifecycle 事件，但 SERVICE_WORKER_MESSAGE_FAILED 或 Worker HTTP 转发失败；重启/唤醒 Worker 后恢复 |
| D X SPA/DOM 重建 | LOCATION_CHANGED 进入未支持 URL，或 DOM_ROOT_CHANGED / Observer disconnected 后 heartbeat/scan 消失 |
| E X 页面异常 | heartbeat metadata 的 URL/readyState/DOM 与 FALLBACK_SCAN_FAILED 或页面 error 文本对应 |
| F heartbeat timer 停止而采集仍活着 | FALLBACK_SCAN_COMPLETED 继续出现，但 CONTENT_SCRIPT_HEARTBEAT_SENT 的 interval 事件停止或 actual_heartbeat_elapsed_ms 明显放大 |
| G Backend 接收问题 | content script/Worker 明确发送成功，但 Backend 没有对应 heartbeat；或 Worker 返回 localhost HTTP 错误 |
| H 其他 | 需要新的事件序列与可重复步骤，不以单个 stale health 记录归因 |

## 6. 目前仍需的实测步骤

当前未自动操作 Edge。请在 Edge 手动完成：

1. 在 edge://extensions 对加载的 extension/dist 点击 Reload。
2. 刷新 https://x.com/thsottiaux 和 https://x.com/thsottiaux/with_replies 两个页面。
3. 两个页面保持打开至少 3–5 分钟。
4. 观察以下接口：

~~~text
http://127.0.0.1:8787/api/health
http://127.0.0.1:8787/api/diagnostics?component=profile_monitor&limit=200
http://127.0.0.1:8787/api/diagnostics?component=replies_monitor&limit=200
~~~

5. 在扩展 Service Worker 的 Inspect views 中保留控制台日志，重点查看 SERVICE_WORKER_MESSAGE_FAILED、TAB_STATE_SNAPSHOT、LOCATION_CHANGED、DOM_ROOT_CHANGED、CONTENT_SCRIPT_HEARTBEAT_FAILED。
6. 如果要复现 Profile 路由问题，可手动从 Profile 点开一条 Tweet，记录进入 /status/<id> 的时间，再查看 Profile 诊断时间线；本阶段不会自动点击、reload 或修复。

完成上述观察后，才能对 Replies 和 A/B/C/E/F/G 做最终排除，并形成掉线前后的时间线结论。

## 7. 验证结果

~~~text
Backend pytest: 24 passed
Extension Vitest: 5 passed
TypeScript: passed
MV3 build: passed
~~~

新版本产物位于：

~~~text
D:\work\20260828-CodexResetRadar\extension\dist
~~~
