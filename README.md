# Codex Reset Radar

Codex Reset Radar V2 is a local-first system that collects Tibo's public X posts, analyses Reset
signals, maintains verified Reset events and exposes the current Radar through a local Dashboard.

Current accepted release: **V2 Local Intelligence Alpha 4** (`2.0.0-alpha.4`). The active runtime is
local only; GitHub is source history and CI, not a data path.

## Start here

- [Local start, stop and validation](docs/v2/local-development.md)
- [Current architecture](docs/v2/architecture.md)
- [V2 API contract](docs/v2/api-contract.md)
- [Data and corpus standard](docs/v2/corpus/corpus-standard.md)
- [Notification preparation](docs/notifications/README.md)
- [Notification user test guide](docs/notifications/testing-guide.md)
- [Notification preparation and cleanup report](docs/maintenance/notification-prep-and-cleanup.md)
- [Corpus phase closeout](docs/v2/corpus/corpus-closeout-report.md)

Historical V1 material remains under `docs/v1/`. Concluded V2 corpus reports remain under
`docs/v2/corpus/` so immutable manifests and evidence links keep their original paths.

## Local runtime

```text
X public pages
    -> apps/collector-extension
    -> apps/backend (FastAPI + DeepSeek pipeline)
    -> runtime/data/codex-reset-radar-v2.db
    -> apps/web (local Dashboard)
```

Start and stop from the repository root:

```powershell
.\start-v2-local.bat
.\stop-v2-local.bat
```

- Web: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8787/api/v2`
- Health: `http://127.0.0.1:8787/api/v2/health`

The stop command validates project PID records and never kills unrelated Python, Node or browser
processes.

## Notification preparation

Notification code is prepared but is **not connected to Reset/Judge automation**. Backend startup,
status, configuration checks, previews and offline self-tests send nothing. The only live path is the
explicit interactive test command:

```powershell
.\test-notifications.bat
```

Credentials stay in the ignored root `.env`; never commit them or paste them into chat. See the
[testing guide](docs/notifications/testing-guide.md) before selecting a live test.

## Repository map

```text
apps/backend/               active V2 Backend and tests
apps/web/                   local Dashboard
apps/collector-extension/   transitional Profile/Replies/Search collector
docs/v2/                    current V2 contracts and retained phase evidence
docs/notifications/         current notification configuration and test guide
docs/maintenance/           current maintenance reports
docs/v1/                    archived V1 contracts and reports
scripts/                    current lifecycle, migration and test entries
runtime/                    ignored databases, logs, PID records and test evidence
data/corpus/                ignored corpus assets plus its tracked policy file
local-archive/              ignored retired one-time tools (local only)
```

## Security and data policy

- Never commit `.env`, tokens, cookies, browser profiles, SQLite files, runtime logs or complete real
  corpora.
- V1 runtime data is preserved locally and is not an active Backend.
- Historical import/review must not trigger realtime Judge or notifications.
- Tests use synthetic fixtures and may not invent production Reset history.
- Notification results distinguish API acceptance, provider status and the user's phone observation.

## Validation

```powershell
backend\.venv\Scripts\python.exe -m pytest apps\backend\tests -q

cd apps\web
npm test
npm run typecheck
npm run build

cd ..\collector-extension
npm test
npm run typecheck
npm run build
```

GitHub Actions runs the same product checks. It does not host the Dashboard or publish runtime data.
