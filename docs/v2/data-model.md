# V2 Data Model

The V2 database is a new SQLite file at `runtime/data/codex-reset-radar-v2.db`. The V1 database remains a read-only migration source and is never opened as the active V2 database.

Forecast, attempt, truth-revision and review-export semantics are defined in [CRR 日期预测与复盘规范](prediction-and-review-spec.md). Production remains Alpha5 / main `1e865c37d1643f429162adeb0fab61bb7371a47b` with schema 7. Schema 8 is isolated development only. Historical offline baseline at code manifest `1c7a29ad…` recorded Backend 318/0/0, Web 17, Collector 18 and an empty-DB smoke with schema versions 1–8, 22 tables, integrity `ok`, zero FK errors and an unchanged DB hash across CLI use; these results do not attest later changes. The prior v9 11-HTTP controlled model-semantics result is `PARTIAL`; v10 time-contract retest was not authorized and remains `NOT_EVALUATED`. Actual accuracy remains `NOT_EVALUATED`; deployment remains `NOT_DEPLOYED`. No production migration was run for that historical baseline. See the [current report](../maintenance/prediction-three-lines-v1-report.md) for current status.

## Core tables

### `tibo_posts`

Deduplicated public posts keyed by unique `tweet_id`. English/source text, Chinese display translation, language/source metadata, content hash, processing states, and errors are separate fields. A translated browser sighting cannot overwrite an already preserved English original. The content hash plus prompt/model versions forms the model-processing identity. Historical rows additionally carry `ingestion_mode`, batch/cutoff, verification, completeness, context/conflict, and time-source/precision metadata. Historical-only rows are excluded from realtime bootstrap processing.

### `reset_events`

Canonical verified events with an idempotent event key, `event_type`, optional `special_type`, occurrence range, time basis, scope, execution stage, all evidence Tweet IDs, summary, and provenance. A Full Reset must not have a subtype; a Special Reset must have one.

Temporal proximity is not identity. New implicit keys use mechanism, exact stated occurrence and
evidence IDs, not a six-hour bucket. Explicitly reviewed cross-post associations may reuse an existing
event key. Startup preserves assigned IDs/keys and never deletes historical events to consolidate
time bins; old merged records require separate evidence review rather than speculative splitting.

### `reset_cycles`

Lifecycle support for Full Resets. Cycles are rebuilt in event-time order, so adding older verified history cannot replace the newest current cycle. A Special Reset never changes this table.

Rebuilding updates interval boundaries in place and preserves each opening event's cycle ID, including
IDs referenced by existing Judge rows. It does not invent replacements for already-lost legacy links.

### `post_analysis`

Structured, attributable analysis outcomes: post/content hash, analysis type, model, prompt version, category, evidence JSON, concise structured output, status, and timestamps. Hidden model reasoning is not stored.

### `radar_judgements`

Product decisions with the main Action Level, 24/48/72-hour horizons, data health, reason, evidence post IDs, Special Reset IDs, signal estimate range/basis, validity, cycle, context hash, model, and prompt version. All Action/Horizon values are constrained to the four levels plus `UNKNOWN`; no confidence field exists.

### `processing_jobs`, `reset_event_candidates`, `pipeline_state`

`processing_jobs` provides local restart recovery and finite retries without Redis or Celery. Ambiguous event evidence is kept in `reset_event_candidates` instead of being forced into history. `pipeline_state` exposes processing, failure, stale, and ready states without manufacturing a Radar result.

### Historical corpus tables

- `corpus_sources` registers where material came from, how it was obtained, the available range, content type, and reuse limitation.
- `historical_import_batches` records cutoff, status, checkpoint and statistics. `historical_import_changes` stores per-record pre-images for conservative batch rollback.
- `post_source_evidence` keeps each source observation separate, including quoted text, verification, completeness, time basis and conflicts.
- Schema v5 separates `source_claimed_status` from `local_verification_status` and retains author,
  source-time, timezone/semantics, parent Tweet ID, and upstream-key fields. A third party's `verified`
  value is therefore never the local result by implication.
- `historical_cases` is the reviewed, versioned subset eligible for retrieval into the Judge. It includes known outcome and coverage limitations rather than treating missing outcomes as negatives.
- `corpus_coverage` records actual acquired ranges and known gaps without manufacturing a percentage denominator.
- `historical_event_dispositions` gives every acquired event/signal claim an explicit destination,
  reason, missing evidence, optional formal event/candidate link, and per-effect split for dual claims.

