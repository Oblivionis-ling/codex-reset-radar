# Codex Reset Radar — Profile / Replies 掉线诊断阶段报告

报告时间：2026-08-30 22:05（Asia/Shanghai）  
诊断范围：Profile Monitor、Replies Monitor 周期性掉线问题  
当前基线：[profile-replies-diagnostic.md](profile-replies-diagnostic.md)

## 1. 阶段结论

本阶段已完成浏览器侧、MV3 Service Worker 侧和 Backend 侧的诊断 instrumentation，并完成一轮 reload / 刷新后的持续运行观测。

当前运行窗口没有发生掉线：

| 组件 | 当前状态 | 最新 heartbeat | 关键证据 |
|---|---|---:|---|
| Backend | healthy | 16:59:26 | `http://127.0.0.1:8787/health` 返回 `status=ok` |
| Profile Monitor | healthy | 16:59:42 | 心跳约 59.956 秒；DOM、Observer、scan 均正常 |
| Replies Monitor | healthy | 16:59:42 | 心跳约 59.952 秒；DOM、Observer、scan 均正常 |
| Search Backfill | healthy | 16:59:27 | 正常持续上报 |

本轮检查时间为 17:00 左右。数据库记录的本次 Content Script 初始化时间为：Profile 16:44:01、Replies 16:44:04；从初始化到检查时，两页仍在持续上报。因此，当前证据支持“刷新后运行稳定”，但不代表已经完成多小时级别的长期稳定性验收。

## 2. 当前监控链路

```text
Profile / Replies X 页面
        ↓
content.ts
        ↓
60 秒 heartbeat timer + 60 秒 fallback scan timer
        ↓
chrome.runtime.sendMessage()
        ↓
background.ts 的 MV3 Service Worker
        ↓
POST http://127.0.0.1:8787/api/heartbeat
        ↓
Backend record_heartbeat()
        ↓
monitor_health
        ↓
/api/health 派生 healthy / warning / offline
```

Service Worker 参与 heartbeat 转发和 Tab 状态查询，但不负责 Profile / Replies heartbeat 的定时；定时器实际运行在页面 content script 中。

## 3. 已完成的诊断能力

### Content Script

已记录以下事件：

```text
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
```

heartbeat metadata 至少包含：当前 URL、`document.visibilityState`、`readyState`、目标 DOM 是否存在、Observer 状态、最近一次 scan 时间和结果、期望/实际 heartbeat 间隔，以及 Tab 状态。

### Service Worker

已增加只读 Tab 快照，记录真实可读取的：

```text
tab_id
url
active
status
discarded
frozen（浏览器提供时）
autoDiscardable
pinned
windowId
```

HTTP 转发成功和失败也分别记录，避免把“消息已发出”误认为“Backend 已收到”。

### Backend

已增加：

```text
POST /api/diagnostics
GET  /api/diagnostics
GET  /api/health
```

诊断事件持久化到 `monitor_diagnostic_events`；最新 heartbeat metadata 持久化到 `monitor_health.metadata_json`。现有 15 分钟 warning、30 分钟 offline 阈值未修改。

## 4. 本轮运行观测

### Profile Monitor

- URL：`https://x.com/thsottiaux/`
- 最新 heartbeat：16:59:42
- 实际 heartbeat 间隔：约 59.956 秒
- `document_visibility=hidden`，但 timer 仍持续运行
- `document_ready_state=complete`
- `has_target_dom=true`
- `observer_attached=true`
- Observer root 为已连接的 `BODY`
- 最近 fallback scan：成功
- `tab_status=complete`
- `tab_discarded=false`
- `tab_frozen=false`
- 最新 Tab 快照：16:59:59

### Replies Monitor

- URL：`https://x.com/thsottiaux/with_replies`
- 最新 heartbeat：16:59:42
- 实际 heartbeat 间隔：约 59.952 秒
- `document_visibility=hidden`，但 timer 仍持续运行
- `document_ready_state=complete`
- `has_target_dom=true`
- `observer_attached=true`
- Observer root 为已连接的 `BODY`
- 最近 fallback scan：成功
- `tab_status=complete`
- `tab_discarded=false`
- `tab_frozen=false`
- 最新 Tab 快照：16:59:59

