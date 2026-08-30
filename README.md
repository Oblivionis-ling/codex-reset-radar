# Codex Reset Radar

Personal, local-first monitoring of Tibo (`@thsottiaux`) on X. Phase A provides reliable browser collection, SQLite ingestion/deduplication, health heartbeats, and Latest-search reconciliation. Phase B now adds transparent classification, bounded context, optional DeepSeek semantic review, and Radar State.

## Current progress

- [x] Milestone 0 — scaffold, architecture, SQLite schema, readable logging, `/health`
- [x] Milestone 1 — MV3 Profile/Replies DOM collector, local ingestion, deduplication, fallback scan, heartbeat
- [x] Milestone 2 — 72-hour Latest search backfill, UTC day windows, reconciliation
- [x] Milestone 3 — transparent Rule Classifier
- [x] Milestone 4 — DeepSeek Provider with structured validation and fallback
- [x] Milestone 5 — bounded SQLite Context Engine
- [x] Milestone 6 — audited Rule/AI Final Resolver
- [x] Milestone 7 — Radar State and expiry engine
- [x] DeepSeek live calls — Phase B.5 calibrated backfill and acceptance completed
- [x] Phase C core — Alert Manager, notification channels, deduplication, baseline, escalation, and monitor alerts
- [x] Phase C acceptance — WxPusher delivery and Windows Toast verified locally
- [x] Profile / Replies SPA Route Fix — context-preserving status navigation verified
- [x] Phase D local mirror — allow-listed public data export and GitHub sync script
- [x] GitHub Pages Dashboard — static UI on GitHub Pages
- [x] Phase E.5 live data branch and freshness-aware Health semantics

GitHub Pages hosts the static Dashboard. Live public JSON is published to the independent `data` branch; the local Collector, Backend, SQLite, Radar, and notifications continue to run on the Windows machine and do not depend on GitHub.

## Quick start on Windows

1. Copy `.env.example` to `.env` and adjust only local settings if needed.
2. Run `start-radar.bat`.
3. In Chrome or Edge, open `chrome://extensions` or `edge://extensions`, enable Developer mode, choose **Load unpacked**, and select `extension/dist` after building the extension.
4. Sign in to X, open `https://x.com/thsottiaux`, and keep the browser running.
5. For Phase C notifications, configure the local `.env` using the variables described in `docs/phase-c-progress-report.md`; never commit the App Token or UID.

The backend listens on `http://127.0.0.1:8787`. Check `http://127.0.0.1:8787/health`.

## Build and test

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
\.venv\Scripts\python.exe -m pytest -q

cd ..\extension
npm install
npm test
npm run build

cd ..\backend
.\.venv\Scripts\python.exe classify_existing.py
```

See [docs/architecture.md](docs/architecture.md), [docs/data-model.md](docs/data-model.md), and [docs/operations.md](docs/operations.md) for the current implementation and known collector limits.

The live mirror design and Phase E.5 acceptance record are documented in [docs/live-data-mirror.md](docs/live-data-mirror.md) and [docs/phase-e5-progress-report.md](docs/phase-e5-progress-report.md).

## Public data mirror

The tracked `public-data/` directory contains only sanitized Tweet, final classification, Radar summary, and component health snapshots. It does not contain the local SQLite database, diagnostic telemetry, notification records, AI usage, or credentials.

After the Backend has produced current data and the repository remote is configured, update the live data branch with:

```powershell
.\scripts\sync-github-data.ps1
```

The sync script reads SQLite in read-only mode, stages only the five sanitized JSON files in a temporary data-branch worktree, and pushes through the authenticated Git remote. It never switches the active development worktree or updates `main/public-data/`. A GitHub outage does not interrupt the local radar.

The Backend runs the same sync in a lightweight 5-minute background loop, with event-triggered sync requests for new Tweets, high-value classifications, Radar changes, and monitor state changes. GitHub failures are logged and retried at most three times per sync cycle; they do not interrupt collection, classification, Radar, SQLite, or notifications.

Collector verification and the current leak-risk assessment are recorded in [docs/collector-test-results.md](docs/collector-test-results.md).

Phase B classification results are recorded in [docs/phase-b-classification-report.md](docs/phase-b-classification-report.md). Phase B.5 calibration and acceptance materials are in [docs/phase-b5-progress-report.md](docs/phase-b5-progress-report.md), [docs/phase-b5-review-table.md](docs/phase-b5-review-table.md), and [docs/phase-b5-classification-report.md](docs/phase-b5-classification-report.md).
