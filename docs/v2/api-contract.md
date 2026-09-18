# V2 API Contract

Base URL: `http://127.0.0.1:8787/api/v2`

## Product reads

- `GET /health` — version/commit, database counts, ephemeral collector state, pipeline/Judge state, pending jobs, corpus inventory, and disabled GitHub runtime flags.
- `GET /radar` — persisted Judge ID/state/validity, Action Level, 24/48/72 horizons, evidence IDs, selected historical case IDs/corpus version, signal time range, next-reset baseline, last Full Reset, and recent Special Resets.
- `GET /posts?limit=20` — recent posts with source text, Chinese translation, analysis and per-stage status.
- `GET /resets?limit=50` — canonical events, current last Full Reset, and explicitly separated review candidates.

The Radar response accepts only `GREEN`, `YELLOW`, `ORANGE`, `RED`, and `UNKNOWN`. It never exposes confidence or confidence percentage. `judgement_state` distinguishes processing, failed, stale, blocked and ready. With no verified Full Reset, `next_reset.status` is `waiting_for_verified_history`; an elapsed +7-day reference is `expired` and is never rolled forward automatically.

## Controlled writes

- `POST /api/v2/resets` — records an explicitly supplied canonical Full/Special Reset and applies lifecycle constraints.
- `POST /api/v2/collector/posts` — ingests a normalized `{tweets: [...]}` batch and returns real `new`, `updated`, `duplicate`, and `queued` counts before background model processing.
- `POST /api/v2/collector/heartbeat` — updates in-memory collector state and returns `{accepted: true, persisted: false}`.

`POST /api/ingest/tweets`, `POST /api/heartbeat`, and the two `/api/diagnostics*` routes remain compatibility endpoints for the current Extension. Diagnostic compatibility requests are accepted but not persisted in the V2 core database.

Historical import is deliberately not exposed as an HTTP collector route. `scripts/import_historical_corpus.py` performs explicit local batch imports with dry-run, date/source limits, idempotent evidence keys, checkpoints and batch rollback. It creates no realtime jobs and sends no notification.

## Compatibility and evolution

Alpha 2 is additive within `/api/v2`. Breaking changes require an API version transition; V1 static `public-data` is not an API fallback.
