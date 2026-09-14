# Codex Reset Radar — WxPusher / 微信通知渠道诊断报告

报告日期：2026-09-02（Asia/Shanghai）  
诊断范围：Radar → Alert Manager → WxPusher API → WxPusher 异步投递 → 微信客户端。  
原则：本轮只做诊断和可观测性增强，没有修改 Radar 规则、分类阈值、去重规则、SQLite schema 或更换通知服务。

## 1. 最终结论

本轮没有发现本机配置、Backend 进程、Alert Manager 或 WxPusher HTTP 请求失败。真实 TEST 请求已经到达 WxPusher：HTTP 200、业务码 `1000`，并获得 `sendRecordId`。

但是，查询该发送记录在发送后约 6 分钟时仍返回：

```text
HTTP 200
code=1000
data=1
msg=等待发送
```

因此当前能够确认的故障边界是：

> WxPusher 已接受异步发送任务，但下游发送记录仍停留在“等待发送”；微信客户端是否展示无法由当前证据确认。

这不是“HTTP 请求失败”，也不能直接归因于 UID 失效、公众号未关注或微信渠道机制变化。需要用户人工确认是否收到 TEST 消息；在人工确认前，最后一跳结论为 `UNKNOWN`。

对“长时间没有普通通知”的主要解释是：数据库中的 41 条高价值 Classification 是历史/重复分类结果，不等于 41 次新的 Radar 通知事件；Backend 启动时会建立当前状态 baseline，不会把历史 `CONFIRMED` 等状态重新发送。当前 SQLite 中没有新的 Radar alert 行，因此没有证据表明这些历史信号被 WxPusher 失败吞掉。

## 2. Current Architecture

当前真实代码链路为：

```text
新 Tweet / Final Classification / Monitor Health
        ↓
Radar update_radar()
        ↓
AlertManager.handle_radar_transition()
或 AlertManager.evaluate_monitor_health()
        ↓
AlertManager._dispatch()
        ↓
AlertManager._deliver()
        ↓
WxPusherNotifier.send()
        ↓
POST https://wxpusher.zjiecode.com/api/send/message
        ↓
appToken + UID
        ↓
WxPusher 异步发送记录
        ↓
微信客户端
```

本地测试入口仍为：

```text
POST http://127.0.0.1:8787/api/alerts/test?channel=wxpusher
```

该入口生成独立 `alert_type=test`，不创建假 Tweet、不写入 `reset_confirmed`，不会污染 Reset History、Radar 或 Forecast。

新增的持久化诊断日志为：

```text
D:\work\20260828-CodexResetRadar\backend\data\notification-delivery.jsonl
```

日志只保存结构化元数据，不保存消息正文、Token 或完整 UID。

## 3. Configuration and Runtime

| 项目 | 结果 |
|---|---|
| `WXPUSHER_ENABLED` | `true` |
| `ALERTS_ENABLED` | `true` |
| `ALERT_DRY_RUN` | `false` |
| App Token | 已配置；长度 37；格式前缀检查通过；内容不记录 |
| UID | 已配置；长度 32；格式前缀检查通过；内容不记录 |
| Topic ID | 未配置 |
| `WINDOWS_NOTIFICATIONS_ENABLED` | 未配置，生产渠道关闭 |
| Backend | `/health` 正常；当前监听进程于 2026-09-02 18:29:26 启动 |
| SQLite | 原文件保留，未删除、未 reset |

新进程启动日志确认：

```text
WXPUSHER_CONFIG_CHECK enabled=True alerts_enabled=True dry_run=False
app_token_configured=True recipient_configured=True uid_length=32
WXPUSHER_PROVIDER_INITIALIZED ...
```

因此 `.env` 中有配置但 Backend 未加载配置这一类问题已排除。

## 4. Recent Alert History

从当前 `backend/data/radar.db` 查询：

