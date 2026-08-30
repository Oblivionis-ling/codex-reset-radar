# Public Data Mirror Contract

`public-data/` is a deliberately narrow, static export for a future GitHub Pages consumer. It is not a backup of the local database and it is not required by the collector, classifier, Radar, or notification path.

## Files

- `index.json` — schema version, generation time, Tweet/classification counts, category counts, and the list of mirror files.
- `tweets.json` — public Tweet fields, source names, and the latest `final` classification only.
- `radar.json` — current public Radar state and its public trigger Tweet ID.
- `health.json` — public component state and heartbeat timestamps only.

## Explicitly excluded

The exporter never copies:

- `.env`, API keys, WxPusher identifiers, passwords, or credentials;
- `backend/data/radar.db` or any SQLite journal/WAL file;
- `monitor_diagnostic_events`, including Tab IDs, window IDs, URLs with query state, and browser lifecycle telemetry;
- `alerts`, notification baseline, or delivery details;
- `ai_usage`, prompt payloads, sync queue data, or internal operational logs;
- raw Rule/AI audit history beyond the latest public `final` classification.

The exporter reads SQLite through a read-only connection, uses an explicit field allow-list, canonicalizes Tweet URLs, and redacts any configured known Secret values if they appear unexpectedly in text or reason fields.

## Operational boundary

The mirror is best-effort and outbound-only. `scripts/sync-github-mirror.ps1` runs the exporter, stages only `public-data/`, and pushes through the already authenticated Git remote. A GitHub outage cannot stop the local Backend, Extension, SQLite, Radar, or notifications because none of those paths imports the mirror script.
