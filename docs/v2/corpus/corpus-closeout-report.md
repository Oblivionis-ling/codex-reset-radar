# Codex Reset Radar V2 — corpus and program cross-check closeout

## Closeout status

**CLOSED_WITH_DECLARED_LIMITATIONS**

The corpus-standardization and development-time model cross-check phase is closed. The final product
program reproduced all fourteen human-approved Judge fields, content with unresolved body, author, or
context limitations is blocked from unsafe downstream use, the release regression passed, and the same
code is running against the retained production database. The remaining limitations are preserved as
archive-quality constraints; they are not silently treated as verified facts.

This closeout does not claim that every historical English original was recovered, that every archived
post is analysis-complete, or that a language model can never make a future error. It establishes that
the known limitations are explicit and that the current product does not use them as formal event or
trusted forecast evidence.

## A. Final version and scope

| Item | Accepted value |
|---|---|
| Application | `2.0.0-alpha.4` |
| Release implementation commit | `68daf680cac579d0ef23e6a8e4d2e5598c4e23ce` |
| Main merge commit | `a9f811b628461c362b5004ec8d3d936549ab8513` |
| Pull request | `#4` |
| Release tag | `v2.0.0-alpha.4` |
| Remote tag object | `e7e97307bb26749a7e8eb1457fd6c8ee36418d56` |
| Tag target | `a9f811b628461c362b5004ec8d3d936549ab8513` |
| Corpus standard | `crr-corpus-v1` |
| Reviewed corpus | `reviewed-corpus-20260918-v1` |
| Frozen package | 366 posts, 14 events, 20 cases, 705 review results, 104 human decisions |
| Review-package generated at | `2026-09-18T03:17:09.087663Z` |
| Review-package manifest SHA-256 | `8e07341d671afd7817b5555f17d904a2ff96fe1d822e4d3ba69f2e24ac9f90eb` |
| Analysis Prompt | `v2-post-semantics-8` |
| Translation Prompt | `v2-zh-translation-1` |
| Judge Prompt | `v2-reset-judge-6` |

The original reviewed package remains unchanged and its manifest file list, byte lengths, and SHA-256
values were revalidated before this work. Human approval for J1-J14 remains field-scoped to
`action_level`, `horizon_24h`, `horizon_48h`, and `horizon_72h`; reasons, evidence lists, estimated times,
and complete Judge cards were not retroactively marked human-approved.

The full 366-post replay used Analysis `v2-post-semantics-5`. The final closeout database overlays the
eleven accepted, targeted Analysis `v2-post-semantics-8` results on that replay. This is not described as
a full-corpus v8 rerun. No indiscriminate 366-post paid replay was performed during closeout.

## B. Final J1-J14 comparison

All fourteen final v6 rows below were produced by the current product Judge path with a fresh real model
request. None was copied from the GPT reference or manually inserted into `radar_judgements`.

| Window | `as_of` (UTC) | Human-approved action / 24h / 48h / 72h | Final program | Result | Evidence |
|---|---|---|---|---|---|
| J1 | 2026-08-27 12:00 | ORANGE / ORANGE / RED / RED | ORANGE / ORANGE / RED / RED | Match | v6 real request; context `08a05f3b…` |
| J2 | 2026-08-27 17:00 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `67b5e4ac…` |
| J3 | 2026-08-29 12:00 | ORANGE / ORANGE / RED / RED | ORANGE / ORANGE / RED / RED | Match | v6 real request; context `1c4f04ef…` |
| J4 | 2026-08-29 21:10 | GREEN / GREEN / YELLOW / YELLOW | GREEN / GREEN / YELLOW / YELLOW | Match | v6 real request; context `660226d5…` |
| J5 | 2026-08-30 00:00 | YELLOW / YELLOW / ORANGE / ORANGE | YELLOW / YELLOW / ORANGE / ORANGE | Match | v6 real request; context `6f2d1f90…` |
| J6 | 2026-08-31 03:00 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `d3bf9c40…` |
| J7 | 2026-09-03 23:30 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `413b3a1e…` |
| J8 | 2026-09-04 23:00 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `2d72bcb3…` |
| J9 | 2026-09-05 02:00 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `c0611258…` |
| J10 | 2026-09-08 05:00 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `80e352e7…` |
| J11 | 2026-09-09 19:00 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `0b715f19…` |
| J12 | 2026-09-12 04:00 | RED / RED / RED / RED | RED / RED / RED / RED | Match | v6 real request; context `6754870d…` |
| J13 | 2026-09-12 09:00 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `e1f88e8b…` |
| J14 | 2026-09-14 08:00 | GREEN / GREEN / GREEN / YELLOW | GREEN / GREEN / GREEN / YELLOW | Match | v6 real request; context `f962373f…` |

The bounded sequence was:

