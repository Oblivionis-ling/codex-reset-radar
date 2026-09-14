# Migration from V1

## Safety policy

`backend/data/radar.db` is preserved as local legacy data and must not be changed or committed. The migration utility opens it with SQLite `mode=ro`, writes only to the separate V2 database, and generates an ignored review artifact.

## Run

From the repository root:

```powershell
apps\backend\.venv\Scripts\python.exe scripts\migrate_v1_to_v2.py
```

Defaults:

- source: `backend/data/radar.db`
- target: `runtime/data/codex-reset-radar-v2.db`
- review candidates: `data/analysis/v1-reset-migration-candidates.json`

All paths can be overridden with `--source`, `--target`, and `--candidates`.

## Semantics

- Posts are normalized and deduplicated by `tweet_id`.
- Existing V2 posts can be updated idempotently without creating duplicates.
- V1 `reset_confirmed` classifications become `REQUIRES_PROVENANCE_REVIEW` candidates only.
- The utility does not create canonical `reset_events`, Full Reset cycles, Radar judgements, or fabricated history.
- Consequently, the initial V2 Radar remains `UNKNOWN` and the next-reset baseline remains `waiting_for_verified_history`.

Before promoting any candidate, verify its original public post, event meaning, time, and provenance. Candidate review and historical corpus construction are later phases.
