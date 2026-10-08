# V2 API Contract

Base URL: `http://127.0.0.1:8787/api/v2`

The confirmed prediction semantics are defined in [CRR 日期预测与复盘规范](prediction-and-review-spec.md). Production remains Alpha5 / main `1e865c37d1643f429162adeb0fab61bb7371a47b`. The isolated three-line development contract below passed final offline acceptance against code manifest `1c7a29ad…` (Backend 318/0/0, Web 17, Collector 18, type checks and builds). It is not deployed. See the [current report](../maintenance/prediction-three-lines-v1-report.md).

## Prediction review export boundary

The Ledger baseline contains a local `prepare` / `preview` / `export` / `verify` CLI and did not
add an HTTP route. The current branch adds the read projection and history route described
below. Schema 8, the reader/exporter and these extensions have not been enabled in production.

The CLI requires an existing SQLite database and opens it read-only; it does not initialize or
migrate the source. Review selection, freeze cutoff, ledger high-water, dependency closure, legacy
gaps, and export capabilities are reported in the local preview/package, not exposed through this
API. The [operations guide](prediction-review-operations.md) documents the isolated CLI and its
limits.

OPEN [Ledger PR #10](https://github.com/Oblivionis-ling/codex-reset-radar/pull/10), head `ef226ebe...`,
is the dependency. Its historical Backend 140 / Web 7 / Collector 18 results and CI are baseline
evidence, not this round's results. Scoring and export remain explicit local actions; neither a
health GET nor a package-verification result constitutes model or prediction-quality acceptance.

## Product reads

- `GET /health` — version/commit, database counts, ephemeral collector state, pipeline/Judge state, pending jobs, corpus inventory, and disabled GitHub runtime flags.
- `GET /radar` — persisted Judge ID/state/validity, Action Level, 24/48/72 horizons, evidence IDs, selected historical case IDs/corpus version, signal time range, next-reset baseline, last Full Reset, and recent Special Resets.
- `GET /posts?limit=20` — recent posts with source text, Chinese translation, analysis and per-stage status.
- `GET /resets?limit=50` — canonical events, current last Full Reset, and explicitly separated review candidates.

The Radar response accepts only `GREEN`, `YELLOW`, `ORANGE`, `RED`, and `UNKNOWN`. It never exposes confidence or confidence percentage. `judgement_state` distinguishes processing, failed, stale, blocked and ready. With no verified Full Reset, `next_reset.status` is `waiting_for_verified_history`; an elapsed +7-day reference is `expired` and is never rolled forward automatically.

## Three-line read extension (development contract)

The development `/radar` response adds `prediction` with version `prediction-three-lines-v1` and
algorithm version `three-lines-time-v1`. Existing `estimated_start/end`, horizons, cycle and
`next_reset` fields retain their Full meanings. Final empty-DB API smoke returned health/Radar and
each target history successfully; the database remained byte-identical through CLI use.

| Projection field | Read contract |
| --- | --- |
| `version`, `algorithm_version`, `state` | Explicit projection identity and overall availability/partial-failure state. |
| `capabilities` | Boolean `normal_weekly`, `extra_full`, `banked`, `history` support flags; support does not prove that historical source records exist. |
| `health` | Current collection health, generation health and global judgement validation remain visible. |
| `lines` | Separate entries keyed by `NORMAL_WEEKLY`, `EXTRA_FULL`, `BANKED`; each retains its own availability and validity. |
| Per-line time/source | `form`, nullable `predicted_start/end`, `expression`, `source_timezone`, `precision`, `time_basis`, relative anchor/unresolved reason, `method` and Normal `basis`. |
| Per-line lineage | Forecast/series/revision/previous links, update time, nullable `output_available_at` and availability kind. |
| Per-line eligibility | State, validity, health, `current_advice_eligible` and an explanation when the record is only a historical reference. |

Compatibility absence and a valid returned model UNKNOWN are separate contracts. A legacy Judge
without Banked output, an unavailable projection, a missing target field or unrecorded history must
retain its absence/rejection reason; it must not be labelled as a historical model UNKNOWN. Only an
accepted target response explicitly declaring UNKNOWN can support that model state. Errors and
reasons use safe summaries, and the read API does not expose raw Ledger payloads or model requests.

`GET /api/v2/predictions/history` is the development history entry point. Query parameters are optional
`target` (one of the three target IDs), optional `series_id` and `limit` (default 100, range 1–200).
The response carries `version`, `state`, selection fields, `items`, `total_count`,
`total_count_known`, `truncated` and a safe reason. `items` must contain flat, target-specific
prediction DTOs with `item_schema=prediction-history-line-v1`, stable lineage and time/source
fields. The safe Ledger getter supplies first/last record IDs, singular/plural boundary items,
`source_output_count`, `truncated`, `attempts_truncated` and safe `prediction-attempt-v1`
summaries. Ordering is `append_sequence_not_proven_temporal_or_pre_event_order`, not scorer
first/last pre-event selection. Raw rows with a nested `payload` are not a history DTO.
First, intermediate and latest versions remain distinguishable; truncation does not claim
complete coverage. Final empty-DB smoke returned 200 with zero items and the flat schema for all
three targets; invalid targets returned 422. Populated UI review used a separate formal06 clone.

Final clean acceptance covers official-source/time-expression protection, relative anchors, legacy
expiry/absence and flat history. Synthetic A and real legacy B packages independently verified
their assessment/reference bindings. The isolated UI review showed seven history items and the
expected stale/Normal/Banked distinctions. The UI clone was from formal06, not the final formal07
scoring sample; its screenshot was not persisted. Old candidate failures remain historical and
are not relabelled. These reads do not trigger a model request, notification or scoring write.

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

Judge input snapshots and per-Tweet versions are stored internally for validation; the Radar API
does not expose model request bodies or raw snapshots. A changed or missing source version makes
the stored result invalid with a concrete validation reason rather than silently repairing evidence.

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

Alpha 5 is additive within `/api/v2`. Breaking changes require an API version transition; V1 static `public-data` is not an API fallback.
