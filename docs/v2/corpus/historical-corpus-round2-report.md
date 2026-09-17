# Codex Reset Radar V2 — historical corpus round 2 report

## Outcome

Round 2 is implemented and applied to the real V2 database. It reads the requested sources, stores
separate source/local verification states, preserves conflicts, gives every acquired claim a disposition,
creates seven reviewed 2025 Full Reset events, adds twelve reviewed cases, runs a bounded historical
analysis batch, and performs exactly one controlled current Judge update.

Corpus version: `corpus-round2-20260917-994180c769c7@2026-09-17T06:40:00Z`.

No historical row entered the realtime queue. The import triggered zero per-post Judge calls, zero
notifications, and zero Git operations.

## 1. Sources and fixed versions

| Source | Actual records obtained | Fixed version / snapshot |
|---|---:|---|
| `liyoungc/codex-reset-index` | 39 reset claims + 10 signals | Commit `7a494b8b…`; blobs `e3e7ac7…`, `2c02e5f…` |
| `codex-resets.com` | 53 unique Tweet entries | Homepage snapshot at 06:53 UTC, SHA-256 `274a59d…` |
| Gussuri | 31 history rows | Commit `4d687459…`; `resetHistory.ts` blob `4cfba9c…` |
| `codex-reset.com/api/feed` | 27 tweets + 10 context rows + 59 event rows | `fetched_at=2026-09-17T06:52:00Z`, snapshot `68ebaa3…` |
| `codexreset.co` | 8 unique IDs across 3 monthly pages | Page hashes `1b25bac…`, `bdb5378…`, `df20de6…` |
| `codex-reset.today` | 56 unique rows over 3 pages; 54 valid Tibo `x_post` copies | Page hashes `373e2f8…`, `66c0726…`, `7974a45…` |

The importer received 198 post-evidence records and 256 source claims. Full details are in
[third-party-source-verification.md](third-party-source-verification.md).

## 2. Import, deduplication, conflicts, and rejection

First real pass across the 198 post-evidence records:

- new canonical posts: 20;
- metadata/evidence enrichment: 7;
- same canonical content: 50;
- different source text retained as conflict evidence: 121;
- failed imports: 0.

A follow-up precedence correction upgraded the seven 2025 seeds from earlier excerpts to complete
cross-source English. It added no post/evidence/event row. The final same-batch rerun path is idempotent:
stable keys keep 366 posts, 279 evidence rows, 12 events, 262 dispositions, and 20 cases. The isolated
database was also rerun with no count growth.

Eleven claims were explicitly rejected/excluded as event evidence: four ordinary references, two
synthetic aggregates, two non-Tibo authors, and three product/quota/policy rows. “Conflict” means a
preserved source-text difference, not a failed import and not another Reset.

## 3. Seven 2025 clues

All seven seeds have a concrete disposition and formal Full Reset event. They are events #7–#13 at:

1. `1968163721034994139` — 2025-09-17 04:02:52.465Z.
2. `1986166501435711936` — 2025-11-05 20:19:29.788Z.
3. `1992370994028388670` — 2025-11-22 23:13:56.096Z.
4. `1995988609896513743` — 2025-12-02 22:49:02.931Z, stored as propagating.
5. `2001114683047317723` — 2025-12-17 02:18:14.008Z.
6. `2002137269134819610` — 2025-12-19 22:01:37.530Z.
7. `2004100061933064395` — 2025-12-25 08:01:03.800Z; temporary 2x is a secondary effect.

These use announcement-post time as a proxy. Date conflicts remain in source evidence. The current
cycle did not move: the latest Full Reset is still `2098685367058612394` at 2026-09-12 08:09:17Z.

## 4. Formal and Special events

Added: seven Full Reset events. Added: zero Special Reset events. Existing Banked event remains the
only formal Special event. Eighteen source claims are retained with Special semantics but need stronger
completion evidence before promotion. Full+Banked source posts have two effect dispositions and never
create two Full cycles.

