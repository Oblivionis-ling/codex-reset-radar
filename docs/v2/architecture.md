# V2 Architecture

## Runtime

```text
X public pages
  -> apps/collector-extension (transitional adapter)
  -> apps/backend (FastAPI)
       -> persistent processing jobs
       -> DeepSeek post analysis / translation
       -> verified Reset events / candidates
       -> debounced and hourly DeepSeek Judge
  -> runtime/data/codex-reset-radar-v2.db
  -> apps/web (Vite, /api/v2 proxy)
```

The Backend owns validation, Reset lifecycle, persistence, and the Radar API. The Web is a presentation client and never reads GitHub-hosted JSON. Collector heartbeats are current-state signals held in Backend memory; routine lifecycle telemetry is not added to the long-term database.

## Runtime boundaries

The V2 lifespan starts database initialization, bounded local logging, two local processing workers, and the debounced/hourly DeepSeek Judge when credentials are configured. It starts no mirror scheduler, Git worktree, Git push, Pages deployment, real notification delivery, or server browser.

GitHub is used for source, docs, CI, and version history. The legacy `data` branch is read-only historical material. Active workflows run code validation only.

## Components

- `apps/backend/app`: active V2 Backend.
- `legacy/v1/backend`: archived V1 Backend source; not imported by V2.
- `apps/web`: local Radar product surface and minimal `/ops` placeholder.
- `apps/collector-extension`: existing Profile/Replies/Search collector adapted to V2 compatibility endpoints.
- `scripts/migrate_v1_to_v2.py`: explicit read-only V1 import path.
- one-time historical import and repair tools are retired to an ignored local archive after corpus
  closeout; active product code has no dependency on them.
- `apps/backend/app/notifications`: prepared, disabled-by-default transports for explicit manual
  tests; they are not connected to Reset/Judge events.
- `runtime`: ignored V2 state with bounded JSONL logs and PID ownership records.

## Reply context acquisition

`REPLY_CONTEXT` jobs share the existing persistent processing queue. The extension claims a
90-second lease, uses cached canonical/context bodies first, and manages at most one inactive
owned X detail tab. A document-start MAIN-world observer reads only the normal page's
TweetDetail/TweetResultByRestId responses. It never obtains cookies/tokens or synthesizes API
requests. Direct relations come from `in_reply_to_status_id_str`, not conversation roots, DOM
adjacency, quoted links or model guesses. Unavailable structured responses remain an explicit
failure; the collector does not substitute whole-page UI text.

Depth is capped at three ancestors and the combined submitted text at 12,000 characters.
Backend attempts are capped at three; temporary failures back off five minutes. A restarted
extension can recover its recorded owned tab and Backend lease. User navigation revokes tab
ownership. Login/ownership failures pause until explicit retry. The helper has no Profile,
Replies or Search identity. Normal heartbeat and ingestion continue independently.

Analysis waits at most 100 seconds for an initial context attempt, then uses explicit missing
context. Model `context_sufficient=false` blocks event promotion. Parent authors are separate
from Tibo, and parent posts alone never create events. Analysis/translation receive the same
structured context; Judge receives it with the versioned analysis. Input versions invalidate
old results and late model results are discarded before promotion. Previously reviewed events
are preserved and conflicting context reanalysis is recorded for review.

Live browser contract verification is tracked in
[the historical reply-context report](../archive/incidents/reply-context-fix-report.md) and
[current repair acceptance](../maintenance/judge-context-and-health-fix-report.md); offline tests are not delivery evidence.

## Local security model

The default Backend binds to `127.0.0.1:8787`. CORS permits only the configured local Web origins and does not allow credentials. Secrets live only in the ignored root `.env`. The Extension can post to localhost but V2 does not persist browser diagnostic spam.

## Future boundaries

Further corpus verification, a server collector, production notification wiring, Docker/host deployment, and
final UI design remain separate later phases. Their future presence must not weaken the V2 data or
runtime boundaries established here.

## Corpus review boundary

The versioned `crr-corpus-v1` format is an interchange and review boundary around the existing database,
not a second application architecture. Isolated historical replay imports standard records through the
normal ingest and persistent task pipeline, uses the current DeepSeek analysis/translation/Judge path,
and writes only below `runtime/review`. GPT reference labels are never loaded into the replay database or
production retrieval context.
