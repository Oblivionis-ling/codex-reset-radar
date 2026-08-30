# Codex Reset Radar — Phase C 通知系统进度与验收报告

报告时间：2026-08-30 11:47（Asia/Shanghai）  
当前基线：[Phase B.5 总报告](phase-b5-progress-report.md)  
本阶段范围：Alert Manager、WxPusher、Windows Toast、Alert 持久化/去重、Radar 升级、监控离线/恢复、历史 baseline。

## 1. 当前结论

Phase C 核心代码、自动化验收和真实 WxPusher 测试均已完成；用户已确认在微信端收到测试通知。真实测试使用本地 `.env` 中已配置的凭据发送，报告不记录凭据内容。

当前停止点：Phase C 已完成，等待后续阶段授权；不进入 GitHub Mirror、GitHub Pages 或 Dashboard。

## 2. 已实现内容

- `AlertManager` 只消费 Final Classification、Radar State、Tweet 和 Monitor Health，不再调用 DeepSeek；
- Radar 只在状态升级时通知：`LIKELY`、`IMMINENT`、`ANNOUNCED`、`CONFIRMED` 分别映射到固定 alert type；同级重复和状态降级默认不通知；但历史终态之后出现新的 `ANNOUNCED/CONFIRMED` trigger Tweet 时，作为新终态证据通知一次；
- alerts 表保存 `alert_type`、`tweet_id`、`radar_state`、`channel`、`status`、`created_at`、`sent_at`、`error`；同一事件在同一渠道只发送一次，WxPusher 与 Windows 可独立记录；
- 启动时写入当前 Radar/Monitor baseline，当前历史 `CONFIRMED` 不会启动即轰炸；
- WxPusher 处理 timeout、连接错误、HTTP 非 2xx、非法 JSON 和 API 错误，最多 3 次短间隔重试；失败写入 `status=failed`，不影响主链路；
- Windows Toast 使用本机 PowerShell/WinRT，不依赖云服务；
- Profile/Replies/Search/Backend 监控使用现有 15 分钟 warning、30 分钟 offline 判定；`offline` 只通知一次，恢复到 `healthy` 再通知一次；Profile/Replies 离线但 Search 健康时会明确提示仍可补抓；
- 新增 `GET /api/alerts` 和仅允许 localhost 的 `POST /api/alerts/test?channel=...`。

## 3. 当前 Notification 配置

只记录开关和配置状态，不记录 Secret：

| 项目 | 当前状态 |
|---|---|
| `ALERTS_ENABLED` | `.env` 未配置，代码默认启用 |
| `ALERT_DRY_RUN` | `.env` 未配置，代码默认关闭 |
| `WXPUSHER_ENABLED` | `true` |
| WxPusher App Token | 已配置（内容不记录） |
| WxPusher UID | 已配置（内容不记录） |
| `WINDOWS_NOTIFICATIONS_ENABLED` | `.env` 未配置，渠道关闭 |

## 4. 测试结果

| 测试 | 结果 |
|---|---|
| Backend 全测试（含 Phase C） | **23 passed** |
| Phase C 专项测试 | **7 passed** |
| Extension Vitest | **5 passed** |
| TypeScript `tsc --noEmit` | **通过** |
| MV3 `npm run build` | **通过** |
| Alert baseline | **通过**：当前历史 Radar 未生成通知 |
| Alert dedup | **通过** |
| State escalation | **通过** |
| WxPusher failure isolation | **通过** |
| Monitor offline/recovery | **通过** |
| Windows Toast 本机实测 | **通过**，2026-08-30 00:37 左右 |
| WxPusher 真实微信实测 | **通过**，2026-08-30 01:05，`alert_id=1`，API 返回 `status=sent`，用户确认已收到 |

## 5. 当前 Alert 数据

本次新 Backend 启动时读取到历史 Radar 为 `CONFIRMED`，baseline 正常建立，没有发送历史通知。随后真实 WxPusher 测试写入 1 条 `test` alert，`status=sent`、`error=null`；后续监控状态变化又产生 3 条 `sent` 记录；没有污染 Tibo Tweet 数据。

当前生产数据库共 4 条通知记录，全部 `sent`：1 条测试通知、2 条 `monitor_offline`、1 条 `monitor_recovered`。

专项测试使用临时数据库验证了：

- 同一 Radar 事件的两个渠道各最多 1 条；
- `WATCH → LIKELY → IMMINENT` 只产生两次升级通知；
- `IMMINENT → IMMINENT` 不重复；
- WxPusher timeout 最终写入 `failed`，主流程不抛错；
- `offline → healthy` 产生一次恢复通知。

## 6. 当前系统 Health

Backend 重启后实际检查：

| 组件 | 状态 |
|---|---|
| Backend | `healthy` |
| Profile Monitor | `offline` |
| Replies Monitor | `offline` |
| Search Backfill | `healthy` |

Backend 和 Search Backfill 当前运行正常；Profile/Replies 的 heartbeat 已过期，这是当前采集运行状态，不影响已完成的通知链路验收。若要恢复实时采集，请 reload 扩展并刷新两个 X 页面。

## 7. 用户下一步

真实测试接口已执行成功：`POST /api/alerts/test?channel=wxpusher` 返回 HTTP 200、`status=sent`，且你已确认微信收到测试通知。后续只需在需要实时采集时保持两个 X 页面运行；Token/UID 不要发给我、不要写入报告、不要提交 Git。

## 8. 阶段结论

| 验收项 | 结论 |
|---|---|
| Alert Manager | 通过 |
| Alert DB / Dedup | 通过 |
| Radar State Hook | 通过 |
| State Escalation / No Spam | 通过 |
| Historical Baseline | 通过 |
| Monitor Offline / Recovery | 自动化通过；当前 Profile/Replies heartbeat 已过期 |
| Windows Toast | 本机实测通过 |
| WxPusher 真实微信 | **发送通过，用户已确认收到** |
| **Phase C** | **正式通过** |
