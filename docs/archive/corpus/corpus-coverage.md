# Historical corpus coverage

Coverage means “material actually obtained”, not completeness of X and not probability that no other
Reset occurred. Rows use UTC calendar-month half-open intervals.

## Unique material now represented

| Period | Unique round-2 IDs of interest | What is covered | Known gap |
|---|---:|---|---|
| 2025-09 | 1 | One Full Reset seed, represented by four source observations | No general Tibo timeline; direct X re-check unavailable |
| 2025-10 | 0 | No acquired rows | Absence is unknown, not “no Reset” |
| 2025-11 | 3 | Two Full Reset seeds plus one product/quota post correctly excluded | No complete month archive |
| 2025-12 | 4 | Four Full Reset seeds, including the Full + temporary 2x boundary | No complete month archive |
| 2026-01 to 2026-02 | 0 | No newly acquired source rows | Absence is unknown |
| 2026-03 to 2026-08 | Multiple overlapping source observations | Prior ModelYard/AIPlanWatch material plus the new indexes/API | Sources share upstream X posts and cannot be summed as independent confirmations |
| 2026-09 through acquisition | Current feed plus archive rows | 37 feed text/context rows, 59 feed claims, five API archive posts in month | Rolling feed is not a complete archive; parent text remains missing |

The database has 41 source/month coverage rows. They deliberately count source records, so the four
source observations of the September 2025 seed appear as four coverage records but only one canonical
Tweet/event.

## Current corpus inventory

- Frozen review package: 366 canonical posts, 308 realtime and 58 historical-only.
- Live production at final adjudication: 368 posts, 14 formal events, 13 Full cycles, and 20 cases.
- 279 source-evidence rows from seven post-bearing external sources.
- 262 persisted source-claim dispositions.
- 20 reviewed historical cases.
- The 14 formal events are 13 Full and one Banked Special. E1 is merged into E2 as scope evidence and
  does not increase either event or cycle counts.
- 7 evidence rows are `cross_source_correlated`; 272 are not independently verified.
- 16 parent Tweet IDs were acquired; zero parent bodies were acquired in round 2.

The field-scoped review version is `reviewed-corpus-20260918-v1`. Its 17 substantive adjudication items
are resolved; 10 canonical input-integrity limitations, three human `INSUFFICIENT_INPUT` posts, and one
adjudicated-but-not-event-promotable record remain explicit. These limitations do not reduce the unknown
archive gaps shown above.

The complete source snapshots remain in ignored local storage. Public reports contain counts, fixed
versions, hashes, short evidence descriptions, and boundaries rather than republishing the corpus.
