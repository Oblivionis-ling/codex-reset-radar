# Codex Reset Radar V2 — unified corpus and product cross-check report

## 2026-09-18 full continuation after human adjudication

The supplied 87 human records were preserved as field-scoped decisions and used to continue the task.
They were not expanded into whole-object or Judge-colour approvals.

The frozen 366-post package completed a new isolated product replay with Analysis
`v2-post-semantics-5`, Translation `v2-zh-translation-1`, and Judge `v2-reset-judge-4`:

- 366 / 366 posts, analyses, translations, and persistent jobs completed;
- 677 real model HTTP attempts all returned successfully;
- two initially invalid structured analyses were recovered by the existing persistent-job retry path;
- 40 formal events, 40 candidates, 35 Full cycles, and 16 Judge results were produced;
- SQLite `quick_check=ok`, zero foreign-key violations, zero notifications;
- the latest Full event remained `2098685367058612394` at `2026-09-12T08:09:17Z` in that replay;
- all 16 current/historical Judge contexts had zero future post, event, or historical-outcome leakage.

The replay exposed a deterministic Judge parser defect: one valid answer was returned inside a
`required_schema` envelope, while the parser silently substituted four `UNKNOWN` values. The parser now
unwraps a complete generic envelope and rejects genuinely missing required levels. A real two-request
regression reproduced the same `2026-09-12T09:00:00Z` window as `GREEN/GREEN/GREEN/GREEN`, with no
estimated time. Backend tests increased to 50 and pass.

Analysis was then advanced through bounded targeted product regressions to
`v2-post-semantics-8`. The current general rules add `plus_pro`, prevent named Plus/Pro scope from being
expanded to `all_paid` or downgraded to partial, separate an ongoing investigation from an already
completed Reset, preserve explicit multiplicity such as “twice”, distinguish future landing language
from a started rollout, and suppress context-free slogans/questions as false hints. These rules do not
contain Tweet-ID overrides. Across v6/v7/v8 targeted runs, 48 post executions made 96 real requests;
every task completed and no notification was sent.

Of 73 unique posts with human field decisions, the final comparison is:

| Status | Count |
|---|---:|
| Program agrees with the human-decided fields | 69 |
| Human `INSUFFICIENT_INPUT` retained | 3 |
| Intentional human override still differs from source-only model | 1 |

The remaining mismatch is `2028649088594436225`: the user decided that the event had occurred, while
the frozen source says “will reset”. The decision remains authoritative for `content_relation`, but scope
and occurrence time are still missing, so no new formal event was manufactured and the original wording
was not changed.

The earlier reference-translation gap was re-counted from the actual package as 182, not the stale
documented estimate of 185. All 182 now have item-level GPT Chinese references with content hashes. They
were produced from frozen source text without reading the matching program translation and are labelled
as a second pass, not as a blind translation eval. Five obvious GPT reference defects were separately
revised with supersession records; none is labelled human-approved.

The composite comparison now has 366 `AGREED`, 17 `NEEDS_HUMAN_REVIEW`, and 10
`INSUFFICIENT_INPUT` records. The 17 open records are three event scope/cycle questions and fourteen
historical Judge colour/window questions. The Judge cards previously used for content classification did
not approve their colours. The exact queue is in the ignored candidate package at
`data/corpus/reviews/unified-review-20260917T094740Z/adjudication-20260918/review-candidate-20260918/remaining-human-adjudication.md`.

Candidate `review-candidate-20260918-v1` contains 366 posts, 14 event records, 20 cases, 688 traceable
review records, comparison outputs, hashes, and the remaining queue. Its state is deliberately
`CANDIDATE_PENDING_HUMAN`; it is not a final reviewed corpus version. The two already approved Plus/Pro
events remain the only new production promotions. No other event/cycle, Judge result, or notification was
written to production, and the running service still has not been replaced by this worktree.

At the final runtime observation, the live database had naturally advanced to 368 posts, 14 events,
20 cases, and zero pending jobs; Profile, Replies, and Search were healthy and the Web returned 200. The
process still reported Judge Prompt `v2-reset-judge-2`, proving that the new Prompt/parser code had not
been hot-reloaded. Git-derived commit metadata alone showed the new checkout commit and is not treated as
deployment evidence.

Regression after these changes: Backend 50 tests; Web 6 tests, typecheck, and build; Collector 12 tests,
typecheck, and build. The 49-file commit whitelist excludes all seven third-party fetch/import/repair
modules, review packages, databases, logs, and credentials. A clean checkout containing only that patch
passed Backend 35 tests, Web 6 tests/typecheck/build, Collector 12 tests/typecheck/build, empty-database
startup, and all four API reads. That smoke test also exposed and fixed a Windows SQLite handle leak:
`Database.connect()` now commits/rolls back and always closes the connection; temporary database cleanup
then passed. Release publication/tagging remains gated by the unresolved event/Judge decisions. The
baseline sections below are retained for traceability.

