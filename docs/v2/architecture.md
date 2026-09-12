# V2 Architecture

## Runtime

```text
X public pages
  -> apps/collector-extension (transitional adapter)
  -> apps/backend (FastAPI)
  -> runtime/data/codex-reset-radar-v2.db
  -> apps/web (Vite, /api/v2 proxy)
```

The Backend owns validation, Reset lifecycle, persistence, and the Radar API. The Web is a presentation client and never reads GitHub-hosted JSON. Collector heartbeats are current-state signals held in Backend memory; routine lifecycle telemetry is not added to the long-term database.

## Runtime boundaries

The V2 lifespan starts only database initialization and bounded local logging. It starts no mirror scheduler, Git worktree, Git push, Pages deployment, DeepSeek Judge, real notification delivery, or server browser.

GitHub is used for source, docs, CI, and version history. The legacy `data` branch is read-only historical material. Active workflows run code validation only.

## Components

- `apps/backend/app`: active V2 Backend.
- `apps/backend/legacy_v1`: archived V1 Backend source; not imported by V2.
- `apps/web`: local Radar product surface and minimal `/ops` placeholder.
- `apps/collector-extension`: existing Profile/Replies/Search collector adapted to V2 compatibility endpoints.
- `scripts/migrate_v1_to_v2.py`: explicit read-only V1 import path.
- `runtime`: ignored V2 state with bounded JSONL logs and PID ownership records.

## Local security model

The default Backend binds to `127.0.0.1:8787`. CORS permits only the configured local Web origins and does not allow credentials. Secrets live only in the ignored root `.env`. The Extension can post to localhost but V2 does not persist browser diagnostic spam.

## Future boundaries

Historical corpus acquisition, the semantic Judge, a server collector, production notifications, Docker/host deployment, and final UI design are separate later phases. Their future presence must not weaken the V2 data or runtime boundaries established here.
