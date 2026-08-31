# Public Data Mirror Contract

`public-data/` is a deliberately narrow, static export for a future GitHub Pages consumer. It is not a backup of the local database and it is not required by the collector, classifier, Radar, or notification path.

## Files

- `index.json` — schema version, generation time, Tweet/classification counts, category counts, and the list of mirror files.
- `tweets.json` — public Tweet fields, source names, and the latest `final` classification only.
- `radar.json` — current public Radar state, forecast, usage advice, and public trigger Tweet ID.
- `health.json` — public component state and heartbeat timestamps only.
- `resets.json` — confirmed Reset history, Beijing-time fields, interval labels, and lightweight time distribution.

`tweets.json` keeps the original `text` unchanged and may include the best-effort
`translation_zh`, `translation_model`, `translation_version`, and `translated_at`
display fields. A missing translation is represented by `null` and never removes the
English original.

`radar.json.forecast` contains `last_reset_at`, `baseline_next_reset_at`,
`signal_window`, `estimated_next_reset_at`, `forecast_source`, and
`forecast_reason`. The baseline is explicitly `last confirmed reset + 7 days`;
an active `reset_hint` with `within_24h` or a parseable explicit announcement may
override it. `radar.json.usage_advice` contains the public `level`, `title_code`,
and `reason_code` used by the Dashboard.

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