The DeepSeek historical analysis labelled two incident-compensation seeds as Special, but that model
output is stored as analysis only and does not overwrite the reviewed Full event type. Incident reason
is not itself a Special delivery mechanism.

## 5. What remains unconfirmed

- `NEEDS_ORIGINAL`: 147 disposition rows.
- `FUTURE_ANNOUNCEMENT`: 36; later completion/scope still needed.
- `SPECIAL_EVENT`: 18 source claims; independent delivery/completion evidence still needed.
- `NEEDS_CONTEXT`: 1; parent body missing.
- Direct X page re-check: unavailable because the Edge automation provider failed repeatedly.

Zero current candidates is therefore not presented as “nothing remains”. The disposition table is the
auditable unresolved queue.

## 6. English originals and parent context

Seven 2025 seed records were actually upgraded to complete English and marked
`cross_source_correlated`. No Chinese-to-English back-translation was created. The feed supplied 16
parent Tweet IDs, but zero parent bodies; context stays `parent_id_only` and no report claims complete
reply context.

## 7. Analysis backlog and budget

A bounded historical-only batch made 14 DeepSeek calls (`v2-post-semantics-2`), all successful:

- seven 2025 seed posts;
- anti-signal `2077212009071075330`;
- advance hints `2055446089957036402` and `2060964284117782996`;
- dual-effect posts `2071740419030053227` and `2075641131002700120`;
- two English records previously marked failed.

Final post states: 57 `COMPLETED`, 5 `FAILED`, 53 `HISTORICAL_UNANALYSED`, and 251 `PENDING`.
Realtime processing jobs pending: 0. “Queue empty” and “all stored posts analysed” remain separate facts.
The remaining general backlog was not sent to the model because of the bounded-call requirement.

## 8. Historical cases

Twelve cases were added, 20 total:

- advance judgement: `hist-r2-2055446089957036402`, `hist-r2-2060964284117782996`;
- completion/event recognition only: seven 2025 seed cases;
- Special/dual-effect recognition: `hist-r2-2071740419030053227`;
- completed-now plus future-later split: `hist-r2-2075641131002700120`;
- negative/false-positive context: `hist-r2-2077212009071075330`.

The seven same-post completion cases are explicitly tagged `event_recognition_only` and are not counted
as advance-warning successes. No unknown outcome is converted into a negative sample.

## 9. Controlled Judge result

Exactly one controlled call created judgement #91:

- corpus version: `corpus-round2-20260917-994180c769c7@2026-09-17T06:40:00Z`;
- result: `GREEN`; horizons `GREEN / GREEN / YELLOW`;
- data health: `HEALTHY`;
- new round-2 case actually used: `hist-r2-2071740419030053227`;
- other cases: `hist-2099393115241300166`, `hist-2098300998968357218`,
  `hist-2093811840258293947`, `hist-2093573991965557198`, `hist-2090947196107764189`;
- notifications sent: 0.

The result need not change color; the acceptance condition is attributable use of the new corpus.

## 10. Database, services, tests, and worktree

- Database backup before round-2 writes:
  `runtime/data/codex-reset-radar-v2.pre-corpus-round2-20260917-105000.db`.
- Schema version: 5; `quick_check=ok`; foreign-key violations: 0.
- Final database: 366 posts, 279 evidence rows, 262 dispositions, 20 cases, 12 events, 91 judgements.
- Backend `2.0.0-alpha.2`: healthy; Profile, Replies, Search: healthy.
- Web and Vite API proxy: HTTP 200 and reading local V2 API.
- Backend test suite: 30 passed.
- Web: 6 tests passed; TypeScript check and Vite production build passed.
- Collector Extension: 12 tests passed; typecheck and Vite build passed.
- Import snapshot directory remains ignored; credentials/logs/SQLite remain local.
- No commit or push was performed. Existing uncommitted Alpha 2 and corpus work was preserved.

Detailed disposition and coverage reports are
[historical-evidence-disposition.md](historical-evidence-disposition.md) and
[corpus-coverage.md](corpus-coverage.md).