| Product Judge | Real requests | Four-field complete matches | Notes |
|---|---:|---:|---|
| `v2-reset-judge-4` baseline | 15 | 1 / 14 | One finite retry; all fourteen windows completed |
| `v2-reset-judge-5` first correction | 14 | 10 / 14 | Four substantive mismatches remained |
| `v2-reset-judge-6` final correction | 14 | 14 / 14 | No third Prompt correction performed |

Final output validation also passed for all fourteen windows: referenced posts and historical cases exist,
no post or historical outcome is later than the window `as_of`, no restricted content is cited, and the
two non-null estimated ranges do not precede or contradict their window. The model made 43 requests over
the three runs and sent zero notifications. The immutable local comparison is
`runtime/review/corpus-closeout-20260918/judge-window-final-comparison.json`, SHA-256
`c0b3b947df6a3e884b1096f7f4d3ef52ee5abdc837d3ca3cb24afcddb8c12ab2`.

## C. Content restrictions in force

Policies are bound to `tweet_id + content_hash`, not to a permanent Tweet-ID blacklist. A changed content
version is quarantined until that version is reviewed; a corrected version can regain uses through an
explicit new policy. Ordinary new self-collected posts retain the normal realtime defaults.

`Archive` below means the row and its audit explanation remain in storage. `Event`, `Judge`, and `Case`
refer to formal-event promotion, recent/Judge evidence, and historical-case retrieval respectively.
Hash values are the first twelve characters of the current SHA-256; the full values are in the ignored
policy receipt.

| Tweet ID | Content version | Restriction | Archive | Analysis | Event | Judge | Case | Actual result |
|---|---|---|---|---|---|---|---|---|
| 2093395719805960389 | `ca4b6b304516…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2076119366647894371 | `175e950672fb…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2093916713087897970 | `245507ab01fd…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2094826841622348106 | `5f028ca5bdd3…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2094882239763071372 | `2768d32161f6…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2098705723706269896 | `7289f167a395…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2098814684359270845 | `5879ce79fccd…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2099569520155218337 | `89e108f8c006…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2099757446319276255 | `5659dc423114…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Exact version matched; excluded |
| 2100100484195598412 | `0a1abeb69d40…` | Author/body integrity | Kept | Blocked | Blocked | Blocked | Blocked | Removed from current evidence |
| 2086972802457063486 | `ce12eed0064c…` | Human `INSUFFICIENT_INPUT` | Kept | Allowed | Blocked | Blocked | Blocked | No event/Judge/case use |
| 2090767169889992755 | `b50b0a0adbda…` | Human `INSUFFICIENT_INPUT` | Kept | Allowed | Blocked | Blocked | Blocked | No event/Judge/case use |
| 2092490655864127909 | `c0336a322e4f…` | Human `INSUFFICIENT_INPUT` | Kept | Allowed | Blocked | Blocked | Blocked | No event/Judge/case use |
| 2028649088594436225 | `62c11397ccb5…` | Field-scoped ruling only | Kept | Allowed | Blocked | Blocked | Blocked | No event manufactured |

All fourteen policies matched the current production content hash. Ten block analysis and all fourteen
block event promotion, Judge evidence, and historical-case use. The final isolated contexts and the
production current context contain no restricted ID, no existing formal event cites one, and no active
historical case reaches one directly or through `related_tweet_ids`.

Old Judge history was not rewritten. Judge `#119` still exists with its original evidence, including
`2100100484195598412`, and is therefore auditable as an old result that is no longer eligible for current
display/reuse. Startup Judge `#120` replaced it as the current result and cites no restricted content.

## D. Changes and regression

### Fixed

- Schema version 6 adds `post_content_policies` with content-version-scoped use flags.
- Analysis, event promotion, recent context, Reset-event evidence, historical-case retrieval, Judge
  context, output citation validation, and current API selection now enforce the same policy.
- Changed content that previously had a reviewed restriction is quarantined until the new hash is
  reviewed; the restriction is not hard-coded to a Tweet ID.
- A completed Judge that is expired or now cites ineligible content is retained historically but the API
  returns `UNKNOWN` instead of silently presenting its old colour as current.
- Judge v6 adds the final bounded time/phase semantics needed by J1, J3, J4, and J12. It contains no
  window-ID or Tweet-ID override.
- the launcher and Web header read the unified `VERSION` source rather than printing Alpha 2.

### Existing behavior verified

- Complete `required_schema` envelopes parse; a genuinely missing required level fails explicitly.
- Plus/Pro scope is not expanded to all paid users or mechanically reduced to a partial reset.
- An investigation/cause and a completed occurrence remain separate concepts.
- Future announcements do not become completed events early.
- Full plus Banked effects remain two effects but only one Full-cycle transition.
- Special-event certainty does not become Full-Reset certainty.
- Earlier historical imports do not move the latest cycle backwards.
- Reprocessing `2094251180121854309` and `2094252447271366730` does not duplicate an event/cycle;
  different evidence at the same time still remains distinct.