## Outcome

**Additional human ruling applied:** the two historical Plus/Pro resets were explicitly accepted as
Full-cycle starts. After a consistent backup and isolated/idempotent trial, they were added as two
human-adjudicated events (12 -> 14 events, 11 -> 13 Full cycles), retaining `scope=plus_pro` and labelled
post-time proxies. The latest Full Reset/current cycle did not move backwards. A three-post real
product replay used nine requests; remaining model differences are preserved, not labelled agreement.
This partial historical data amendment is separate from deployment of the uncommitted code or final
corpus promotion. See the follow-up report below for its receipt and backup paths.

**2026-09-18 continuation:** the user has returned all 87 simple-review choices (73 primary posts),
eight mechanism/multi-effect clarifications, three explicit stage decisions and one Full-only Radar
policy. These are archived as field-scoped human decisions, not blanket approval of every event field
or Judge window. Three targeted 27-post product runs plus a cached-input Judge regression (168 real HTTP
requests in total) and 47 Backend tests have
now completed. The new code has not replaced the running production process or promoted a final corpus.
See [the Chinese adjudication follow-up](human-adjudication-followup-20260918.md) for current results,
remaining model/engineering failures and exact evidence paths.

**The sections below preserve the original 2026-09-17 baseline, not the current decision counts.**

The first complete semantic comparison has reached the required human-review stop. The frozen corpus was
standardized, every canonical post ran through the real V2 DeepSeek product pipeline in an isolated
database, representative historical Judge windows were replayed without future leakage, and GPT reference
results were compared field by field with the product outputs.

No disagreement has been marked human-approved. No production event, cycle, task, notification, or
corpus label was changed by the replay. No commit, push, merge, or tag was performed because 77
substantive differences require a real user decision first.

## Versions and freeze

- Corpus standard: `crr-corpus-v1`.
- Review package: `unified-review-20260917T094740Z`.
- Freeze cutoff: `2026-09-17T09:47:40Z`.
- Git branch / HEAD: `main` / `90acfb98ad77aa9a4657c6b84f9a763d2091a729`.
- Application version: `2.0.0-alpha.2` (`v2.0.0-alpha.1-dirty` from Git describe at freeze).
- Existing corpus: `corpus-round2-20260917-994180c769c7@2026-09-17T06:40:00Z`.
- Product model: `deepseek-v4-flash`.
- Prompt versions: analysis `v2-post-semantics-2`, translation `v2-zh-translation-1`, Judge
  `v2-reset-judge-2`.
- GPT reviewer: the current Codex main model, known to be GPT-family; the exact deployment identifier is
  not exposed to this task and was not guessed.

The online SQLite backup is
`runtime/data/codex-reset-radar-v2.pre-unified-review-20260917-094740.db`, SHA-256
`28ec5b67614303cb894e391929127d61c64912dee3dce98203f569ba5db84752`. It opens successfully,
`quick_check=ok`, and has zero foreign-key violations.

## Frozen scope

| Object | Count | Treatment |
|---|---:|---|
| Canonical posts | 366 | One string Tweet ID per record; all received a GPT semantic result and a real product run |
| Formal Reset events | 12 | All included, including seven reviewed 2025 seeds |
| Existing historical cases | 20 | Reviewed for purpose/limitations and loaded only as pre-existing product context |
| Historical dispositions | 262 | Preserved in the local package; no claim was hidden by a zero-candidate count |
| Source evidence rows | 279 | Preserved separately, including conflicts and source/local verification states |
| Current candidates at freeze | 0 | Does not erase the 203 unresolved source dispositions |

The package manifest records content hashes for all exported files, the source database, Git HEAD,
worktree fingerprint, model configuration without credentials, and Prompt versions.

## GPT reference review

GPT produced 413 item-level results:

- 366 post reviews;
- 12 formal-event reviews;
- 20 existing-case reviews;
- 15 `JUDGE_WINDOW` references created before reading this replay’s Judge outputs.

Review states are 403 `GPT_REVIEWED` and 10 `INSUFFICIENT_INPUT`; human-approved count is zero.
Post semantics are 32 reset-confirmed, 15 reset-in-progress, 20 reset-announcement, 11 reset-hint,
13 quota-information, and 275 other.

Translation treatment stayed explicit:

- 79 Reset/quota-sensitive English posts received an independent GPT Chinese reference translation;
- 29 existing translations were retained but not used as the factual source;
- 73 Chinese/browser-translated captures were preserved as obtained, with missing English originals
  explicitly flagged rather than reverse-translated;
