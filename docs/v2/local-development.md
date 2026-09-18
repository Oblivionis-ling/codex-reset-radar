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

Copy-Item .env.example .env
```

If the preserved V1 environment at `backend/.venv` already satisfies the V2 requirements, the launcher can temporarily use it. A fresh `apps/backend/.venv` is preferred for reproducibility.

## Start and stop

```powershell
.\start-v2-local.bat
```

The launcher starts the Backend and Web as hidden child processes, records their exact PID, process start time, executable, and command line under ignored `runtime/pids/`, and checks both HTTP endpoints. It will not start an unrelated fallback Backend.

```powershell
.\stop-v2-local.bat
```

The stop script acts only on PID records created by this repository and verifies the PID, executable, process start time, and command marker before stopping it. It never kills every `python.exe` or `node.exe` process.

URLs:

- Web: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8787/api/v2`
- Health: `http://127.0.0.1:8787/api/v2/health`

Runtime stdout/stderr is written under `runtime/launcher/`; application JSONL logs are under `runtime/logs/`. Both locations are ignored.

## Validation

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
