# Live Mirror Timing Logs

## Purpose

The mirror and Dashboard now keep separate timing records so an old public
snapshot can be distinguished from a delayed Dashboard request or a failed
GitHub publish.

The timing chain is:

```text
Backend export
  -> Backend push completed (sync_finished_at)
  -> public-data/meta.json mirror_synced_at
  -> Dashboard request started
  -> each public JSON response received
  -> Dashboard refresh completed and data selected for display
```

## Backend log

The Backend appends one JSON object per line to:

```text
backend/data/mirror-cadence.jsonl
```

This path is local-only and is ignored by Git. It is created on the first
mirror cycle after the current Backend starts.

Important fields:

- `event`: `PUBLIC_MIRROR_CYCLE_STARTED`, `PUBLIC_MIRROR_EXPORT_COMPLETED`,
  `PUBLIC_MIRROR_PUSH_STARTED`, `PUBLIC_MIRROR_SYNC_SUCCESS`,
  `PUBLIC_MIRROR_SYNC_FAILED`, or `PUBLIC_MIRROR_SYNC_SKIPPED`.
- `source`: `scheduler` for the local scheduler record, or `sync-script` for
  the PowerShell export/push event.
- `cycle_started_at`: when this scheduled or event-triggered cycle began.
- `sync_finished_at`: when the export/push stage reported completion. For a
  successful push this is the Backend-side publish completion time.
- `mirror_synced_at`: the public snapshot timestamp written into `meta.json`.
- `duration_ms`, `trigger`, `result`, `push_attempt`, and failure `reason` when
  available.
- `logged_at`: when the Backend appended the record locally.

The log only persists timing and safe status fields. Credential values and
command output are not written to this file.

PowerShell inspection:

```powershell
Get-Content .\backend\data\mirror-cadence.jsonl -Tail 20
```

## Dashboard log

Because GitHub Pages is a static site and cannot write to the repository or
the local machine, the browser stores Dashboard timing records in:

```text
localStorage["codex-reset-radar-refresh-log"]
```

The Dashboard retains the most recent 100 refreshes and also writes the
current structured object to the browser console as `DASHBOARD_REFRESH_LOG`.

Each refresh record contains:

- `refresh_started_at`: when the Dashboard began loading the six public JSON
  files.
- `dashboard_received_at`: when all requests completed and the Dashboard was
  ready to render the refresh result.
- `duration_ms`: elapsed time for that refresh.
- `mirror_synced_at`: the source timestamp reported by the selected data.
- `used_snapshot_at`: the source timestamp of the data actually kept for
  display, including the previous successful file for a partial refresh.
- `result`: `success`, `partial`, or `failed`.
- `files`: one entry for `index`, `tweets`, `radar`, `health`, `meta`, and
  `resets`, including `request_started_at`, `response_received_at`, HTTP
  `status`, `ok`, and an error when applicable.

The home page also displays the latest `dashboard_received_at` beside the
source mirror timestamp. This is informational only and does not change the
15-minute data freshness rule.

Browser console inspection:

```js
JSON.parse(localStorage.getItem("codex-reset-radar-refresh-log") || "[]")
```

## Correlation procedure

1. Take the latest Backend `PUBLIC_MIRROR_SYNC_SUCCESS` record from
   `source=sync-script` and note `sync_finished_at` and `mirror_synced_at`.
2. Find a Dashboard refresh whose `files` entry for `meta` has the matching
   `response_received_at` window.
3. Compare that record's `dashboard_received_at` with the Backend publish
   time. A fresh Dashboard can still show a stale source if the public branch
   itself has not been updated.
4. If `meta` has no response timestamp or has an HTTP/network error, the
   problem is between the Dashboard and the public data source, not the local
   Backend scheduler.
