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

Alpha 1 defines contracts and lifecycle rules only. A later DeepSeek Judge will make semantic judgements from bounded, attributable evidence. It will not be a hand-written keyword score and this project will not train an ML model in the V2 Foundation phase.

The public contract intentionally contains no confidence percentage, probability badge, or hidden chain-of-thought. Persisted analysis contains structured evidence and concise summaries only.
