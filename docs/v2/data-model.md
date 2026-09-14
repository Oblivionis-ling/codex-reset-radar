# V2 Data Model

The V2 database is a new SQLite file at `runtime/data/codex-reset-radar-v2.db`. The V1 database remains a read-only migration source and is never opened as the active V2 database.

## Core tables

### `tibo_posts`

Deduplicated public posts keyed by unique `tweet_id`. It stores normalized publication/collection time, text, URL, reply relationship, source, and creation time. It does not store large duplicate browser payloads.

### `reset_events`

Canonical verified events with `event_type`, optional `special_type`, occurrence time, optional source post, title, summary, provenance JSON, and creation time. A Full Reset must not have a subtype; a Special Reset must have one.

### `reset_cycles`

Lifecycle support for Full Resets. At most one cycle is open. Recording a new Full Reset closes the previous open cycle and opens the next; a Special Reset never changes this table.

### `post_analysis`

Structured, attributable analysis outcomes: post, analysis type, model, prompt version, category, evidence JSON, concise summary, and creation time. Hidden model reasoning is not stored.

### `radar_judgements`

Product decisions with the main Action Level, 24/48/72-hour horizons, data health, reason summary, evidence post IDs, Special Reset IDs, model, and prompt version. All Action/Horizon values are constrained to the four levels plus `UNKNOWN`; no confidence field exists.

### `schema_versions`

Applied database schema versions and timestamps.

## Long-term storage policy

Long-term data includes public posts, verified Reset events, structured evidence, necessary Radar snapshots, and reviewed analysis artifacts. Heartbeats, HTTP traces, timer ticks, Service Worker routine events, browser lifecycle spam, and high-volume diagnostics remain ephemeral or in bounded logs.

## Initial state

Migration imports posts by `tweet_id` but does not create canonical Reset events from V1 classifications. Until provenance is reviewed and at least one canonical Full Reset exists, `last_full_reset` is null and the next Reset status is `waiting_for_verified_history`.
