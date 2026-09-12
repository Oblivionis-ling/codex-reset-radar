# Phase B classification report

报告时间：2026-08-28

## 实现内容

- Ordered local Rule Classifier with denial-first priority.
- Configurable DeepSeek Provider using `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_PROMPT_VERSION`.
- Pydantic validation for category, confidence, urgency, explicitness, and reason.
- Timeout/HTTP/schema failure boundary with rule fallback and `classification_pending`.
- SQLite Context Engine with parent Tweet, up to 10 related Tweet, last confirmed reset, and recent status events.
- Audited Resolver retaining `rule`, `ai` (when available), and `final` classifications.
- Radar State engine with expiry and `radar_state_history`.
- APIs: `GET /api/radar`, `GET /api/tweets/{tweet_id}/classification`, `POST /api/tweets/{tweet_id}/reclassify`, and `POST /api/classify/backfill`.
- New Tweet ingestion schedules classification without blocking the collector response.

## Automated tests

- Backend total: `12 passed`.
- Includes rule priority, denial protection, hints, context selection, Radar expiry, Mock Provider audit rows, and AI failure fallback.
- Includes API coverage for classification history and Radar state.
- Phase A tests remain included and pass.
- Extension tests and TypeScript build were not changed by Phase B and remain green from the previous verification.

## Real Tweet corpus

The current SQLite corpus contains 46 real Tweets. All 46 were classified once through the Rule → Final pipeline.

| 指标 | 数量 |
|---|---:|
| 总 Tweet 数 | 46 |
| Rule 直接完成 | 43 |
| 需要 AI 语义判断 | 3 |
| DeepSeek 实际调用 | 0 |
| DeepSeek 成功 | 0 |
| DeepSeek API 失败 | 0 |
| Pending（未配置 API Key） | 3 |
| Rule/AI 冲突 | 0 |

本机当前未配置 `DEEPSEEK_API_KEY`，因此没有向外部 AI 服务发送请求。3 条需要语义判断的 Tweet 保留了 Rule 结果，并在 Final 记录中标记 `classification_pending=true`。配置 Key 后可以使用 `POST /api/classify/backfill?force=true` 重跑。

## Final 分类分布

| 类别 | 数量 |
|---|---:|
| unrelated | 40 |
| codex_related | 5 |
| quota_information | 0 |
| reset_hint | 1 |
| reset_announcement | 0 |
| reset_in_progress | 0 |
| reset_confirmed | 0 |
| reset_denial | 0 |

## Radar State

当前状态为：

```text
WATCH
confidence: 0.72
urgency: within_24h
trigger_tweet_id: 2092862554632826968
```

触发原因是检测到 reset-button / tomorrow / dust 组合暗示。由于尚未调用 DeepSeek，这个结果只能视为 Rule fallback，不能当作已经确认的 Reset 预测。

## 高价值 Signal 人工审查清单

### reset_hint

| Tweet 时间 | Tweet | Rule | AI | Final | Confidence | Urgency |
|---|---|---|---|---|---:|---|
| 2026-08-27 14:31 +08:00 | A good thing about having aged is that I feel that it’s been 20 years since I’ve pressed the reset button. Intrigued to see if I can find it tomorrow and dust it up | reset_hint | pending | reset_hint | 0.72 | within_24h |

Reason：Matched a known reset-button or time-linked hint pattern; semantic review is required. AI unavailable; rule fallback retained.

### Other high-value categories

当前 46 条 Tweet 中没有 `reset_announcement`、`reset_in_progress`、`reset_confirmed` 或 `reset_denial`。

## 当前已知问题

1. DeepSeek live classification 尚未执行，原因是本机没有 `DEEPSEEK_API_KEY`。
2. 当前 `WATCH` 由 Rule fallback 触发，必须经过 DeepSeek 和人工检查后才可评估。
3. 7 天 Deep Backfill、页面刷新恢复和 Backend 重启恢复仍属于 Deferred Phase A Validation。
4. 本阶段没有发送任何 WxPusher 或 Windows Toast 通知。

本报告是 Phase B 的停止点；等待 API Key 配置和人工复核后，再决定是否进入通知阶段。