`radar_judgements` now also persists `corpus_version` and the exact historical case IDs supplied to that call.
New Judge `raw_json` records include `input_versions` for every exposed eligible Tweet, including
event-source posts outside the recent-post window, plus an `input_snapshot` and its digest ID. The
snapshot closes over analysis versions, event summaries, retrieved cases, current cycle and corpus
version. It is frozen before the model call and revalidated before persistence; old records are not
rewritten or made valid by reconstructing missing historical versions.

### Standard corpus exchange

`crr-corpus-v1` maps the existing tables to deterministic UTF-8 JSONL records for posts, Reset events,
review cases, and independent review results. It does not add duplicate production tables. Stable IDs,
content hashes, explicit nulls, time precision/basis, original/translation separation, completeness,
and review state are defined in `corpus/corpus-standard.md`.

Historical replay queries accept a bounded `as_of`: future posts, events, cycles, judgements, and case
outcomes are excluded, and a tested post cannot retrieve its own existing case. Default live calls omit
`as_of` and retain current-time behavior.

### Reply context mapping (schema 7)

- `reply_context_nodes`: current bounded context capture, with author, text/language,
  timestamp, direct-parent relation proof, completeness and stable hash. It is context-only;
  other authors never enter `tibo_posts` or Tibo post counts. Existing canonical Tibo bodies
  are reused when assembling model input.
- `reply_context_history`: immutable per-content-version observations for audit. Repeated
  sightings do not add history rows. Later observations are excluded from historical `as_of`.
- `reply_context_inputs`: exact structured inputs keyed by semantic input hash, including
  explicit missing context. These local real assets are ignored by Git with the database.
- `processing_jobs`: accepts `POST_PROCESSING` and `REPLY_CONTEXT`. Schema 7 migrates the
  previous job-type CHECK constraint transactionally while preserving IDs and retry state.
  Context leases use `next_attempt_at` and an opaque token in `payload_json`; duplicate or
  expired receipts cannot update content. Context tasks do not indefinitely block Judge.

For replies, the analysis `content_hash` now identifies the target text plus ordered context,
confirmed relations and meaningful availability. `analysis_json._text_hash` retains the target
body hash; `_input_hash` and `_analysed_at` identify the actual input version. Acquisition times,
heartbeats and attempt counts are excluded. Translation versions are recorded in
`pipeline_state.reply_translation:<post_id>`. Judge raw results retain `input_versions` for
current-result validation. An old Judge is never rewritten to match a new context.

The current posts API includes `reply_context` and `context_acquisition`. Reconstructed
parents observed after a replay cutoff are conservatively excluded, even if their claimed
posting time is earlier. Body-only canonical cache hits do not manufacture ancestor relations.

### Prediction review ledger (schema 8; isolated development only)

The isolated review implementation adds two append-only storage structures and a nullable link on
`radar_judgements`. This schema is present in the development worktree only; it has not been applied
to the resident `main` checkout or enabled in production.

