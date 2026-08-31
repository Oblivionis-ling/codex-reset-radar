# Codex Reset Radar — Public Data

This directory is a development/sample snapshot. The live GitHub Pages Dashboard reads the independent `data` branch.

- `index.json` describes the snapshot and counts.
- `tweets.json` contains public Tweet fields, the latest final classification, and optional `translation_zh` display text.
- `radar.json` contains the current public Radar state, Reset forecast, and quota usage advice.
- `health.json` contains component state and heartbeat timestamps.
- `resets.json` contains confirmed Reset history and Beijing-time statistics.
- `meta.json` describes the mirror branch and snapshot synchronization time.

It is not a backup of the local SQLite database. Secrets, notification delivery details, browser diagnostics, AI usage, and local operational records are intentionally excluded.

Runtime sync is performed by `scripts/sync-github-data.ps1` and does not update `main/public-data`.