- Invalid or expired Judge results are not exposed as current.

### Test results

| Environment | Result |
|---|---|
| Working tree Backend | 55 passed |
| Clean release checkout Backend | 40 passed |
| Web | 6 passed; typecheck and build passed |
| Collector | 12 passed; typecheck and build passed |
| Empty database | Schema versions 1-6, `quick_check=ok`, foreign keys 0 |
| Clean API smoke | Health, Radar, Posts, Resets all HTTP 200 |
| Dependency audit | Web 0 vulnerabilities; Collector 0 vulnerabilities |
| Staged patch checks | `git diff --check` clean; secret-pattern scan clean; no staged file over 1 MiB |

The working tree has fifteen additional tests in the intentionally untracked historical-corpus test
module. They explain the 55-versus-40 count difference. The four new generic content-policy tests are
tracked and are present in the 40-test clean release checkout; no formal release test was excluded to
manufacture a pass.

## E. Production and release acceptance

Before production policy application, a SQLite online backup was created at
`runtime/data/codex-reset-radar-v2.pre-content-policy-alpha4-20260918T061505Z.db`, SHA-256
`7081f92eb43b67bf067f88ca698665724e8c9c4578bb2b52fce21c2a197e621a`. Source and backup both had
`quick_check=ok`, zero foreign-key violations, and identical table/count/current-cycle snapshots.

The project-owned stop/start scripts verified and stopped only Backend PID `24100` and Web PID `24524`,
then started Backend PID `22728` and Web PID `5768`. The launcher printed `2.0.0-alpha.4`; the API and
rendered Web header both show the same version. The runtime result demonstrates loaded code independently
of Git HEAD:

- startup/current Judge `#120` was created by the normal product pipeline with
  `v2-reset-judge-6` and `deepseek-v4-flash`;
- it is `GREEN / GREEN / GREEN / YELLOW`, contains no restricted evidence, and is usable by current API
  validity rules;
- Backend `/api/v2/radar` and the Web proxy return the same Judge ID and level;
- the headless rendered page shows Alpha 4 and does not use GitHub Raw;
- Profile, Replies, and Search are healthy; at least three normal post-restart minute groups were
  observed (the final receipt contains seventeen);
- posts remained 369, events 14, cycles 13, current cycle 214, duplicate event-key groups 0;
- the expected database changes are schema 6, fourteen policy rows, and one startup Judge; no historical
  replay result was written to production;
- database `quick_check=ok`, foreign-key violations 0, and notification sends 0.

Seven old production jobs remain in terminal `FAILED` status from `2026-09-14` DeepSeek timeouts under
Analysis v2; there are no pending jobs. Five of the corresponding archived posts still have no analysis,
and two have completed analysis with pending translation. These failures predate this closeout, were not
relabelled as completed, do not enter current Judge context without an analysis, and were not bulk-rerun
because this task explicitly excluded an indiscriminate historical replay.

GitHub CI passed `backend`, `web`, and `collector-extension` on PR #4. The PR was normally merged to
`main`; no force push or old-tag movement occurred. Git HTTPS experienced transient connection resets
during the first branch/tag pushes. The branch push later succeeded normally; because the tag push path
remained unavailable while GitHub's authenticated API was healthy, the new, previously unoccupied
annotated tag was created through the GitHub Git Data API and independently verified to target the main
merge commit. Pages and Mirror remain disabled.

## Remaining declared limitations

1. Ten archived records still need a corrected body/author/context version before any business use.
2. Three human `INSUFFICIENT_INPUT` records remain non-promotable and non-evidentiary.
3. `2028649088594436225` retains only the approved `content_relation`; scope and occurrence time remain
   insufficient, so no formal event or cycle exists for it.
4. The seven old production processing-job failures described above remain historical operational debt;
   they are visible and non-pending, not silently counted as processed.
5. Judge reasons, evidence lists, and estimated times remain program outputs, not human-approved fields.

None of these limitations hides an unresolved J1-J14 four-field mismatch, current evidence pollution,
event/cycle corruption, missing runtime proof, or release blocker. Future work now returns to normal
incremental corpus maintenance. This task stops here and does not begin the WeChat notification phase.

## Evidence paths

- Final report: `docs/v2/corpus/corpus-closeout-report.md`
- Final Judge comparison: `runtime/review/corpus-closeout-20260918/judge-window-final-comparison.json`
- Aggregate acceptance: `runtime/review/corpus-closeout-20260918/corpus-closeout-acceptance.json`
- Production acceptance: `runtime/review/corpus-closeout-20260918/production-acceptance.json`
- Immutable reviewed package:
  `data/corpus/reviews/unified-review-20260917T094740Z/adjudication-20260918/reviewed-corpus-20260918-v1/`

Real corpus rows, review payloads, model outputs, databases, logs, backups, and one-off review tooling stay
in ignored local paths and are not part of the public repository.
