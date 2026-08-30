# Codex Reset Radar — Phase B.5 进度与验收总报告

报告时间：2026-08-29 23:53（Asia/Shanghai）  
当前基线：`docs/phase-b-progress-report.md`  
本次范围：真实 DeepSeek 覆盖、Rule/Prompt/Resolver/Radar 校准、Gold Set、人工复核材料和运行状态检查。

## 1. 总结结论

Phase B.5 的分类校准工作已经完成，107 条唯一 Tweet 已完成最终全量重分类：

- 最新 `classification_pending=0`；
- 当前规则需要 AI 的 7 条样本均已由 DeepSeek v2 覆盖，两轮共 14 次调用全部成功；
- 已知样本 A–G 已修正或重新确认；
- Gold Set 已建立并纳入自动回归；
- Radar 已从旧的 quota fallback 对齐到最新 `reset_confirmed` Final；
- Review Table、Before/After 和类别变化文件已生成。

因此：

> **Phase B.5 已通过。** 自动化分类验收、人工复核、四项服务健康状态和 Radar 运行状态均已满足本阶段验收条件。

本阶段没有开发通知、Dashboard、GitHub Mirror 或新部署方式。

> 实时复查附注（2026-08-29 23:58）：在持续运行期间新增 1 条普通 Tweet（`2076119366647894371`），已完成 v2 Rule/DeepSeek/Final 分类，结果为 `codex_related`。当前数据库为 108 条唯一 Tweet、108 条最新 Final、`classification_pending=0`；下文 Before/After 与三轮 backfill 数字保留 B.5 校准完成时的 107 条快照口径。

## 2. 实际执行记录

| 阶段 | 结果 |
|---|---|
| B.5 初始全量 force backfill（v1） | 107/107 classified，0 skipped，0 endpoint failed；20 成功、1 Provider 失败 |
| Rule/Prompt/Resolver 校准 | 完成；Prompt version 升级为 `tibo-classifier-v2-calibrated` |
| 校准后全量 force backfill（v2，第 1 轮） | 107/107 classified，0 skipped，0 endpoint failed |
| Rule-only reason 修正后全量 force backfill（v2，第 2 轮） | 107/107 classified，0 skipped，0 endpoint failed |
| 最终数据库状态 | 107 条唯一 Tweet，pending=0 |

## 3. 本次代码校准

- Rule 支持 `reset`、`resets`、`resetting`、`reseted`、`resetted`；
- 明确区分 `reset_hint`、`reset_announcement`、`reset_in_progress`、`reset_confirmed`；
- `banked reset will be ...` 归 announcement，`banked reset has landed` 归 confirmed；
- `5h limit` 等纯额度政策归 `quota_information`，不再因为 tomorrow 自动变成 reset hint；
- `soon, but not today` 归带时间语义的 hint，不误判为 denial；
- 高置信度 AI Reset 事件可以覆盖低置信度 quota/hint Rule 初判，但仍保留 conflict 审计；
- 明确 Rule 不需要 AI 时不再虚假追加 “AI unavailable” fallback；
- Radar expiry 调整为：hint 的 `now/within_6h` 为 12h、`within_24h` 为 36h、其他为 72h；quota 仍为 24h。

主要实现文件：

- `backend/app/classifiers/rules.py`
- `backend/app/classifiers/rule_classifier.py`
- `backend/app/classifiers/providers/deepseek.py`
- `backend/app/intelligence/classification_resolver.py`
- `backend/app/intelligence/radar.py`

## 4. Before / After 分类变化

比较校准前最近一轮 v1 Final 与校准后最近一轮 v2 Final：

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

类别实际变化只有两条：

- `2093014447833116908`：`codex_related` → `reset_confirmed`；
- `2093551005711679557`：`unrelated` → `reset_hint`。

详见 [phase-b5-changed-classifications.md](phase-b5-changed-classifications.md)。

## 5. 当前分类与 AI 指标

### 最新 Final

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

### DeepSeek

- 累计实际调用：35；成功 34；失败 1；成功率 97.1%；
- 校准后 v2：7 个 AI-required 样本，执行两轮共 14 次，14 成功、0 失败；
- 最新 `classification_pending`：0；
- 最新 `classification_conflict`：1；
- 当前模型：`deepseek-v4-flash`；
- 成功调用累计 tokens：input 63,941，output 21,407。

