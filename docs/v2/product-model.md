# V2 Product Model

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

The human-adjudicated policy (2026-09-18 local time) is that the main Action Level,
24/48/72-hour horizons and estimated window concern the next **Full Reset only**.
Issuing a reset card is separate information: its certainty or scheduled arrival must
not, by itself, raise the main level. A mixed Full + Banked post still contributes its
Full effect. This is a judgement boundary, not a forced GREEN rule or a lexical score.
Special events keep their independent record/presentation and never open Full cycles.

The current pipeline implements the DeepSeek Judge using bounded, attributable evidence. The model performs semantic judgement; code validates output enums, evidence IDs, time fields, current-cycle association, and cumulative 24/48/72-hour ordering. It is not a hand-written keyword score and this project does not train an ML model.

An invalid, expired or stale-data result produces a white current action area with an explicit
reason. A last-known result may be shown separately, never relabelled fresh after a heartbeat.
Genuine model UNKNOWN is distinguished from a failed validation or request.

Purple pending Banked/reset-card announcements are labelled “待核验 / 尚未确认发放”.
They are not completed special events, do not change Full cycles and do not imply personal receipt.
An ambiguous date remains unknown; stale collection also makes announcements last-known information.

The public contract intentionally contains no confidence percentage, probability badge, or hidden chain-of-thought. Persisted analysis contains structured evidence and concise summaries only.