本轮针对 Profile / Replies 查询到的诊断记录中，没有 `FAILED` 或 `DISCONNECTED` 事件。由此可见，`hidden` 本身没有导致本轮 heartbeat 停止。

## 5. A–H 根因判定

| 假设 | 当前判定 | 依据 |
|---|---|---|
| A. Edge Tab discard / freeze | 当前运行窗口排除 | Tab 快照和 heartbeat 均为 `discarded=false`、`frozen=false` |
| B. Content Script 失活 | 当前运行窗口不支持 | INIT 后仍持续出现 timer、scan、lifecycle 和 heartbeat 事件 |
| C. MV3 Service Worker 生命周期 | 当前运行窗口不支持 | heartbeat 转发持续成功，没有 Service Worker message failure |
| D. X SPA 导航 / DOM 重建 | **Profile 历史掉线强支持**；本轮未复现 | 旧版 Profile 最后 URL 为 `/thsottiaux/status/<id>`，不在旧版 source 路由识别范围内；本轮 URL 保持在 Profile 监控路径，未出现对应异常 |
| E. X 页面异常 | 当前运行窗口未发现 | `readyState=complete`、目标 DOM 存在、scan 成功、没有页面侧失败事件 |
| F. heartbeat timer 停止但采集逻辑存活 | 当前运行窗口排除 | heartbeat timer、fallback scan 和 lifecycle tick 均持续；实际间隔约 60 秒 |
| G. localhost Backend 接收问题 | 当前运行窗口排除 | Backend 正常监听 8787，monitor health 的最新时间与浏览器上报一致 |
| H. 其他 | 未发现新的可复现证据 | 当前事件时间线没有新的异常断点 |

### 历史 Profile 根因

旧版代码只识别以下路径：

```text
/thsottiaux
/thsottiaux/with_replies
/search
```

而 X 的 SPA 导航可能把 Profile 页面带到：

```text
/thsottiaux/status/<tweet_id>
```

此时旧版会将 `activeSource` 设为 `null`，随后 heartbeat 的 guard 直接返回。因此，Profile 的历史掉线已有强证据支持：

```text
D（SPA 导航到未识别路径）
+
F（heartbeat 被路由 guard 跳过）
```

这是历史问题的诊断结论；本阶段没有引入自动 reload、自动重开 Tab 或 self-healing。

### Replies 根因

Replies 的专项 SPA 验证已经完成，并与 Profile 得到同一结论：进入 `/status/<tweet_id>` 后，`sourceForLocation()` 返回空值，`activeSource` 被置为 `null`，后续 heartbeat 和 scan 路径被 guard 跳过。返回 `/with_replies` 后，路由重新识别为 `with_replies`，heartbeat、fallback scan 和 lifecycle 自动恢复。

## 6. 验证结果

| 验证项 | 结果 |
|---|---|
| Backend 测试 | **24 passed** |
| Extension Vitest | **5 passed** |
| TypeScript 检查 | **通过** |
| MV3 build | **通过** |
| Backend 8787 health | **通过** |
| Profile / Replies 当前持续 heartbeat | **通过** |
| Tab discard / freeze 证据采集 | **通过** |
| Service Worker 转发成功/失败证据采集 | **通过** |

## 7. 阶段交付物

- [诊断报告](profile-replies-diagnostic.md)：链路、instrumentation、历史证据和观测方法。
- 本报告：本轮运行结果、A–H 判定和阶段状态。
- [Content Script](../extension/src/content.ts)：页面生命周期、timer、DOM、Observer 和 heartbeat 诊断。
- [Service Worker](../extension/src/background.ts)：消息转发和 Tab 状态诊断。
- [Backend main](../backend/app/main.py)：诊断事件和 health metadata 查询接口。
- [Backend models](../backend/app/models/__init__.py)：诊断事件数据模型。

## 8. 阶段状态与下一步

阶段状态：**诊断 instrumentation 已完成；Profile 和 Replies 的同一 SPA `/status/<id>` 路由问题已稳定复现；本阶段只诊断，不实施修复。**

如进入修复阶段，建议先做最小改动：在 `inspectLocation()` 中保留进入 `/status/<id>` 前的 monitor context。也就是当新路径是 Tweet status 且旧 `activeSource` 为 `profile_dom` 或 `with_replies` 时，继续沿用旧 source；不要把 status 页无条件映射成 Profile，也不要依赖 reload 或 self-healing。该建议本轮未实施。

