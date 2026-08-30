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
- [ ] GitHub Pages Dashboard — intentionally deferred

The Dashboard is intentionally not included yet. GitHub is a source-code host and best-effort public data mirror; the local Collector, Backend, SQLite, Radar, and notifications do not depend on it.

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

## Public data mirror

The tracked `public-data/` directory contains only sanitized Tweet, final classification, Radar summary, and component health snapshots. It does not contain the local SQLite database, diagnostic telemetry, notification records, AI usage, or credentials.

After the Backend has produced current data and the repository remote is configured, update the mirror with:

```powershell
.\scripts\sync-github-mirror.ps1
```

The sync script reads SQLite in read-only mode, stages only `public-data/`, and pushes through the authenticated Git remote. A GitHub outage does not interrupt the local radar.

Collector verification and the current leak-risk assessment are recorded in [docs/collector-test-results.md](docs/collector-test-results.md).

Phase B classification results are recorded in [docs/phase-b-classification-report.md](docs/phase-b-classification-report.md). Phase B.5 calibration and acceptance materials are in [docs/phase-b5-progress-report.md](docs/phase-b5-progress-report.md), [docs/phase-b5-review-table.md](docs/phase-b5-review-table.md), and [docs/phase-b5-classification-report.md](docs/phase-b5-classification-report.md).
