# Codex Reset Radar — 第二阶段进度与运行验收报告

报告时间：2026-08-29 22:59（Asia/Shanghai）  
数据来源：运行中的 Backend、`/api/health`、`/api/radar` 与本地 SQLite `backend/data/radar.db`。  
本报告以第二阶段开发任务书为验收基准，并以本次实况数据为准；此前的 46 条 Tweet 报告属于历史快照。

## 1. 结论

Phase B 的 Milestone 3–7 已实现，自动化测试和 MV3 构建均通过，当前本地后端也在正常运行。当前状态应定义为：

> **代码开发完成，采集/分类链路运行中，等待剩余 AI 分类和人工复核后再完成阶段验收。**

目前还不能把 Radar 的 `WATCH` 当作已经确认的 Reset 预测，原因是：

- 107 条唯一 Tweet 中，最新 Final 结果有 9 条仍为 `classification_pending=true`；
- DeepSeek 目前只有 1 次成功调用，尚未覆盖全部需要语义判断的历史信号；
- 当前 Radar 触发记录仍是旧的 Rule fallback 结果；
- Profile 和 Replies 两个 Edge 监控页面目前离线，Search Backfill 仍健康。

按照任务书，本阶段尚未接入 WxPusher、Windows Toast、GitHub Mirror 或 Dashboard，这是预期范围。

## 2. 当前运行状态

| 组件 | 当前状态 | 证据 |
|---|---|---|
| Backend | healthy | `127.0.0.1:8787` 正在监听；进程 PID 17752，2026-08-29 22:00:09 启动；`/health` 返回 `ok` |
| Search Backfill | healthy | 最后心跳 22:56:38，最后看到 Tweet 22:56:35，检查时约 3 分钟前 |
| Profile Monitor | offline | 最后心跳 2026-08-28 18:13:41 |
| Replies Monitor | offline | 最后心跳 2026-08-29 01:09:41 |
| SQLite | healthy | 当前 107 条唯一 Tweet |

多来源记录数量为：`search` 107、`profile_dom` 11、`with_replies` 14。Tweet 主表仍按 `tweet_id` 去重，因此不是 132 条，而是 107 条唯一 Tweet。

## 3. Milestone 完成情况

| Milestone | 内容 | 状态 |
|---|---|---|
| 3 | 本地 Rule Classifier、8 类枚举、denial-first 优先级、`requires_ai` | 已完成 |
| 4 | DeepSeek Provider、模型/Base URL 配置化、Pydantic 结构校验、超时/HTTP/JSON fallback | 已完成 |
| 5 | SQLite Context Engine，包含 parent、最多 10 条相关 Tweet、最近 reset/status 上下文 | 已完成 |
| 6 | Rule/AI/Final 审计记录、Resolver 冲突处理、pending 标记 | 已完成 |
| 7 | Radar State、过期机制、`radar_state_history`、Radar API | 已完成 |

已提供的主要 API：

- `GET /api/radar`
- `GET /api/tweets/{tweet_id}/classification`
- `POST /api/tweets/{tweet_id}/reclassify`
- `POST /api/classify/backfill`

新 Tweet 入库后会通过后台任务进入分类，不阻塞 Collector 的入库响应。

## 4. 自动化验证

本次重新执行结果：

| 验证项 | 结果 |
|---|---:|
| Backend 全部测试 | **12 passed** |
| Extension Vitest | **5 passed**（2 个测试文件） |
| TypeScript `npx tsc --noEmit` | **通过** |
| MV3 `npm run build` | **通过** |
| 既有 Phase A 测试 | 包含在 Backend 测试集中，未被破坏 |

覆盖内容包括 Rule 优先级、否定保护、Hint、Context 选择、Resolver、Mock AI 审计、AI 失败 fallback、Radar 状态过期和 API。

## 5. 真实数据分类结果

统计口径为每个唯一 Tweet 的最新 Rule/Final 记录。数据库保留历史记录，因此 Final 表实际有 108 行：其中 1 条 Tweet 被重新分类过；最新状态仍对应 107 条唯一 Tweet。

### 最新 Final 分布

| 类别 | 数量 |
|---|---:|
| `unrelated` | 91 |
| `codex_related` | 7 |
| `quota_information` | 5 |
| `reset_hint` | 4 |
| `reset_announcement` | 0 |
| `reset_in_progress` | 0 |
| `reset_confirmed` | 0 |
| `reset_denial` | 0 |
| **合计** | **107** |

Rule 最新记录与上述分布一致。当前最新 Final 中：98 条已完成，9 条仍为 `classification_pending=true`，`classification_conflict=1` 的记录为 0 条。

## 6. DeepSeek 表现

当前 `.env` 已配置 DeepSeek，运行进程于配置后启动，数据库已有真实调用记录：

| 指标 | 数量 |
|---|---:|
| 总调用 | 1 |
| 成功 | 1 |
| 失败 | 0 |
| Rule/AI 冲突 | 0 |
| 当前 AI 模型 | `deepseek-v4-flash` |
| 成功调用时间 | 2026-08-29 22:00:37（北京时间，数据库 UTC 14:00:37） |
| 成功调用 token | input 1748 / output 528 |