- 185 ordinary non-signal English posts completed semantic review but did not receive a materialized
  line-by-line Chinese reference at this human stop. This remains a corpus-completeness item and is not
  presented as completed translation coverage.

Ten canonical post bodies cannot safely be treated as Tibo statements: two are UI shells without a Tweet
body and eight appear to contain quoted/other-author text. IDs:

`2093395719805960389`, `2076119366647894371`, `2093916713087897970`,
`2094826841622348106`, `2094882239763071372`, `2098705723706269896`,
`2098814684359270845`, `2099569520155218337`, `2099757446319276255`, and
`2100100484195598412`.

The last ID is currently present in production Judge #95 evidence. It must be repaired or verified before
it is promoted as trustworthy Tibo-authored evidence; this report does not decide the author without the
missing page context.

## Current product replay

The isolated replay database is
`runtime/review/unified-review-20260917T094740Z/pipeline-replay.db`; logs are under the sibling `logs`
directory. The replay imported no GPT labels or expected outputs.

All 366 posts followed the current product path:

```text
standard import -> persistent job -> DeepSeek analysis -> DeepSeek translation
-> event/candidate normalization -> cycle rebuild -> historical retrieval
-> DeepSeek Judge -> persisted API data
```

Final execution:

- unique posts completed: 366 / 366;
- final failed posts: 0;
- completed persistent jobs: 366;
- cached or duplicate skips counted as new review: 0;
- jobs that required a second attempt: 7; all recovered;
- LLM failure events: 5 analysis timeouts and 2 invalid responses, all recovered by existing retry paths;
- successful log events: 372 post-analysis calls, 293 remote translation calls, and 16 Judge calls;
- 73 source-Chinese posts completed translation locally without a remote translation request;
- normalized events: 42;
- candidates: 30;
- current Judge plus historical windows: 16;
- notifications sent: 0.

The 15 historical windows cover hint, announcement, propagation, completion, delay/correction,
Special-only banked events, compensation, and ordinary product discussion. An audit found zero evidence
posts or historical-case outcomes later than the window `as_of`. The tested post’s own case is excluded
from retrieval.

The isolated API returned healthy, 366 posts, 42 events, and the replay’s current Radar result. The Web
and API binding was covered by the existing Web tests and production localhost check; the replay did not
replace the user’s ports or live database.

## Comparison result

There are 396 comparison records:

| State | Count | Meaning |
|---|---:|---|
| `AGREED` | 300 | No material fact/product difference found |
| `NEEDS_HUMAN_REVIEW` | 77 | Mechanism, stage, eligibility, semantic signal, or Judge policy differs |
| `ENGINEERING_FIX_REQUIRED` | 9 | Only deterministic validation/format defects remain, mainly non-verbatim evidence quotes |
| `INSUFFICIENT_INPUT` | 10 | Author/body integrity must be repaired before adjudication |

The unresolved file has 211 entries across 176 unique objects: 134 input/context items and 77 substantive
differences. Counts are entries, not invented independent Tweets.

### Highest-priority human decisions

1. **Incident compensation mechanism** — GPT says `1986166501435711936` and
   `2002137269134819610` are completed Full Resets; the product says `SPECIAL_RESET/PARTIAL`.
   The same mismatch affects two already formal events. Decide whether incident reason changes mechanism.

2. **Plus/Pro scope** — `2029308599835738218` and `2030474136024400173` differ on Full versus
   partial/ambiguous and whether the event is already canonical. The plan universe at that historical time
   is required to decide.

3. **Future announcement versus no event/ambiguous** — explicit future statements such as
   `2028649088594436225`, `2031216405266481489`, `2046367145588916687`,
   `2046602907077038501`, `2055446089957036402`, `2060964284117782996`,
   `2075296200761418073`, `2091412393368945027`, and `2098612714704891959`
   are not represented consistently by the current analysis result.

4. **Propagation and canonical eligibility** — multiple texts say a reset has been pressed or is landing,
   but the product often leaves `canonical_eligible=false`. Important IDs include
   `2031605592352313567`, `2042299371602264319`, `2070653282440405046`,
   `2075820987833274448`, `2077114635308986427`, `2079609157934886975`,
   `2087706104814023111`, and `2091688655828246890`.

5. **Multiple effects** — the current one-event analysis output cannot fully preserve the two effects in
   `2004100061933064395`, `2067399435009622521`, `2071740419030053227`, and
   `2075641131002700120`.

6. **Short contextual replies** — posts such as `2090767169889992755`,
   `2091045457158103247`, `2092490655864127909`, `2092491868189929771`,
   `2095004327597506707`, `2097175062566846501`, and `2097183639356489952`
   cannot be safely promoted without their parent/body context.

