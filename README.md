# Codex Reset Radar

Codex Reset Radar is a local-first, full-stack system for answering one practical question:

> Is the next Codex Reset approaching?

It collects Tibo's public X posts, preserves reset history, and exposes a stable product contract for a future semantic judge. The repository is the source, documentation, CI, and version history; GitHub is not part of the V2 runtime data path.

## V2 status

The current release target is **V2 Foundation Alpha 1** (`2.0.0-alpha.1`). It provides:

- a FastAPI Backend with a new isolated SQLite schema;
- a local Vite Web app that reads only `/api/v2/*`;
- the existing browser Extension as a transitional collector adapter;
- bounded local JSONL logs and in-memory collector heartbeat state;
- read-only V1 post migration with explicit Reset review candidates;
- one-command local start and project-scoped stop scripts.

The DeepSeek Judge, historical corpus, server collector, final UI, notification redesign, and overseas deployment are intentionally outside this alpha.

The repository's `main` branch is the V2 local full-stack source. GitHub provides source history and CI only; it is not a live product endpoint.

## Architecture

```text
X public pages
    |
    v
Transitional Collector Extension
    |
    v
Local FastAPI Backend ----> V2 SQLite
    |
    v
Local Vite Web
```

No active V2 process reads `raw.githubusercontent.com`, writes the `data` branch, deploys Pages, or uses Git as a runtime database.

## Repository structure

```text
apps/backend/               V2 API, database, tests, and V1 source archive
apps/web/                   V2 local Dashboard foundation
apps/collector-extension/   transitional Manifest V3 collector adapter
docs/v1/                    V1 reports, contracts, and static-data snapshot
docs/v2/                    V2 product and engineering contracts
legacy/v1/                  V1 operational scripts and launchers
scripts/                    V2 migration and local lifecycle scripts
backend/data/               local legacy V1 data; ignored and preserved
runtime/                    generated V2 database, logs, and PID records
data/analysis/              generated migration review artifacts; ignored
```

## Local development

From the repository root, install the Backend, Web, and Extension dependencies as described in [Local development](docs/v2/local-development.md). Then run:

```powershell
.\start-v2-local.bat
```

Local endpoints:

- Web: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8787/api/v2`
- Health: `http://127.0.0.1:8787/api/v2/health`

Stop only the recorded V2 processes with:

```powershell
.\stop-v2-local.bat
```

## Data policy

Long-lived V2 data is limited to public Tibo posts, verified Full/Special Reset events, structured post analysis, necessary Radar judgements, and reviewed analysis artifacts. Routine heartbeats, request traces, browser lifecycle spam, timer ticks, logs, credentials, databases, and build artifacts are not committed.

The legacy V1 database under `backend/data/` remains local and read-only until migration review is complete. The GitHub `data` branch is a frozen legacy runtime snapshot: V2 neither reads it nor publishes new data to it.

## Radar product model

- Action levels: `GREEN`, `YELLOW`, `ORANGE`, `RED`
- Insufficient evidence: `UNKNOWN`, displayed as white
- Horizons: `24H`, `48H`, `72H`
- Special Reset events: displayed uniformly as `PURPLE`
- Full Reset: a historical event that opens a new Reset cycle, not a persistent risk level
- Confidence percentages: not part of the public V2 contract

Alpha 1 correctly returns `UNKNOWN` until a later Judge is enabled. See [Product model](docs/v2/product-model.md).

## V1 legacy snapshot

The final V1 working state is preserved by the branch `archive/v1-final-2026-09-13` and annotated tag `v1-final-snapshot-2026-09-13`. Its local Backend → GitHub data branch → GitHub Pages architecture is archived and no longer developed as the active product runtime.

Historical reports and source remain available under `docs/v1/`, `legacy/v1/`, and `apps/backend/legacy_v1/` on the V2 branch. Local V1 data is preserved but never committed.

## Deployment plan

V2 is validated as a complete local stack first. A later phase may deploy the Backend, database, Web, and future server collector to an overseas server. Docker, reverse proxy, TLS, domains, and production secrets are not part of Alpha 1.

## Security

- Never commit `.env`, API tokens, cookies, browser profiles, SQLite files, runtime logs, or generated corpora.
- Copy `.env.example` to `.env` only for local configuration.
- The Alpha 1 runtime does not send real notifications or call a semantic Judge.
- Tests use data explicitly labelled as synthetic fixtures; the repository must not invent Reset history or Tibo posts.

## Validation

Run from the repository root:

```powershell
backend\.venv\Scripts\python.exe -m pytest apps\backend\tests -q
cd apps\web
npm ci
npm test
npm run typecheck
npm run build
cd ..\collector-extension
npm ci
npm test
npm run typecheck
npm run build
```

GitHub Actions performs the same Backend, Web, and Collector checks. It does not host the Dashboard or publish runtime data.