| 指标 | 数量/结果 |
|---|---:|
| 最近 30 天高价值 Final Classification 候选 | 41 |
| `reset_hint` | 16 |
| `reset_announcement` | 13 |
| `reset_in_progress` | 0 |
| `reset_confirmed` | 12 |
| 最近 30 天 Alert 总数 | 7 |
| Alert `sent` | 7 |
| Alert `failed` | 0 |
| Alert `skipped` / `dry_run` | 0 |

Alert 类型分布：

- `test`：2 条；
- `monitor_offline`：2 条；
- `monitor_recovered`：3 条；
- Radar `reset_likely` / `reset_imminent` / `reset_announced` / `reset_confirmed`：0 条。

Radar history 中有 9 条状态历史，但其中包含大量历史状态和重复评估。启动 baseline 会记录当前 Radar，不会重播历史状态；因此不能把 41 条 Classification 直接当成 41 次应发送通知。

当前实现没有独立 cooldown 机制；生产去重是同一 `alert_type + tweet_id + radar_state + channel` 的唯一组合。新增日志会明确记录 `ALERT_RECEIVED`、`ALERT_DISPATCH_STARTED` 和 `ALERT_SUPPRESSED reason=dedup/disabled/dry_run/no_recipient`。

## 5. Test Notification

### 5.1 Alert Manager → WxPusher

测试时间：2026-09-02 18:27:29（Asia/Shanghai，约 10:27:29 UTC）。  
数据库 `alert_id`：`7`。  
测试消息标题：`TEST | Codex Reset Radar 通知测试`。  
消息正文包含 `TEST` 和北京时间发送时间，不会被误认为真实 Reset。

本地诊断日志对应时间线：

| 时间（UTC） | 事件 | 结果 |
|---|---|---|
| 10:27:29.740 | `ALERT_RECEIVED` | 收到独立 TEST alert |
| 10:27:29.744 | `ALERT_DISPATCH_STARTED` | 选择 `wxpusher` 渠道 |
| 10:27:29.746 | `WXPUSHER_REQUEST_STARTED` | 发起真实请求 |
| 10:27:29.872 | `WXPUSHER_REQUEST_SUCCESS` | HTTP/API 成功 |

测试接口返回：

```json
{
  "ok": true,
  "alert_id": 7,
  "channel": "wxpusher",
  "status": "sent",
  "error": null,
  "delivery": {
    "http_status": 200,
    "response_code": 1000,
    "send_record_id": 2438072956,
    "duration_ms": 125,
    "delivery_status": "accepted_async",
    "attempt": 1
  }
}
```

这里的 `status=sent` 表示 Provider 调用成功；`delivery_status=accepted_async` 明确表示不能等同于微信客户端已展示。

### 5.2 WxPusher 发送记录查询

依据 WxPusher 当前官方文档，使用：

```text
GET https://wxpusher.zjiecode.com/api/send/query/status?sendRecordId=2438072956
```

查询结果在发送后立即、5 秒、约 15 秒以及约 6 分钟复查均为：

```json
{
  "code": 1000,
  "msg": "等待发送",
  "data": 1,
  "success": true
}
```

这说明 WxPusher 接口可访问且查询成功，但当前发送记录还没有进入可确认的成功状态。官方文档同时说明发送接口是异步分发，接口成功只代表发送任务已创建。

官方资料：

