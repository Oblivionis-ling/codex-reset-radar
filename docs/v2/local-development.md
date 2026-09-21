# Local Development

Run all commands from the repository root on Windows.

## Prerequisites

- Python 3.12 (3.11+ is expected to work)
- Node.js 20+
- npm
- Edge or Chrome only when exercising the transitional collector

## First-time setup

```powershell
py -3 -m venv apps\backend\.venv
apps\backend\.venv\Scripts\python.exe -m pip install -r apps\backend\requirements.txt

cd apps\web
npm ci
cd ..\collector-extension
npm ci
cd ..\..

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

The launcher uses only `apps/backend/.venv/Scripts/python.exe`. It fails with setup instructions
when that environment is missing; there is no silent fallback to the old V1 environment.
Do not copy or move an existing virtual environment between paths: recreate it from dependencies.

Build the Collector with `npm run build` in `apps/collector-extension`, then use Edge's extensions
page (Developer mode, Load unpacked) to select the absolute project `apps/collector-extension/dist`.
Verify the extension details show that directory; a successful disk build alone does not prove it.
Keep the signed-in Profile `https://x.com/thsottiaux` and Replies
`https://x.com/thsottiaux/with_replies` pages available. After an explicit extension update, reload
the extension and refresh those pages. Do not close the daily browser or export cookies.

## Start and stop

```powershell
.\start-v2-local.bat
```

The launcher asks the Windows WMI service to create a hidden launcher outside the calling terminal or Codex app's process lifetime. That launcher starts Backend and Web, records their exact PID, process start time, executable, and command line under ignored `runtime/pids/`, and checks both HTTP endpoints. Closing or updating the calling app does not own these new processes. Existing healthy project processes are reused; after upgrading from the old launcher, run stop then start once to replace old processes. A WMI failure is reported without silently falling back to attached child processes.

This is an on-demand launch, not a Windows service, auto-start task, or crash watchdog. Windows logout/reboot still requires starting the project again. No account password or administrator task registration is required. Startup diagnostics are appended to `runtime/launcher/startup.log`; previous stdout/stderr files are timestamped before a fresh launch so restart does not erase the previous exit evidence.

```powershell
.\stop-v2-local.bat
```

The stop script acts only on PID records created by this repository and verifies the PID, executable, process start time, and command marker before stopping it. It never kills every `python.exe` or `node.exe` process.

URLs:

- Web: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8787/api/v2`
- Health: `http://127.0.0.1:8787/api/v2/health`

Runtime stdout/stderr is written under `runtime/launcher/`; application JSONL logs are under `runtime/logs/`. Both locations are ignored.

The database is `runtime/data/codex-reset-radar-v2.db`; preserve its SQLite sidecars while running.
Health GETs do not create heartbeats or call the model. Log retention does not apply to corpus,
backups, decisions or fixed acceptance evidence. Data policy: [local assets](../../data/README.md).

## Validation

Windows launcher isolation regression (harmless test processes only; no model calls):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test-v2-detached-launch.ps1
```

It kills the test caller's process tree and verifies that the WMI-created test process survives. It cleans up its own probe afterwards. This tests process isolation without closing the user's Codex session.

```powershell
apps\backend\.venv\Scripts\python.exe -m pytest apps\backend\tests -q

cd apps\web
npm test
npm run typecheck
npm run build

cd ..\collector-extension
npm test
npm run typecheck
npm run build
```

Alpha 4 requires `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` for the intelligence pipeline. An `UNKNOWN` result is valid only when the API also explains whether evidence is insufficient, processing is still running, the result is stale, or the model request failed. Verify in browser developer tools that the Web requests only localhost `/api/v2/*`; there must be no Raw GitHub, data-branch, or Pages request.

Notification preparation is optional and does not affect Backend startup. Use
`test-notifications.bat` and [the notification testing guide](../notifications/testing-guide.md);
status, check, preview and selftest never send real messages.