7. **Judge policy for Special events** — at `2026-09-03T23:30Z`, `2026-09-04T23:00Z`, and
   `2026-09-05T02:00Z`, GPT keeps the Full-cycle main level GREEN while exposing the banked event as
   Special; the product returns ORANGE for all horizons. Decide whether Special-only certainty should
   raise the main Action Level.

8. **Judge sensitivity** — the product misses the 2026-08-27 reset-button hint (GREEN versus GPT
   ORANGE) and gives ORANGE rather than RED for the explicit 2026-09-12 “by midnight” announcement.
   Several GREEN-versus-YELLOW 72-hour differences reflect policy rather than historical fact.

The complete 77-item queue includes original text, GPT result, product result, differing fields, and an
empty human decision. No suggested direction is preselected.

## Current cycle and production safety

Both production and replay retain `2098685367058612394` at `2026-09-12T08:09:17Z` as the latest Full
Reset. Older history did not move the current cycle backwards. The replay has no effect on production.

At report time production is healthy:

- Backend `2.0.0-alpha.2`: healthy;
- Profile Monitor: healthy;
- Replies Monitor: healthy;
- Search Backfill: healthy;
- pending product jobs: 0;
- production posts/events/cases: 366 / 12 / 20;
- production Radar #95: GREEN, 24h GREEN, 48h YELLOW, 72h YELLOW;
- local Web: HTTP 200 and reading localhost V2 API;
- real collector batches continue to arrive; the observed batches were existing real Tweet IDs with
  new=0 and duplicate/update outcomes, so no fake post was inserted.

## Regression and security checks

- Backend: 34 tests passed.
- Web: 6 tests passed; TypeScript and production build passed.
- Collector Extension: 12 tests passed; typecheck and production build passed.
- `git diff --check`: passed (line-ending notices only).
- Changed-file secret scan: 52 files inspected, zero secret-pattern hits.
- Changed files over 1 MB: zero.
- The review package, SQLite files, logs, model outputs, and one-off GPT/comparison helpers are ignored.

## Worktree and release state

Long-term additions currently in the worktree include:

- `apps/backend/app/corpus_standard.py`;
- versioned JSONL validation/import/export;
- `as_of`-bounded post/event/cycle/case/Judge context;
- self-case retrieval exclusion;
- `scripts/export_corpus_package.py`;
- `scripts/replay_corpus_pipeline.py`, which orchestrates the real product pipeline and contains no
  reviewer Prompt;
- synthetic regression tests;
- this standard and procedures.

Earlier Alpha 2 and corpus work is still dirty and protected. Third-party fetch/import scripts and the
one-off review helpers have not been added to a release commit. No new version tag was selected.

## Original human-review stop and next continuation (superseded by follow-up above)

The user must now adjudicate the 77 substantive queue items, individually or by an explicit rule for a
clearly defined group. Valid decisions are `GPT_REFERENCE`, `PRODUCT_PROGRAM`, `BOTH_NEED_CHANGE`,
`INSUFFICIENT_INPUT`, or `REPAIR_INPUT_FIRST`, with a short reason.

After those decisions, Codex can continue without a new engineering task sheet: write actual human
decisions, repair canonical input, update the current Prompt/context/event logic, replay only affected
objects plus untouched regression cases, promote eligible reviewed corpus fields, run one controlled
current Judge, validate a clean checkout, and then prepare the reviewed commit/push/tag.

## Paths

- Review package: `D:\work\20260828-CodexResetRadar\data\corpus\reviews\unified-review-20260917T094740Z`
- Human queue: `D:\work\20260828-CodexResetRadar\data\corpus\reviews\unified-review-20260917T094740Z\human-review-queue.md`
- Manifest: `D:\work\20260828-CodexResetRadar\data\corpus\reviews\unified-review-20260917T094740Z\manifest.json`
- GPT results: `D:\work\20260828-CodexResetRadar\data\corpus\reviews\unified-review-20260917T094740Z\review_results.jsonl`
- Program results: `D:\work\20260828-CodexResetRadar\data\corpus\reviews\unified-review-20260917T094740Z\baseline_program_results.jsonl`
- Comparison: `D:\work\20260828-CodexResetRadar\data\corpus\reviews\unified-review-20260917T094740Z\comparison.jsonl`
- Unresolved: `D:\work\20260828-CodexResetRadar\data\corpus\reviews\unified-review-20260917T094740Z\unresolved.jsonl`
- Isolated replay database: `D:\work\20260828-CodexResetRadar\runtime\review\unified-review-20260917T094740Z\pipeline-replay.db`
- Final report: `D:\work\20260828-CodexResetRadar\docs\v2\corpus\corpus-standardization-review-report.md`