The Ledger baseline at `ef226ebe14cf45ad7af80af1b14d87e17638e355` has historical regression
evidence, including Backend 140, Web 7 and Collector 18. Those numbers belong only to the old
implementation described in the [Ledger report](../maintenance/prediction-review-ledger-v1-report.md).
The historical offline result for code manifest `1c7a29ad…` recorded Backend 318/0/0, Web 17 and
Collector 18, with type checks, builds and empty-DB API/CLI verified. It does not cover later source
changes; see the current report above. The branch depends on OPEN [PR #10](https://github.com/Oblivionis-ling/codex-reset-radar/pull/10); no production migration was run.

- `prediction_artifacts` stores immutable JSON payloads by `id`, `kind`, `content_hash`,
  `payload_json`, and `recorded_at`, with a uniqueness constraint on `(kind, content_hash)`.
- `prediction_ledger` stores ordered records by autoincrement `seq` and unique `record_id`; each
  record has a constrained `kind`, optional series/forecast/run/attempt/revision/Judge/event links,
  optional occurrence time, required record time, optional idempotency key, and `payload_json`.
  Supported kinds are `runtime_identity`, `forecast_version`, `run_started`, `attempt_started`,
  `attempt_event`, `output_committed`, `output_observed`, `truth_revision`, `normal_baseline`, and
  `recovery_observed`.
- `radar_judgements.ledger_attempt_id` is a nullable link used to avoid treating a ledger-backed
  Judge row as a second legacy-only record.

The review reader opens an existing SQLite file in read-only mode, enables `query_only`, and reads
the ledger, artifact closure, legacy compatibility rows, and high-water mark from one transaction
snapshot. It does not call `Database.initialize`, create a missing database, migrate, backfill, or
write attempts. Older files without the new tables/column use a bounded legacy adapter; unknown
historical start, completion, output-availability, translation, configuration, or run-identity data
remain null or explicit gaps rather than being reconstructed from current rows. Legacy Judge
`created_at` is only an `as_of` proxy, not proof of when a result completed or became available.

This is a local export/read boundary, not a new production storage guarantee or API contract. See
the [prediction review operations guide](prediction-review-operations.md) for current isolation and
invocation details.

### Three-line storage and scoring extension (development contract)

Current development code reuses `prediction_artifacts`, `prediction_ledger` and the Judge link.
Final empty-DB initialization verified schema 8; no production migration or schema change is
claimed. This section documents the isolated integration boundary; the confirmed business rules
stay in the prediction specification.

| Existing boundary | Current mapping and required distinction |
| --- | --- |
| `forecast_version` | Target-specific `target_refs` carry series/forecast/revision/previous links for Extra Full and Banked. Both targets share the run, immutable input artifacts, runtime identity and actual attempt. |
| `output_committed` | `target_outputs`, `prediction_validation` and contract version preserve accepted, unknown and rejected target results. A shared-input rejection prevents both targets from becoming current; a target-level rejection is retained alongside explicit partial success. |
| `normal_baseline` | Stores new Normal versions and their anchor references through the existing +7-day function. Legacy history remains `NOT_BACKFILLED`; compatible current views are not invented historical versions. |
| Judge `raw_json` / internal `raw` | The structured `predictions` extension is decoded at the existing storage boundary. Legacy Full fields retain their original meaning; absent Banked output is a compatibility gap, not model UNKNOWN. |
| `truth_revision` | Independent revisions and association evidence remain append-only. Proxy, unknown and trusted start ranges remain distinguishable. |
| Evaluation-set / assessment DTOs | Offline files bind fixed membership/hash, source identity and core-record digests, forecast/truth versions and algorithm version. Default scoring does not mutate the source ZIP or database. |

Stable assessment binding uses source identity and `crr-review-core-collections-v1` digests;
evaluation-set and assessment attachment changes package bytes without changing unchanged core
scoring-input identity or creating a hash cycle. The final synthetic package and scored real
seven-day package both reproduced their assessments; final clean empty-DB CLI also produced a
byte-identical final-only re-score. The older base-v2 package still has zero assessments. Scored
Schema7 input retains `LEGACY_UNDECLARED`, missing Banked forecasts/history and unavailable clocks;
an attached assessment does not make it a modern producer or prove real accuracy.

Official-time extraction retains independently checkable source qualification and the stated time
expression. Relative time retains the source-post anchor and conversion evidence. Historical full
offline acceptance was bound to code manifest `1c7a29ad5c561c240e5ce6b67e59cf4eb68d213e3c42160e260769acce58a3df`;
its Backend result was 318 tests with no failures or skips. These historical results do not cover
later source changes. Old candidate failures remain historical evidence.
`tzdata>=2025.2,<2027` is
declared for Python `ZoneInfo` on Windows; the dependency
does not supply a missing source timezone or justify extra time precision.

### Content policy and Judge storage boundary

`post_content_policies` stores content-version-scoped restrictions and field-level review
provenance. Restrictions apply before event promotion and before text reaches Judge through
recent posts, associated context or historical cases; a site label alone is not a quality rule.

SQLite stores Judge model output in `raw_json`; the sole database decoding boundary exposes
internal `raw`. `input_versions` records actual semantic input hashes; new rows also keep
`input_post_ids`, triggers and pending inputs. Malformed JSON/types or conflicting representations
are explicit contract errors, not an empty legacy dictionary. Validation checks expiry, cycle,
evidence eligibility and target/parent/ancestor versions without rewriting old answers.

### Schema version ledger

Applied database schema versions and timestamps.

## Long-term storage policy

Long-term data includes public posts, verified Reset events, structured evidence, necessary Radar snapshots, and reviewed analysis artifacts. Heartbeats, HTTP traces, timer ticks, Service Worker routine events, browser lifecycle spam, and high-volume diagnostics remain ephemeral or in bounded logs.

## Initial state

Migration imports posts by `tweet_id` without blindly copying V1 classifications into canonical events. Alpha 2 selectively reprocesses the recent 72-hour window, recent Dashboard records, and migration candidates with the configured semantic model. Historical corpus import is a separate, non-queuing path. Until evidence passes current validation, it is not promoted into `reset_events`.
