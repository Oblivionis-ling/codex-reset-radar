# Operations

## Start

Run `start-radar.bat` from the repository root. It creates the local virtual environment and installs backend dependencies on first use, then starts Uvicorn bound to `127.0.0.1`.

## Stop

Run `stop-backend.bat` from the repository root, or run the PowerShell script directly:

```powershell
.\scripts\stop-backend.ps1
```

The script only matches the Backend started from this repository's
`backend\.venv\Scripts\python.exe/pythonw.exe` with `app.main:app`,
`--app-dir backend`, and port `8787`. It does not stop unrelated Python
processes. The default mode waits for a non-forceful termination request;
if the process does not exit, rerun with `-Force` only when you explicitly
want to force it:

```powershell
.\scripts\stop-backend.ps1 -Force
```

Stopping the process does not delete or modify the SQLite database.

## Verify

- Backend: `http://127.0.0.1:8787/health`
- Health detail: `http://127.0.0.1:8787/api/health`
- Monitor diagnostic timeline: `http://127.0.0.1:8787/api/diagnostics?component=profile_monitor`
- Recent raw Tweets: `http://127.0.0.1:8787/api/tweets`
- Recent alerts: `http://127.0.0.1:8787/api/alerts`
- Local test alert: `POST http://127.0.0.1:8787/api/alerts/test?channel=wxpusher`
- Extension service-worker logs: the extension's service worker **Inspect views** page.

## Unified observability

The local read-only CLI uses the same SQLite database and JSONL event streams
as the Backend:

```powershell
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py summary
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py backend
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py component profile
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py component replies
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py component profile --instance-id <content-instance-id> --limit 100
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py component replies --trace-id <heartbeat-trace-id> --limit 100
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py outage profile
\.\backend\.venv\Scripts\python.exe scripts\diagnose.py trace <trace-id>
```

The corresponding query endpoints are local-only and are not used by GitHub
Pages: `/api/observability/summary`,
`/api/observability/trace/{trace_id}`,
`/api/observability/component/{component}`, and
`/api/observability/errors`. Structured events are under
`backend/data/observability/events/`; the human-readable rotating runtime log
is `backend/data/observability/runtime/backend-runtime.log`.

## Profile / Replies diagnostics

The diagnostic build records browser lifecycle evidence without performing any
automatic recovery. After loading the generated `extension/dist` directory,
click **Reload** in `edge://extensions` and refresh the Profile and
`/thsottiaux/with_replies` tabs. Keep both tabs open while observing:

- `GET /api/health` for the latest heartbeat metadata, including the client
  heartbeat interval, visibility, DOM, Observer, and real `tab_*` fields;
- `GET /api/diagnostics?component=profile_monitor&limit=200` and the equivalent
  `replies_monitor` query for the event timeline;
- the extension Service Worker **Inspect views** console for the same event
  names and delivery failures.

The diagnostic records are evidence only. They do not reload tabs, reopen tabs,
change monitor thresholds, or reconnect a detached Observer.

## Phase C notifications

Keep notification settings in the untracked local `.env` file. Set `ALERT_DRY_RUN=true` while validating the pipeline; set it to `false` only after confirming the dry-run rows and logs. WxPusher requires `WXPUSHER_ENABLED=true`, `WXPUSHER_APP_TOKEN`, and `WXPUSHER_UID`. Windows Toast is controlled independently by `WINDOWS_NOTIFICATIONS_ENABLED=true`.

On every Backend restart, the current Radar state and monitor states are recorded as a notification baseline. The existing historical `CONFIRMED` Radar therefore does not send a notification at startup. Alert delivery failures are persisted in `alerts` and do not stop collection, classification, or Radar updates.

The current live DOM check confirmed Profile Tweet cards, numeric `/status/<id>` links, and Tweet text on the public Profile page. The checked `with_replies` page returned X's reload error, and Search returned the login wall in the current unauthenticated browser state. Those are external state limitations, not silently treated as an empty feed.

The extension alarm setup is idempotent: reloading the Service Worker checks for existing alarms instead of resetting their countdown. After installing or updating the extension, allow roughly 5–10 minutes for the first Search Backfill to finish its UTC windows.

After a new build, click **Reload** for the extension in `edge://extensions`, then refresh the open Profile and Replies tabs so the new content script is injected.

## Failure interpretation

No new Tweet is meaningful only when the corresponding heartbeat is healthy. A stale heartbeat is a monitor warning/offline condition and must be investigated separately.
