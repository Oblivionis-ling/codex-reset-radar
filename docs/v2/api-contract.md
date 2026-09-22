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

Historical import is deliberately not exposed as an HTTP collector route. The concluded corpus phase
used bounded, local-only import tools with dry-run, idempotent evidence keys, checkpoints and rollback;
those one-time tools are now retired to an ignored local archive. They are not part of a clean checkout
or the active runtime.

## Current result and health metadata

`GET /radar` includes `judgement_id`, `judged_at`, `valid_until`, `validation`
(`valid`, `reason`, optional `details`), `current_data_health`, `judgement_data_health`,
`display_mode`, `last_known_result`, `judge_runtime` and `pipeline`.
`display_mode` is `current`, `model_unknown`, `last_known` or `unavailable`.
Existing but invalid/expired results are not described as never generated. A valid result
based on STALE data stays last-known even after new heartbeats; fresh collection schedules
a new judgement without rewriting history. Last-known colors are not current action advice.

`special_announcements` is separate from `special_resets`: current eligible Banked/reset-card
candidates include candidate/tweet identity, original URL, publication time, summary, scope,
subtype, pending label/status and nullable `scheduled_at`. This view creates no event/cycle.

`GET /health` exposes a shared derived `data_health` and per-collector `reported_state`,
derived `state`, `last_seen_at`, `age_seconds`, `checked_at`, `reason`, instance and sequence
where present. Missing/old heartbeats decay after the existing 15-minute threshold; accepted
client observation time is not replaced by receipt time. Health/Radar GETs are read-only.

### Explicit task endpoints (not configuration checks)

| Method/path | Semantics |
| --- | --- |
| POST `/api/v2/judge/request` | Coalesces a manual Judge request; 503 if model pipeline absent. May call the paid model. |
| POST `/api/v2/posts/{tweet_id}/reprocess` | Known-post reprocessing, identical semantic input reuses caches; 404 unknown post, 503 absent pipeline. |
| POST `/api/v2/context/claim` | Claims an existing context task/lease; returns `job` or null. |
| GET `/api/v2/context/cache/{tweet_id}` | Returns context-only cached `node` or null. |
| POST `/api/v2/context/retry/{tweet_id}` | Explicit retry of a known reply's non-running context task; does not fabricate context. |
| POST `/api/v2/context/result` | Accepts task `id`, `lease`, `nodes`, optional `reason`; validates lease/context, returns `accepted`; meaningful changed inputs enqueue existing processing. |

The claim/retry/result endpoints mutate task state. They are not health probes. Result payload
shape is validated by the context implementation; malformed input returns 422. The posts API
includes `reply_context` and `context_acquisition` alongside analysis/translation status.

### Evolution boundary

Alpha 4 is additive within `/api/v2`. Breaking changes require an API version transition; V1 static `public-data` is not an API fallback.

### Optional decision provenance

Radar adds `decision` with `decision_engine` (`laya`, `deepseek`, or
`deepseek_fallback`), `decision_mode`, `question_schema`, `evidence_prompt`,
`fallback_reason`, `forecast_candidate_id` and `decision_package_hash`.
Legacy rows can have null provenance. Probabilities and full evidence packages
are not returned by this view. `DECISION_MODE_CHANGED` / `DECISION_CONFIG_CHANGED`
invalidate incompatible results; they do not rewrite historical rows.
All existing expiry, generation-vs-current health, input-version and cycle rules
remain in force. The optional feature is not a claim of production acceptance.
