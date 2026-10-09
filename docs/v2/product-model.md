# V2 Product Model

Historical engineering status only: `READY_FOR_CONTROLLED_MODEL_TEST` was the result for frozen
code manifest `1c7a29ad…` (Backend 318/0/0, Web 17, Collector 18, type checks, builds, empty-DB
API/CLI, sample verification and isolated UI review). It is not acceptance of later changes.
Model-semantics status: the prior v9 11-HTTP controlled result is `PARTIAL`; the v10 time-contract
retest has not been authorized and remains `NOT_EVALUATED`. Actual accuracy remains `NOT_EVALUATED`;
deployment remains `NOT_DEPLOYED`.
This branch depends on OPEN [Ledger PR #10](https://github.com/Oblivionis-ling/codex-reset-radar/pull/10).
Production remains Alpha5 / main `1e865c37d1643f429162adeb0fab61bb7371a47b`. See the
[single report](../maintenance/prediction-three-lines-v1-report.md) for scope and evidence.

## Product question

Codex Reset Radar exists to answer: **Is the next Codex Reset approaching, and what should the user do now?** It is not primarily a Dashboard project and it does not treat operational telemetry as product content.

## Action levels

| Level | User meaning |
|---|---|
| `GREEN` | Use Codex normally. |
| `YELLOW` | Start paying attention; modestly increase usage if useful. |
| `ORANGE` | A Reset appears relatively close; actively use the remaining allowance. |
| `RED` | Strong near-term Reset signals; use the remaining allowance promptly. |

`UNKNOWN` is displayed as white. It is not a fifth risk level and must not be converted to `GREEN`. It means the system lacks enough reliable data to judge.

## Horizons

Every judgement contains independently valid `24H`, `48H`, and `72H` horizon values. Each accepts only `GREEN`, `YELLOW`, `ORANGE`, `RED`, or `UNKNOWN`.

## Reset lifecycle

A `FULL_RESET` is a verified historical event. It closes the previous Reset cycle, opens a new cycle, and updates `last_full_reset`. It is not a Dashboard action level and must not leave the home page in a persistent `CONFIRMED` or `RED` state.

A `SPECIAL_RESET` does not change `last_full_reset` or the current Full Reset cycle. Its subtype may be `PARTIAL`, `BANKED`, `RESET_CARD`, `STAGED`, `EXTRA_CREDIT`, or `OTHER`; every subtype uses the same `PURPLE` presentation with explanatory text.

## Judge boundary

The current implementation follows the human-adjudicated policy (2026-09-18 local time): the main Action Level,
24/48/72-hour horizons and estimated window concern the next **Full Reset only**.
Issuing a reset card is separate information: its certainty or scheduled arrival must
not, by itself, raise the main level. A mixed Full + Banked post still contributes its
Full effect. This is a judgement boundary, not a forced GREEN rule or a lexical score.
Special events keep their independent record/presentation and never open Full cycles.

The confirmed product target is separate date predictions for actual Extra Full execution and Banked issuance start, alongside the user Normal weekly baseline. The isolated branch implements these targets, Ledger history, scoring and the minimum UI; final offline integration acceptance is complete. The production Judge date estimate remains Full-only. [CRR 日期预测与复盘规范](prediction-and-review-spec.md) remains the single source for target, time and evaluation semantics.

The current pipeline implements the DeepSeek Judge using bounded, attributable evidence. The model performs semantic judgement; code validates output enums, evidence IDs, time fields, current-cycle association, and cumulative 24/48/72-hour ordering. It is not a hand-written keyword score and this project does not train an ML model.

An invalid, expired or stale-data result produces a white current action area with an explicit
reason. A last-known result may be shown separately, never relabelled fresh after a heartbeat.
Genuine model UNKNOWN is distinguished from a failed validation or request.

Purple pending Banked/reset-card announcements are labelled “待核验 / 尚未确认发放”.
They are not completed special events, do not change Full cycles and do not imply personal receipt.
An ambiguous date remains unknown; stale collection also makes announcements last-known information.

The public contract intentionally contains no confidence percentage, probability badge, or hidden chain-of-thought. Persisted analysis contains structured evidence and concise summaries only.

## Development presentation boundary

The development three-line read view and minimum history entry use the additive
[API contract](api-contract.md#three-line-read-extension-development-contract). The parent Codex
agent (Sol) visually reviewed an isolated API/Web clone using the formal06 fixture; this is not
human-user acceptance, and the screenshot remained in the parent tool output rather than a saved
file. The review observed the following distinctions:

| Display data | Required product state |
| --- | --- |
| Accepted target response explicitly says UNKNOWN | Show the target's unknown time and reason. |
| Legacy/unsupported/missing target or history | Explain compatibility absence or rejection; do not imply the old model answered UNKNOWN. |
| Rejected target or failed run | Preserve the failure reason independently from another accepted target. |
| Expired or stale record | Label historical availability and exclude it from current action advice. |
| Normal reference | Retain its separate reference/source label and never include it in prediction accuracy. |

Dates, precision, original relative expression and source type agreed with the API in the reviewed
fixture. It showed seven history items; question revisions 1/3/5 and output revisions 1/4/7.
Normal showed only the known start with its legacy proxy/precision limits, Banked used purple, and
STALE data displayed UNKNOWN with a last-known warning rather than current advice. The UI fixture
was formal06, not the final formal07 scoring sample. The isolated services were stopped after review.
The existing Full action levels and uniform purple Banked presentation remain the confirmed policy.
