# Phase B.5 人工复核清单

生成时间：2026-08-29 23:38（Asia/Shanghai）  
数据口径：107 条唯一 Tweet 的最新 `tibo-classifier-v2-calibrated` Final。正文保持数据库原文，不以摘要替代。  
本清单只列高价值类别：`reset_hint`、`reset_announcement`、`reset_in_progress`、`reset_confirmed`、`reset_denial`、`quota_information`。

所有以下记录的 `is_reply=false`、`Parent context=无（reply_to=NULL）`。其中“AI 未调用”表示当前 v2 Rule 已明确，不是漏记；若有历史 v1 AI 结果会单独标明。

## 2093573991965557198

- 时间（数据库 `created_at`）：`2026-08-29 05:38:31`
- 正文：Looking at the dashboard we might hit a new milestone to celebrate tomorrow. Hold on to your Codex
- Rule Result：`codex_related`, confidence `0.68`, urgency `within_24h`, explicitness `unclear`。Reason：Matched Codex-related terminology without a direct reset signal.
- AI Result（v2）：`reset_hint`, confidence `0.72`, urgency `within_24h`, explicitness `implicit`。Reason：The tweet indirectly hints at a reset through a milestone celebration tomorrow, without explicitly mentioning reset. 'Hold on to your Codex' suggests an upcoming event, and prior context ties milestones to resets.
- Final Result：`reset_hint`, confidence `0.544`, urgency `within_24h`, explicitness `implicit`。Pending `false`，Conflict `true`。Reason：Rule/AI conflict: rule=codex_related; AI=reset_hint. The tweet indirectly hints at a reset through a milestone celebration tomorrow, without explicitly mentioning reset. 'Hold on to your Codex' suggests an upcoming event, and prior context ties milestones to resets.
- Expected Category：`reset_hint`
- Review：`Correct（用户已确认）`
- Notes：这是间接 milestone hint；AI 支持 reset_hint。用户已确认该记录可作为 reset_hint 进入 Reset Radar。

## 2093551005711679557

- 时间（数据库 `created_at`）：`2026-08-29 04:07:10`
- 正文：There is a place and a time for resets. Soon, but not today
- Rule Result：`reset_hint`, confidence `0.72`, urgency `within_3d`, explicitness `implicit`。Reason：Matched a known reset-button or time-linked hint pattern; semantic review is required.
- AI Result（v2）：`reset_hint`, confidence `0.72`, urgency `within_3d`, explicitness `implicit`。Reason：The tweet implies a reset will happen soon but does not specify a schedule or confirm an event, making it a playful hint rather than an announcement. It mentions resets indirectly with 'there is a place and a time' and 'soon, but not today'.
- Final Result：`reset_hint`, confidence `0.72`, urgency `within_3d`, explicitness `implicit`。Pending `false`，Conflict `false`。Reason：The tweet implies a reset will happen soon but does not specify a schedule or confirm an event, making it a playful hint rather than an announcement. It mentions resets indirectly with 'there is a place and a time' and 'soon, but not today'.
- Expected Category：`reset_hint`
- Review：`Correct`
- Notes：已修复原先被判为 `unrelated` 的问题；“not today”被按时间语义处理，没有误判成 denial。

## 2093014447833116908

- 时间（数据库 `created_at`）：`2026-08-27 16:35:05`
- 正文：Never slept better and feeling reseted. Brand new me and brand new usage for all ChatGPT Work and Codex users. Regaining my youth one button press at a time. Happy Thursday
- Rule Result：`reset_confirmed`, confidence `0.82`, urgency `now`, explicitness `explicit`。Reason：Matched reset vocabulary with restored/new usage language; semantic review is required.
- AI Result（v2）：`reset_confirmed`, confidence `0.85`, urgency `now`, explicitness `explicit`。Reason：The tweet uses 'reseted' and states 'brand new usage for all ChatGPT Work and Codex users', indicating the reset has already taken effect.
- Final Result：`reset_confirmed`, confidence `0.85`, urgency `now`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：The tweet uses 'reseted' and states 'brand new usage for all ChatGPT Work and Codex users', indicating the reset has already taken effect.
- Expected Category：`reset_confirmed`
- Review：`Correct`
- Notes：已修复 `reseted`、恢复 usage 和 button press 组合被降为 `codex_related` 的问题。

## 2092862554632826968

