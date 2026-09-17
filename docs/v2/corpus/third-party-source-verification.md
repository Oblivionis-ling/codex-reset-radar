# Third-party source verification — historical corpus round 2

Checked on 2026-09-17. The final corpus identifier is
`corpus-round2-20260917-994180c769c7@2026-09-17T06:40:00Z`.

This report distinguishes what a source says from what V2 verified locally. A source field such as
`confirmed`, `verified`, `direct`, or `announced` is stored in `source_claimed_status`. The independent
V2 result is stored in `local_verification_status`. The two fields are never inferred from one another.

## Acquired material

| Source | Fixed version / snapshot | Material actually read | Importable post evidence | Event/signal claims | Verification notes |
|---|---|---:|---:|---:|---|
| `liyoungc/codex-reset-index` | Commit `7a494b8b683ab0416b3f0be0148f635482df364c`; blobs `e3e7ac7…` and `2c02e5f…` | `resets.json` 39 events; `signals.json` 10 signals | 49 | 49 | Static JSON only. `confirmed` includes both completed and imminent statements, so it is not mapped to local completion |
| `codex-resets.com` | Homepage snapshot captured 2026-09-17 06:53 UTC; local SHA-256 `274a59d155554bff98a42c4128adb7057e977395662fb228543e0f0555353e56` | 53 unique Tweet links: 50 regular, 3 banked | 53 truncated excerpts | 53 | `/history` is 404; the archive is on the homepage. `data-date` and snippets remain source claims |
| Gussuri `resetHistory.ts` | Commit `4d68745981a0b3436aa981da70a93b83b4fa9d8c`; blob `4cfba9c…` | 31 JSON-compatible history rows | 0 | 31 | Parsed with `json.JSONDecoder.raw_decode`; TypeScript was not executed and `eval` was not used |
| `codex-reset.com/api/feed` | Feed snapshot `fetched_at=2026-09-17T06:52:00Z`; local SHA-256 `68ebaa3fae2485f46525eb9213cec84f9a34600f589e16b02aed089eddfb7db0` | 27 tweets, 10 radar-context rows, 59 event rows | 37 unique text rows | 59 | 16 parent Tweet IDs were retained; no parent text was obtained, so context is not marked complete |
| `codexreset.co` | Three HTML/JSON-LD snapshots: `2025-09` `1b25bac…`, `2025-11` `bdb5378…`, `2025-12` `df20de6…` | 8 unique Tweet IDs | 5 non-generic text copies | 8 | Seven 2025 seeds plus product/quota post `1986863197803192782`; generic site prose is not stored as Tibo original text |
| `codex-reset.today/api/v1/resets` | Three cursor pages captured at low rate; page SHA-256 values `373e2f8…`, `66c0726…`, `7974a45…` | 56 unique API rows | 54 numeric `x_post` rows attributed to `thsottiaux` | 56 | Two `public_source`/`observed-*` rows were excluded as synthetic. The documented public endpoint works, while `robots.txt` says `Disallow: /api/`; only the requested bounded three pages were read |

The fixed Git object sizes are 25,365 bytes (`resets.json`), 4,579 bytes (`signals.json`), and
38,846 bytes (`resetHistory.ts`). The locally ignored snapshot directory is
`data/corpus/imports/historical-round2-20260917/`. Complete pages and copied text are not committed.

## Author, text, time, and context rules

- Numeric Tweet IDs and original X links are retained independently from site summaries.
- The feed's `replying_to` handle is metadata about the parent target; it is never concatenated into
  Tibo's text or treated as the parent author.
- Gussuri links to `dkundel` and `bossnayamoss` are recorded as non-Tibo evidence and rejected for
  Tibo-language/event attribution.
- Reliable English is never replaced by a translation. Seven 2025 seeds were upgraded from excerpts
  to complete English copies only after Tweet ID, author/link identity, snowflake time, and multiple
  archive copies correlated.
- Source date strings, Tweet-snowflake times, and source event times remain separate. In particular,
  `1968163721034994139` retains the `2025-09-16` versus `2025-09-17` source-date conflict, and
  `2001114683047317723` retains `2025-12-16` versus `2025-12-17`.
- Missing event time is not filled with noon or midnight. Formal seed event time is explicitly an
  `announcement_post_time_proxy`, not an asserted backend execution timestamp.
- A parent Tweet ID without parent text is `parent_id_only`, not complete context.

## Direct-X verification boundary

The authorized Edge session was selected for a read-only check, but the browser automation provider
failed repeatedly with `nodeRepl.fetch request failed`, including after a runtime reset. No Cookie was
read or copied, no CAPTCHA/login barrier was bypassed, and no X interaction was performed. Therefore:

- none of the round-2 rows is labelled `direct_original_verified`;
- seven seeds are labelled `cross_source_correlated`;
- the remaining 272 evidence rows are `not_independently_verified`.

This is an explicit remaining blind spot, not a hidden PASS.
