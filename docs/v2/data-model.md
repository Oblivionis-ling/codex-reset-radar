# V2 Data Model

The V2 database is a new SQLite file at `runtime/data/codex-reset-radar-v2.db`. The V1 database remains a read-only migration source and is never opened as the active V2 database.

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

### Standard corpus exchange

`crr-corpus-v1` maps the existing tables to deterministic UTF-8 JSONL records for posts, Reset events,
review cases, and independent review results. It does not add duplicate production tables. Stable IDs,
content hashes, explicit nulls, time precision/basis, original/translation separation, completeness,
and review state are defined in `corpus/corpus-standard.md`.

Historical replay queries accept a bounded `as_of`: future posts, events, cycles, judgements, and case
outcomes are excluded, and a tested post cannot retrieve its own existing case. Default live calls omit
`as_of` and retain current-time behavior.

### `schema_versions`

Applied database schema versions and timestamps.

## Long-term storage policy

Long-term data includes public posts, verified Reset events, structured evidence, necessary Radar snapshots, and reviewed analysis artifacts. Heartbeats, HTTP traces, timer ticks, Service Worker routine events, browser lifecycle spam, and high-volume diagnostics remain ephemeral or in bounded logs.

## Initial state

Migration imports posts by `tweet_id` without blindly copying V1 classifications into canonical events. Alpha 2 selectively reprocesses the recent 72-hour window, recent Dashboard records, and migration candidates with the configured semantic model. Historical corpus import is a separate, non-queuing path. Until evidence passes current validation, it is not promoted into `reset_events`.