- [WxPusher API Reference](https://wxpusher.zjiecode.com/docs/api-reference.html)
- [WxPusher 当前 OpenAPI](https://github.com/wxpusher/wxpusher-docs/blob/master/docs/openapi.yaml)

当前官方资料仍支持 `appToken + UID` 标准推送，也仍提供发送状态查询；没有证据表明本项目调用的发送 API 已被废弃或必须迁移。

## 6. Windows Toast Comparison

`.env` 中 `WINDOWS_NOTIFICATIONS_ENABLED` 未配置，因此没有打开生产 Windows 渠道。作为对照，本轮直接调用现有 `WindowsToastNotifier` 发送同样标记为 TEST 的本机消息，PowerShell/Toast Provider 返回：

```json
{"result":"sent","delivery_status":"local_provider_returned"}
```

这说明本机 Windows Provider 命令执行成功；由于没有做屏幕级人工确认，不能把它扩展为“Toast 已在屏幕展示”。该对照没有写入生产 Alert 行，也没有改变 Windows 配置。

## 7. Four-Layer Result Matrix

| Layer | Result | 证据 |
|---|---|---|
| Radar → Alert Manager | **PASS（TEST 路径）** | `ALERT_RECEIVED`、`ALERT_DISPATCH_STARTED`，alert `7` 建立；历史状态按 baseline 不重播 |
| Alert Manager → WxPusher Provider | **PASS** | Provider 调用返回，Alert `status=sent`，无异常 |
| WxPusher Provider → WxPusher API | **PASS** | HTTP 200、业务码 1000、耗时 125 ms、返回 `sendRecordId` |
| WxPusher → 微信 | **UNKNOWN / PENDING** | 官方状态查询仍为 `data=1`、`等待发送`；未获得微信客户端人工确认 |

## 8. Primary Root Cause

针对当前“TEST 已发送但尚未能确认微信收到”的现象，唯一可被证据支持的主要根因是：

> **WxPusher 已接受任务，但其下游异步发送记录持续停留在“等待发送”；问题位于 WxPusher API 接受之后，具体是微信渠道、UID/订阅关系或 WxPusher 队列原因目前无法进一步区分。**

针对“为什么长期没有普通通知”，当前主要原因是：

> **运行期间没有可观察到新的 Radar alert dispatch；已有高价值分类主要是历史/重复分类，且 Backend baseline 设计不会在启动时回放历史 Radar。**

这两条现象需要分开：前者是最后一跳的未决投递问题，后者不是已证实的 Alert Manager 丢消息问题。没有证据支持以下结论：

- Token 未加载；
- UID 格式不合法；
- Alert Manager 没有调用 Provider；
- 本机到 WxPusher 的 HTTP 请求失败；
- Radar 曾产生真实新升级事件但被 cooldown 压制；
- WxPusher 官方已取消 App Token + UID 模式。

## 9. Implemented Diagnostics

本轮仅增加诊断能力：

- `backend/app/notifications/wxpusher.py`
  - 记录 Provider 初始化、请求开始、HTTP status、API code、msg、耗时；
  - 解析 `sendRecordId`；
  - 增加官方状态查询接口；
  - 对 HTTP、连接、超时、非法 JSON、API 业务错误保留分类字段。
- `backend/app/notifications/alert_manager.py`
  - 增加 `ALERT_RECEIVED`、`ALERT_DISPATCH_STARTED`、`ALERT_SUPPRESSED`；
  - 保存脱敏 `notification-delivery.jsonl`；
  - 测试消息明确标记 TEST；
  - 保存 Provider 返回详情供本地测试接口查看。
- `backend/app/main.py`
  - `/api/alerts/test` 返回脱敏 delivery 元数据。

未修改：Alert 规则、Radar、Collector、DeepSeek、Translation、WxPusher 服务迁移、SQLite schema、Dashboard。

## 10. Regression and Secret Checks

| 检查项 | 结果 |
|---|---:|
| Backend pytest | **48 passed** |
| Python compileall | **通过** |
| Dashboard Vitest | **8 passed** |
| Dashboard TypeScript + Vite build | **通过** |
| Extension Vitest | **12 passed** |
| Extension Vite build | **通过** |
| 配置值加载验证 | **通过，均只输出 configured/length/prefix 结果** |
| 实际配置 Secret 扫描 source diff | **未发现** |

结论停止点：保留现有 WxPusher，不自动迁移、不删除、不重写 Alert Manager。下一步只需要用户确认微信中是否收到标题为 `TEST | Codex Reset Radar 通知测试` 的消息；若未收到，应在 WxPusher 管理端检查该发送记录和 UID/微信订阅状态，再决定是否修复渠道。
