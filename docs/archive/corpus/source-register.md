# Historical Corpus Source Register

Updated 2026-09-18. Full copied material stays in ignored local storage. Source labels are claims, not
V2 verification outcomes.

The final field-scoped review overlay is `reviewed-corpus-20260918-v1`. It changes no source ranking and
does not turn third-party claims into primary verification. E1 (`2091709346371838240`) is now linked as
supplementary Business-scope evidence to the existing E2 Full Reset; it remains one event, not an
additional source confirmation or cycle.

| Source ID | Entry / fixed version | Material obtained | Time represented | V2 use and limitation |
|---|---|---|---|---|
| `v2-live-collector` | Local V2 SQLite and authorized Edge collector | Realtime Tibo posts and collector metadata | Existing live window | Highest-precedence local capture; private, not re-exported |
| `v1-read-only` | `backend/data/radar.db` | Legacy migration comparison only | V1 window | Never reopened as active DB |
| `modelyard-public-events` | <https://tibo.modelyard.dev/> | 35 rows labelled direct by source | 2026-08 to 2026-09 | Source `DIRECT_VERIFIED` remains a source claim |
| `aiplanwatch-reset-history` | <https://codex-reset.aiplanwatch.com/history> | 46 quoted rows | 2026-03 to 2026-09 | Candidate discovery; 14 excerpts may be truncated |
| `liyoungc-codex-reset-index` | Commit `7a494b8b683ab0416b3f0be0148f635482df364c` | 39 reset rows + 10 signals | 2025-09 to 2026-07 | Fixed JSON; `confirmed` can mean complete or imminent |
| `codex-resets-calendar` | <https://codex-resets.com/> snapshot 2026-09-17 06:53 UTC | 53 unique Tweet entries | 2025-09 to 2026-09 | Truncated snippets/date/type claims; homepage is the archive |
| `gussuri-reset-observatory-round2` | Commit `4d68745981a0b3436aa981da70a93b83b4fa9d8c`, blob `4cfba9c…` | 31 history claims | Source-defined historical window | Static JSON decode only; references, profile-only links and non-Tibo authors are not promoted |
| `codex-reset-feed` | <https://codex-reset.com/api/feed>, `fetched_at=2026-09-17T06:52:00Z` | 27 tweets, 10 context rows, 59 event claims | 2026-09 rolling feed | Parent IDs retained separately; parent bodies not obtained |
| `codexreset-monthly-2025` | `/en/history/2025-09`, `2025-11`, `2025-12` | 8 unique IDs | Selected 2025 months | JSON-LD only; generic site prose is not Tibo original text |
| `codex-reset-today-api` | <https://codex-reset.today/api/v1/resets>, bounded 3 pages | 56 rows; 54 valid Tibo `x_post` copies | 2025-09 to 2026-09 | Documented public API works, while robots disallows `/api/`; no broad crawl; two synthetic rows rejected |
| `x-original` | `https://x.com/thsottiaux/status/<id>` | Primary source when actually readable | Varies | Direct check failed this run because the Edge automation provider was unavailable; no Cookie or login bypass used |

## Source and local status

`post_source_evidence.source_claimed_status` records the third party's words. Examples include
`confirmed`, `announced`, `expected`, `verified_archive_listing`, `regular`, `banked`, and Gussuri's
`confirmed_global`/`reference`.

`post_source_evidence.local_verification_status` records V2's result:

- `direct_original_verified`: only an actually checked primary original; none added in round 2;
- `cross_source_correlated`: seven 2025 seeds with full English, matching Tweet identity/time and multiple copies;
- `not_independently_verified`: all remaining source evidence.

The compatibility `verification_status` field remains for existing APIs and ranking; it does not replace
the two explicit fields above.

## Source precedence

1. Existing directly captured English original or an actually readable X post.
2. Complete English that is cross-source correlated by Tweet ID, author/link identity, and snowflake time.
3. A source-labelled direct copy.
4. A third-party quote with Tweet ID and original link.
5. A truncated excerpt, translation, site summary, or classification claim.

A lower-ranked source never overwrites reliable English. Conflicting text and dates remain separate
evidence rows. Multiple sites copying one upstream post do not increase an independent-confirmation count.

## Reuse and access limits

Public availability, repository licensing, and `robots.txt` do not automatically grant redistribution
rights for copied X content. Network reads were bounded by page count, response size, retries, and delays.
No paywall, CAPTCHA, rate limit, or permission barrier was bypassed. Complete snapshots remain under
`data/corpus/imports/`, which Git ignores.