唯一当前冲突为 `2093573991965557198`：Rule=`codex_related`、AI=`reset_hint`，Final 保留 `reset_hint` 但置信度 0.544。用户已确认该记录作为 `reset_hint`，不再列为 `Uncertain`。

## 6. Gold Set 与自动化验证

Gold Set：[backend/tests/fixtures/tibo_gold_set.json](../backend/tests/fixtures/tibo_gold_set.json)

- 共 22 条：20 条真实 Tweet、2 条手工边界句；
- 至少包含 5 unrelated、3 codex_related、3 quota_information；
- 包含现有 hint、announcement、confirmed 真实样本；
- 以手工句覆盖真实库中暂缺的 `reset_in_progress` 和 `reset_denial`；
- Gold Set Rule 断言已加入 `backend/tests/test_phase_b.py`。

最终验证结果：

- Backend：**16 passed**；
- Extension：**5 passed**；
- TypeScript：`npx tsc --noEmit` 通过；
- MV3：`npm run build` 通过；
- 真实 DeepSeek：全量 backfill 完成；unit test 未直接消耗真实 API。

## 7. 高价值信号复核

人工材料：[phase-b5-review-table.md](phase-b5-review-table.md)

当前高价值真实记录 12 条：12 条均为 `Correct`（其中 1 条为用户确认）、0 条 `Uncertain`、0 条 `Incorrect`。

```text
2093573991965557198
Looking at the dashboard we might hit a new milestone to celebrate tomorrow. Hold on to your Codex
```

它没有直接说 reset，AI 根据历史 milestone pattern 给出 `reset_hint`；你已确认该记录可纳入 Reset Radar。

样本 A–G 结果：

- A `resets ... soon, but not today` → `reset_hint`；
- B `reseted + brand new usage + button press` → `reset_confirmed`；
- C `has been propagated` → `reset_confirmed`；
- D `will land ... tomorrow` → `reset_announcement`；
- E `banked reset will be there` → `reset_announcement`；
- F `banked reset has landed` → `reset_confirmed`；
- G `will credit ... BANKED reset` → `reset_announcement`。

## 8. Radar 重新验收

当前 `GET /api/radar`：

```text
state: CONFIRMED
confidence: 0.99
urgency: now
trigger_tweet_id: 2091688655828246890
reason: Matched language stating that the reset or limits are complete.
expires_at: null
```

验收结论：

- 状态来自最新 Final，而非旧 fallback；
- trigger Tweet 的最新 Final 是 `reset_confirmed`；
- 纯 quota 只会产生短期 `WATCH`，不会单独产生 `LIKELY`/`IMMINENT`；
- 当前 `CONFIRMED` 来自 `Reset has been propagated to accounts`，不是 quota 单独抬高。

## 9. 当前运行健康

最终检查时间约 23:53：

| 组件 | 状态 |
|---|---|
| Backend | `healthy`，`/health` 返回 `ok`，当前 108 Tweet |
| Search Backfill | `healthy`，最近心跳约 4 分钟内 |
| Profile Monitor | `healthy` |
| Replies Monitor | `healthy` |

Profile/Replies 已在你 reload 扩展、刷新两个 X 页面并保持运行后恢复 heartbeat；没有改动账号或扩展权限。

## 10. 你需要完成的最后一步

你已完成 Edge 侧的 reload、两个 X 页面刷新和持续运行；四项服务均为 `healthy`。按照任务书，Phase C 通知开发仍保持暂停，除非你另行授权启动。

## 11. 阶段结论

| 验收项 | 结论 |
|---|---|
| 真实 AI Backfill | 通过 |
| Rule/Prompt/Resolver 校准 | 通过 |
| Pending 清零 | 通过 |
| Gold Set 与回归 | 通过 |
| Radar 对齐最新 Final | 通过 |
| 高价值人工材料 | 已完成，12 Correct、0 Uncertain、0 Incorrect |
| Profile/Replies Monitor | 通过，均为 healthy |
| **完整 Phase B.5** | **通过** |