## 9. SPA 路由专项验证最终结果

最终结论：**A. Profile 和 Replies 都可由同一个 SPA `/status/<id>` 路由问题稳定复现。**

### Replies 时间线

实验 Tab：`tab_id=973162737`。当前代码没有 `instance_id` 或 `sequence` 字段，因此本报告使用 Tab ID 作为实例标识，并使用 Backend 诊断事件 ID 作为事件顺序；不伪造缺失字段。

```text
18:09:07  最后一次 /with_replies heartbeat
18:09:10  LOCATION_CHANGED
          previous_source=with_replies
          next_source=null
18:09:59  Service Worker Tab snapshot：status 页，complete，未 discarded/frozen
18:10:59  同上
18:11:59  同上
18:12:18  进入 status 已超过 3 分钟；Replies 无新的 heartbeat/timer/scan/lifecycle 事件
18:23:06  返回 /with_replies 后 heartbeat 恢复
18:24:04  heartbeat timer、lifecycle、fallback timer 恢复
18:24:05  fallback scan 完成并再次发送 heartbeat
```

进入 status 时，Tab 仍然是 `complete`，`tab_discarded=false`、`tab_frozen=false`，Observer root 仍连接。因此停止点不是 Tab discard/freeze、DOM Observer、Service Worker forwarding 或 localhost Backend。

### Profile 时间线

实验 Tab：`tab_id=973162150`。

```text
21:53:43.242  进入 status 瞬间的一条在途 heartbeat
21:53:43.814  LOCATION_CHANGED
              previous_source=profile_dom
              next_source=null
21:53:59      Service Worker Tab snapshot：status 页，complete，未 discarded/frozen
21:54:59      同上
21:55:59      同上
21:56:59      同上
21:57:03      进入 status 已超过 3 分钟；无新的 Profile heartbeat/timer/scan/lifecycle 事件
22:04:28      返回 /thsottiaux 后 heartbeat 恢复
22:05:02/03  heartbeat timer、lifecycle、fallback timer、fallback scan 和 heartbeat 正常
```

Profile 的一条 heartbeat 发生在 `LOCATION_CHANGED` 记录前约 0.6 秒，属于路由检测前已启动的在途请求；它没有改变后续三周期完全停止的结论。

### 两次返回行为

两页从 status 返回原监控路由后都无需刷新即可恢复 heartbeat。这证明 content script、timer、Observer 和 Service Worker 并未整体死亡；核心问题是路由变化后 source context 被清空。当前 `LOCATION_CHANGED` 在从 `activeSource=null` 返回时不会单独持久化为 monitor 事件，但恢复后的 heartbeat、scan、lifecycle 和 Tab snapshot 已形成完整的可观测证据。

### A–H 最终判定

| 假设 | 最终判定 |
|---|---|
| A. Edge Tab discard / freeze | 排除；两次实验均为 `complete`、未 discarded/frozen |
| B. Content Script 失活 | 排除为主因；返回后同一 content script 自行恢复 |
| C. MV3 Service Worker 生命周期 | 排除为主因；Tab snapshot 持续，且没有 forwarding failure |
| D. X SPA 导航 / DOM 重建 | **确认：共同根因** |
| E. X 页面本身异常 | 无证据支持 |
| F. Heartbeat timer 停止但采集仍存活 | 直接表现为 route guard 后所有相关事件消失；根因属于 D 导致的 source guard |
| G. localhost Backend 接收问题 | 排除；进入 status 前 heartbeat 可达，Tab snapshot 仍持续写入 |
| H. 其他 | 未发现 |

本阶段未修改 Collector、health threshold、通知链路或 self-healing；未实施上述最小修复建议。

后续如授权进入修复阶段，应先补充 status route 的 monitor-context 单元测试，再进行最小代码修改和回归验证。

后续建议（不属于本阶段实施范围）：

1. 若授权进入修复阶段，先补充 status route 的 monitor-context 单元测试。
2. 实施前述最小修复建议，并验证 Profile、Replies 两条路径以及返回行为。
3. 保留 Replies instrumentation，继续作为回归证据。
4. 本阶段不修改 health threshold，不加入自动 reload 或 self-healing。