- 时间（数据库 `created_at`）：`2026-08-27 06:31:31`
- 正文：A good thing about having aged is that I feel that it��s been 20 years since I��ve pressed the reset button. Intrigued to see if I can find it tomorrow and dust it up
- Rule Result：`reset_hint`, confidence `0.72`, urgency `within_24h`, explicitness `implicit`。Reason：Matched a known reset-button or time-linked hint pattern; semantic review is required.
- AI Result（v2）：`reset_hint`, confidence `0.72`, urgency `within_24h`, explicitness `implicit`。Reason：User metaphorically refers to pressing the reset button and looking for it tomorrow, implying a possible reset without explicit statement.
- Final Result：`reset_hint`, confidence `0.72`, urgency `within_24h`, explicitness `implicit`。Pending `false`，Conflict `false`。Reason：User metaphorically refers to pressing the reset button and looking for it tomorrow, implying a possible reset without explicit statement.
- Expected Category：`reset_hint`
- Review：`Correct`
- Notes：典型 reset-button metaphor，不应升级为 announcement 或 confirmed。

## 2092058556707344708

- 时间（数据库 `created_at`）：`2026-08-25 01:16:43`
- 正文：Tomorrow we will bring back the 5h limit for Plus accounts across ChatGPT Work and Codex. I had mentioned this a while ago, but then postponed it. This is necessary as (a) the 5h limit allows us to smoothen the load on our compute, allowing to keep the plan generous in terms of
- Rule Result：`quota_information`, confidence `0.78`, urgency `unknown`, explicitness `unclear`。Reason：Matched quota or usage-limit terminology without a confirmed reset action.
- AI Result（v2）：`quota_information`, confidence `0.92`, urgency `unknown`, explicitness `explicit`。Reason：The tweet explicitly announces reinstating a 5-hour usage limit for Plus accounts, which is a quota/usage-limit policy change rather than a reset event.
- Final Result：`quota_information`, confidence `0.92`, urgency `unknown`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：The tweet explicitly announces reinstating a 5-hour usage limit for Plus accounts, which is a quota/usage-limit policy change rather than a reset event.
- Expected Category：`quota_information`
- Review：`Correct`
- Notes：明确区分 limit policy change 与 reset event。

## 2091688655828246890

- 时间（数据库 `created_at`）：`2026-08-24 00:46:51`
- 正文：Good Sunday. Reset has been propagated to accounts and we landed some fixes to usage for things mentioned yesterday as issues we found. You should feel a positive difference. More to come tomorrow and will keep communicating.
- Rule Result：`reset_confirmed`, confidence `0.99`, urgency `now`, explicitness `explicit`。Reason：Matched language stating that the reset or limits are complete.
- AI Result：当前 v2 未调用（Rule 已明确）；历史 v1 AI 为 `reset_confirmed`, confidence `0.95`, urgency `now`, explicitness `explicit`。
- Final Result：`reset_confirmed`, confidence `0.99`, urgency `now`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：Matched language stating that the reset or limits are complete.
- Expected Category：`reset_confirmed`
- Review：`Correct`
- Notes：`has been propagated to accounts` 按已应用/完成处理，而不是 hint。

## 2091412393368945027

- 时间（数据库 `created_at`）：`2026-08-23 06:29:05`
- 正文：Reset will land around 14pm PST tomorrow.
- Rule Result：`reset_announcement`, confidence `0.98`, urgency `within_24h`, explicitness `explicit`。Reason：Matched an explicit reset announcement pattern.
- AI Result：当前 v2 未调用（Rule 已明确）；历史 v1 AI 为 `reset_announcement`, confidence `0.98`, urgency `within_3d`, explicitness `explicit`。
- Final Result：`reset_announcement`, confidence `0.98`, urgency `within_24h`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：Matched an explicit reset announcement pattern.
- Expected Category：`reset_announcement`
- Review：`Correct`
- Notes：明确未来时间和 `will land`，不再归入 implicit hint。

## 2091407991736332689

