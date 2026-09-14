# Codex Reset Radar — Phase B.5 分类验收报告

报告时间：2026-08-29 23:38（Asia/Shanghai）  
数据库：`backend/data/radar.db`  
Prompt：`tibo-classifier-v2-calibrated`  
本报告统计每个唯一 Tweet 的最新记录，同时保留数据库中的历史 Rule/AI/Final 审计行。

> 口径说明：本报告的分类校准表是 B.5 完成时的 107 条快照。2026-08-29 23:58 实时复查时新增的 `2076119366647894371` 已完成 v2 分类（`codex_related`），因此当前数据库为 108 条唯一 Tweet、108 条最新 Final、`classification_pending=0`；不影响本阶段校准结论和 12 条高价值人工复核结果。

## 1. 执行结果

| 项目 | 结果 |
|---|---:|
| 唯一 Tweet | **107** |
| 第一轮 B.5 force backfill | 107/107 classified，0 skipped，0 endpoint failed |
| 校准后第二轮 force backfill | 107/107 classified，0 skipped，0 endpoint failed |
| 最终修正文案后的第三轮 force backfill | 107/107 classified，0 skipped，0 endpoint failed |
| 最新 Rule records | 107 |
| 最新 Final records | 107 |
| 最新 `classification_pending` | **0** |
| 最新 `classification_conflict` | **1** |

“endpoint failed=0”表示 backfill 请求没有漏掉 Tweet；AI Provider 的历史失败单独计入下表。

## 2. Before / After Calibration

Before 使用校准前最近一轮 v1 Final；After 使用校准后最近一轮 v2 Final。

| 类别 | Before | After | 变化 |
|---|---:|---:|---:|
| `unrelated` | 91 | 90 | -1 |
| `codex_related` | 6 | 5 | -1 |
| `quota_information` | 3 | 3 | 0 |
| `reset_hint` | 2 | 3 | +1 |
| `reset_announcement` | 3 | 3 | 0 |
| `reset_in_progress` | 0 | 0 | 0 |
| `reset_confirmed` | 2 | 3 | +1 |
| `reset_denial` | 0 | 0 | 0 |
| **合计** | **107** | **107** | **0** |

发生类别变化的只有 2 条：`2093014447833116908` 从 `codex_related` → `reset_confirmed`；`2093551005711679557` 从 `unrelated` → `reset_hint`。详见 [phase-b5-changed-classifications.md](phase-b5-changed-classifications.md)。

## 3. 最新 Rule 分布

| 类别 | 数量 |
|---|---:|
| `unrelated` | 90 |
| `codex_related` | 6 |
| `quota_information` | 3 |
| `reset_hint` | 2 |
| `reset_announcement` | 3 |
| `reset_in_progress` | 0 |
| `reset_confirmed` | 3 |
| `reset_denial` | 0 |
| **合计** | **107** |

## 4. 最新 Final 分布

| 类别 | 数量 |
|---|---:|
| `unrelated` | 90 |
| `codex_related` | 5 |
| `quota_information` | 3 |
| `reset_hint` | 3 |
| `reset_announcement` | 3 |
| `reset_in_progress` | 0 |
| `reset_confirmed` | 3 |
| `reset_denial` | 0 |
| **合计** | **107** |

Final 的 1 条冲突是 `2093573991965557198`：Rule=`codex_related`，AI=`reset_hint`；Final 保留 AI 的 hint 类别并保留冲突标记，置信度 0.544。该记录已由用户确认，当前人工复核为 `Correct`。

## 5. DeepSeek 覆盖与表现

### 累计 AIUsage

| 指标 | 数量 |
|---|---:|
| 总实际调用 | **35** |
| 成功 | **34** |
| 失败 | **1** |
| 成功率 | **97.1%** |
| 最新模型 | `deepseek-v4-flash` |
| 总 input tokens（成功） | 63,941 |
| 总 output tokens（成功） | 21,407 |

唯一失败发生在校准前 v1 backfill；服务捕获后继续完成全量分类。校准后的 v2 两轮共覆盖 7 个 AI-required 样本、14 次调用，14 次成功、0 次失败；最终最新 pending 为 0。

### v2 最新 AI 分布

