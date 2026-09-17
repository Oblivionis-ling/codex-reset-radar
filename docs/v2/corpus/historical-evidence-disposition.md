# Historical evidence disposition

Round 2 persists every acquired event/signal claim in `historical_event_dispositions`. The table now
contains 262 dispositions derived from 256 source rows. The difference is intentional: a claim with
Full + Banked effects, or one completed Reset plus another planned Reset, is split by effect.

## Disposition totals

| Disposition | Count | Meaning |
|---|---:|---|
| `NEW_FORMAL_EVENT` | 7 | Reviewed 2025 Full Reset created |
| `LINKED_EXISTING_EVENT` | 13 | Tweet ID already belongs to a formal V2 event |
| `DUPLICATE_SOURCE` | 28 | Another source copy of the same upstream event; not an independent Reset |
| `FUTURE_ANNOUNCEMENT` | 36 | Future/still-propagating language; not treated as completed |
| `SPECIAL_EVENT` | 18 | Banked/reset-card or other Special effect; does not advance Full Reset cycle |
| `NEEDS_ORIGINAL` | 147 | Reset-like source claim still lacks sufficient primary/independent evidence |
| `NEEDS_CONTEXT` | 1 | Parent/reply context is specifically missing |
| `NEGATIVE_OR_DELAY_CONTEXT` | 1 | Negative present-time statement retained without inventing a 72-hour negative window |
| `NON_RESET_PRODUCT_CHANGE` | 3 | Product, quota, or policy change is not a Reset completion |
| `EXCLUDED_REFERENCE` | 4 | Ordinary/reference cycle is not an additional Reset |
| `EXCLUDED_SYNTHETIC` | 2 | `observed-*`/public-source aggregate is not an original post |
| `REJECTED_NON_TIBO_AUTHOR` | 2 | Link author is not `@thsottiaux` |

The source-level counts are 52 (`liyoungc`), 54 (`codex-resets.com`), 31 (Gussuri), 60
(`codex-reset.com`), 8 (`codexreset.co`), and 57 (`codex-reset.today`). These are disposition rows,
not independent Reset counts.

## Seven 2025 seeds

| Tweet ID | Reviewed time basis | Disposition | Result and boundary |
|---|---|---|---|
| `1968163721034994139` | Snowflake `2025-09-17T04:02:52.465Z` | Full Reset event #7 | Full text says everyone's gpt-5-codex limits were reset; source date conflict `09-16` vs `09-17` retained |
| `1986166501435711936` | Snowflake `2025-11-05T20:19:29.788Z` | Full Reset event #8 | Outage resolved and rate limits reset; incident reason does not make it a Special mechanism |
| `1992370994028388670` | Snowflake `2025-11-22T23:13:56.096Z` | Full Reset event #9 | Reset for all Codex users after US latency; incident compensation is still a Full Reset |
| `1995988609896513743` | Snowflake `2025-12-02T22:49:02.931Z` | Full Reset event #10 | Already reset, with ten-minute propagation window; stored as `propagating`, not future-only |
| `2001114683047317723` | Snowflake `2025-12-17T02:18:14.008Z` | Full Reset event #11 | Everyone's usage limits reset; `12-16`/`12-17` display-date conflict retained |
| `2002137269134819610` | Snowflake `2025-12-19T22:01:37.530Z` | Full Reset event #12 | Usage-accounting rewrite and reset in the process |
| `2004100061933064395` | Snowflake `2025-12-25T08:01:03.800Z` | Full Reset event #13 | One Full Reset plus temporary 2x usage through Jan 1; boost is a secondary effect, not a second cycle |

Each event uses `announcement_post_time_proxy`. The direct X page could not be re-opened by automation,
so provenance explicitly says `cross_source_correlated`, not direct verification.

## Required semantic boundaries

- Source `confirmed` plus future tense becomes `FUTURE_ANNOUNCEMENT`, not completed.
- `auto-confirm-*`, `observed-*`, and `public_source` aggregate rows are excluded from posts/events/replay evidence.
- No missing timestamp is materialized as 12:00 or 00:00.
- Four Gussuri `reference` effects are excluded from Full Reset history.
- Two non-Tibo authors are rejected for Tibo attribution.
- Product/quota post `1986863197803192782` is explicitly `NON_RESET_PRODUCT_CHANGE`.
- `hard_reset_plus_banked` produces separate Full and Banked dispositions; only one Full cycle can result.
- Tweet `2075641131002700120` has separate completed and future dispositions.
- Multi-site copies of one Tweet produce duplicate-source rows, not independent confirmations.
- Feed parent authors remain parent metadata and are not merged into Tibo text.
- Historical inserts rebuild cycles in event-time order; the open cycle still begins at
  `2026-09-12T08:09:17Z` and no negative interval exists.
- `2077212009071075330` is a present-time anti-signal only; no 72-hour no-Reset claim was created.

## Formal events versus unresolved material

Round 2 adds seven Full Reset events, zero Special events, and zero Dashboard-facing current candidates.
The zero candidate count no longer hides source work: all 262 claims are queryable with a reason and a
missing-evidence field. The 147 `NEEDS_ORIGINAL`, 36 `FUTURE_ANNOUNCEMENT`, 18 `SPECIAL_EVENT`, and one
`NEEDS_CONTEXT` row remain explicit verification work rather than silently disappearing.