- 时间（数据库 `created_at`）：`2026-08-23 06:11:36`
- 正文：Update on rate limits in Codex. We��ve found (a) some inefficiencies when using images in long sessions with multiple compactions (b) high p95+ usage for Computer History (c) a feature that was meant to generate conversation titles that was draining a bit more usage than
- Rule Result：`quota_information`, confidence `0.94`, urgency `unknown`, explicitness `explicit`。Reason：Matched quota or usage-limit terminology without a confirmed reset action.
- AI Result：当前 v2 未调用（高置信度普通 quota）。
- Final Result：`quota_information`, confidence `0.94`, urgency `unknown`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：Matched quota or usage-limit terminology without a confirmed reset action.
- Expected Category：`quota_information`
- Review：`Correct`
- Notes：普通 rate-limit/usage 优化信息，不提升 Radar 到 Reset 事件状态。

## 2091033630147854385

- 时间（数据库 `created_at`）：`2026-08-22 05:24:01`
- 正文：Update on rate limits in Codex. We do see that for some users the cache hit rate has been worse this week than the stable state the weeks before. This could explain that usage is draining somewhat faster for those users as hitting the cache consistently is an important component
- Rule Result：`quota_information`, confidence `0.94`, urgency `unknown`, explicitness `explicit`。Reason：Matched quota or usage-limit terminology without a confirmed reset action.
- AI Result：当前 v2 未调用（高置信度普通 quota）。
- Final Result：`quota_information`, confidence `0.94`, urgency `unknown`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：Matched quota or usage-limit terminology without a confirmed reset action.
- Expected Category：`quota_information`
- Review：`Correct`
- Notes：缓存命中率和 usage 消耗解释，不是 reset event。

## 2090964822422949999

- 时间（数据库 `created_at`）：`2026-08-22 00:50:36`
- 正文：The banked reset has landed, I repeat, the banked reset has landed. Have an amazing weekend.
- Rule Result：`reset_confirmed`, confidence `0.99`, urgency `now`, explicitness `explicit`。Reason：Matched language stating that the reset or limits are complete.
- AI Result：当前 v2 未调用（Rule 已明确）；历史 v1 AI 为 `reset_confirmed`, confidence `0.95`, urgency `now`, explicitness `explicit`。
- Final Result：`reset_confirmed`, confidence `0.99`, urgency `now`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：Matched language stating that the reset or limits are complete.
- Expected Category：`reset_confirmed`
- Review：`Correct`
- Notes：`banked reset has landed` 已按 confirmed 处理。

## 2090947196107764189

- 时间（数据库 `created_at`）：`2026-08-21 23:40:34`
- 正文：The banked reset will be there by 8pm PST. For all paid users of ChatGPT Work and Codex. Do with this information what you may.
- Rule Result：`reset_announcement`, confidence `0.98`, urgency `unknown`, explicitness `explicit`。Reason：Matched an explicit reset announcement pattern.
- AI Result：当前 v2 未调用（Rule 已明确）；历史 v1 AI 为 `reset_announcement`, confidence `0.95`, urgency `within_6h`, explicitness `explicit`。
- Final Result：`reset_announcement`, confidence `0.98`, urgency `unknown`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：Matched an explicit reset announcement pattern.
- Expected Category：`reset_announcement`
- Review：`Correct`
- Notes：指定发放时间的 banked reset 是明确 announcement。

## 2090766694897619318

- 时间（数据库 `created_at`）：`2026-08-21 11:43:19`
- 正文：It's me again. I come bearing great news. First of all, we have hit 20M active users for Codex some time this week. Second of all, this is cause for celebration and during the day we will credit every Codex and ChatGPT Work user with a BANKED reset that you can use at your own
- Rule Result：`reset_announcement`, confidence `0.98`, urgency `unknown`, explicitness `explicit`。Reason：Matched an explicit reset announcement pattern.
- AI Result：当前 v2 未调用（Rule 已明确）；历史 v1 AI 为 `reset_announcement`, confidence `0.90`, urgency `within_24h`, explicitness `explicit`。
- Final Result：`reset_announcement`, confidence `0.98`, urgency `unknown`, explicitness `explicit`。Pending `false`，Conflict `false`。Reason：Matched an explicit reset announcement pattern.
- Expected Category：`reset_announcement`
- Review：`Correct`
- Notes：`will credit ... with a BANKED reset` 是未来发放计划，不能因为同时出现 Codex/usage 语义而降为 quota。

## 复核汇总

- 当前高价值记录：12 条
- `Correct`：12 条（含用户已确认的 `2093573991965557198`）
- `Uncertain`：0 条
- `Incorrect`：0 条
- 当前真实数据没有 `reset_in_progress` 或 `reset_denial`；对应边界由 Gold Set 中的手工样本覆盖。