| 类别 | 数量 |
|---|---:|
| `codex_related` | 2 |
| `quota_information` | 1 |
| `reset_hint` | 3 |
| `reset_confirmed` | 1 |

明确的 Reset announcement/confirmed Rule 不重复调用 AI，但历史 v1 AI 结果和当前 v2 Rule/Final 都保留在审计表中。

## 6. Gold Set

Gold Set 文件：[backend/tests/fixtures/tibo_gold_set.json](../backend/tests/fixtures/tibo_gold_set.json)

- 5 条 `unrelated`
- 3 条 `codex_related`
- 3 条 `quota_information`
- 3 条 `reset_hint` 相关样本（含 AI-sensitive milestone）
- 3 条 `reset_announcement`
- 3 条 `reset_confirmed`
- 1 条 `reset_in_progress` 手工样本
- 1 条 `reset_denial` 手工样本
- Gold Set Rule 回归已纳入测试：通过

真实数据当前没有 `reset_in_progress` 和 `reset_denial`，所以这两个类别使用手工句子作为 Rule regression case，并没有伪装成真实 Tweet。

## 7. Radar 重新验收

当前 `/api/radar`：

```text
state: CONFIRMED
confidence: 0.99
urgency: now
trigger_tweet_id: 2091688655828246890
reason: Matched language stating that the reset or limits are complete.
expires_at: null
```

验收结论：

- 当前状态来自最新 Final，而不是旧 fallback；
- trigger Tweet 当前 Final 为 `reset_confirmed`，字段一致；
- 纯 `quota_information` 只产生 `WATCH`，并在 24 小时后过期，不会单独产生 `LIKELY`/`IMMINENT`；
- `reset_hint` 过期按 urgency 分层：`now`/`within_6h` 12 小时，`within_24h` 36 小时，其余 72 小时；
- 真实当前 Radar 的 `CONFIRMED` 是由于明确的 `Reset has been propagated to accounts`，不是 quota 单独抬高。

## 8. 人工复核预审结果

完整清单见 [phase-b5-review-table.md](phase-b5-review-table.md)。当前 12 条高价值真实记录中：12 条标记 `Correct`（其中 1 条 milestone 隐喻由用户确认），0 条 `Uncertain`，0 条 `Incorrect`。

样本 A–G 均已处理：

- A：`resets ... soon, but not today` → `reset_hint`；
- B：`reseted + brand new usage + button press` → `reset_confirmed`；
- C：`has been propagated` → `reset_confirmed`；
- D：`will land ... tomorrow` → `reset_announcement`；
- E：`banked reset will be there` → `reset_announcement`；
- F：`banked reset has landed` → `reset_confirmed`；
- G：`will credit ... BANKED reset` → `reset_announcement`。

## 9. Monitor Health

本次最终检查时：

| Monitor | 状态 |
|---|---|
| Backend | `healthy` |
| Search Backfill | `healthy` |
| Profile Monitor | `healthy` |
| Replies Monitor | `healthy` |

Profile/Replies 已在用户完成扩展 Reload、两个 X 页面刷新并保持运行后恢复 heartbeat。

## 10. 测试结果

最终代码回归：

- Backend：**16 passed**；
- Gold Set Rule assertions：包含在上述测试中并通过；
- Extension：Phase A 原有 5 tests 通过；
- TypeScript：`npx tsc --noEmit` 通过；
- MV3：`npm run build` 通过；
- 未增加真实 AI 到 unit test；真实 DeepSeek 验证通过全量 backfill 完成。

## 11. Phase B.5 验收结论

**自动化分类门：通过。**

已满足：

- pending=0；
- DeepSeek 真实调用成功，并覆盖 7 个当前 AI-required 历史样本；
- 高价值类别全部进入人工可审查清单；
- 已知误判样本已修复；
- Gold Set 已建立并纳入回归；
- Radar 已对齐最新 Final，不依赖旧 fallback；
- 累计 AI 冲突保留可审计，当前 1 条冲突 hint 已由用户确认。

**完整 Phase B.5：通过。** Profile/Replies Monitor 已恢复 healthy，milestone hint 已由用户确认。Phase C Alerting、WxPusher、Windows Toast、GitHub Mirror、Dashboard 按任务书继续暂停，除非另行授权。