这 1 次调用复核的是 `reset_hint`：Rule 为 `reset_hint`、0.72，AI 为 `reset_hint`、0.70，Final 为 `reset_hint`、0.70，判定为带有 reset-button 隐喻和 tomorrow 时间语义的隐含提示。

其余 9 条 pending 主要来自 API Key 尚未配置时的历史分类；它们没有产生 AI 失败记录，而是保留了 Rule fallback。

## 7. 高价值 Signal 人工复核清单

当前最新 Final 中有 9 条需要优先人工查看的 quota/reset 信号。以下列出主要内容，文本过长处按数据库原文截取显示。

### `reset_hint`

| Tweet ID | Tweet 文本 | Rule | AI | Final | Pending |
|---|---|---|---|---|---|
| `2092862554632826968` | “...pressed the reset button... find it tomorrow and dust it up” | `reset_hint` 0.72 | `reset_hint` 0.70 | `reset_hint` 0.70 / `within_24h` | 否 |
| `2092058556707344708` | “Tomorrow we will bring back the 5h limit for Plus accounts...” | `reset_hint` 0.72 | 未调用 | `reset_hint` 0.72 / `within_24h` | 是 |
| `2091688655828246890` | “Reset has been propagated to accounts... positive difference...” | `reset_hint` 0.72 | 未调用 | `reset_hint` 0.72 / `within_24h` | 是 |
| `2091412393368945027` | “Reset will land around 14pm PST tomorrow.” | `reset_hint` 0.72 | 未调用 | `reset_hint` 0.72 / `within_24h` | 是 |

### `quota_information`

| Tweet ID | Tweet 文本 | Rule | AI | Final | Pending |
|---|---|---|---|---|---|
| `2091407991736332689` | “Update on rate limits in Codex...” | `quota_information` 0.94 | 未调用 | `quota_information` 0.94 | 否 |
| `2091033630147854385` | “Update on rate limits in Codex...” | `quota_information` 0.94 | 未调用 | `quota_information` 0.94 | 否 |
| `2090964822422949999` | “The banked reset has landed...” | `quota_information` 0.78 | 未调用 | `quota_information` 0.78 | 是 |
| `2090947196107764189` | “The banked reset will be there by 8pm PST...” | `quota_information` 0.78 | 未调用 | `quota_information` 0.78 | 是 |
| `2090766694897619318` | “...credit every Codex and ChatGPT Work user with a BANKED reset...” | `quota_information` 0.78 | 未调用 | `quota_information` 0.78 | 是 |

当前没有被判为 `reset_announcement`、`reset_in_progress`、`reset_confirmed` 或 `reset_denial` 的记录。

## 8. 当前 Radar

```text
state: WATCH
confidence: 0.94
urgency: unknown
trigger_tweet_id: 2091033630147854385
updated_at: 2026-08-29 22:59:36 +08:00
expires_at: 2026-08-29 23:56:15 +08:00
```

当前原因是：检测到 quota / usage-limit 信号，但没有确认 Reset 动作。这个触发 Tweet 是 `quota_information`，目前仍是旧的 Rule fallback 结果，所以 Radar 当前表示“需要关注”，不表示“Reset 已确认”。完成 pending 重新分类后应再次检查状态是否变化。

## 9. 已知问题与风险

1. **AI 覆盖率不足。** 当前只有 1 条成功 AI 结果，9 条最新 Final 仍 pending；需要执行一次强制 backfill。
2. **规则对词形和隐喻仍有限制。** 例如 “There is a place and a time for resets. Soon, but not today” 当前被判为 `unrelated`；包含 “reseted / brand new usage / button press” 的 Tweet 当前被判为 `codex_related`。这些应在人工复核中作为潜在漏报/误报样本记录。
3. **Radar 仍受 fallback 结果影响。** 当前 `WATCH` 的 reason 中包含 `AI unavailable`，待重新分类后再评估。
4. **Profile/Replies 监控离线。** 这不影响已存在的数据库和 Search Backfill，但会影响后续实时采集覆盖率。
5. **Phase A 延后验证仍未完成。** 页面刷新恢复、Backend 重启恢复、7 天 Deep Backfill 首个 6 小时周期和真实漏报率统计继续记录为 `Deferred Phase A Validation`。
6. **通知和展示层尚未开发。** WxPusher、Windows Toast、GitHub Mirror、GitHub Pages Dashboard 按任务书留到后续阶段，当前不会自动发通知。

## 10. 下一步与停止点

建议先完成分类验收，不继续扩展通知或 Dashboard：

1. 保持当前 Backend 运行。
2. 在项目根目录确认 `.env` 中使用的是自己的 DeepSeek Key，不要把 Key 写入报告或提交到仓库。
3. 执行一次全量强制重分类：

```powershell
Invoke-RestMethod -Method Post `
  'http://127.0.0.1:8787/api/classify/backfill?force=true'
```

4. 再查询 `/api/health`、`/api/radar`，并人工复核上述高价值 Tweet。
5. 复核通过后，才进入下一阶段的 Alert Manager / WxPusher / Windows Toast / Mirror / Dashboard。

**第二阶段停止点：** Milestone 3–7 已完成；当前停在“补齐真实 DeepSeek 分类并人工确认结果”。
