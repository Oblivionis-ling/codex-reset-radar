# V2 API Contract

Base URL: `http://127.0.0.1:8787/api/v2`

## Product reads

- `GET /health` — application version/commit, database readiness/counts, ephemeral collector state, and explicit runtime flags showing that GitHub mirror and Pages dependencies are disabled.
- `GET /radar` — Action Level, 24/48/72 horizons, data health, reason, next-reset baseline, last Full Reset, and recent Special Resets.
- `GET /posts?limit=20` — normalized recent Tibo posts.
- `GET /resets?limit=50` — canonical Reset events and current last Full Reset.

The Radar response accepts only `GREEN`, `YELLOW`, `ORANGE`, `RED`, and `UNKNOWN`. It never exposes confidence or confidence percentage. With no Judge, it returns white `UNKNOWN`; with no verified Full Reset, `next_reset.status` is `waiting_for_verified_history`.

## Controlled writes

- `POST /api/v2/resets` — records an explicitly supplied canonical Full/Special Reset and applies lifecycle constraints.
- `POST /api/v2/collector/posts` — ingests a normalized `{tweets: [...]}` batch from the transitional collector.
- `POST /api/v2/collector/heartbeat` — updates in-memory collector state and returns `{accepted: true, persisted: false}`.

`POST /api/ingest/tweets`, `POST /api/heartbeat`, and the two `/api/diagnostics*` routes remain compatibility endpoints for the current Extension. Diagnostic compatibility requests are accepted but not persisted in the V2 core database.

## Compatibility and evolution

Alpha 1 is an explicit contract boundary, not the final Judge implementation. Additive changes may be made in future alpha versions. Breaking changes require an API version transition; V1 static `public-data` is not an API fallback.
