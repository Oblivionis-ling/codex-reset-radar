# Codex Reset Radar — Public Data

This directory is a development/sample snapshot. The live GitHub Pages Dashboard reads the independent `data` branch.

- `index.json` describes the snapshot and counts.
- `tweets.json` contains public Tweet fields and the latest final classification.
- `radar.json` contains the current public Radar state.
- `health.json` contains component state and heartbeat timestamps.
- `meta.json` describes the mirror branch and snapshot synchronization time.

It is not a backup of the local SQLite database. Secrets, notification delivery details, browser diagnostics, AI usage, and local operational records are intentionally excluded.

Runtime sync is performed by `scripts/sync-github-data.ps1` and does not update `main/public-data`.
