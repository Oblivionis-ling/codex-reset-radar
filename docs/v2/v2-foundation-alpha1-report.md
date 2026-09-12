# Codex Reset Radar V2 Foundation Alpha 1 Report

Date: 2026-09-13

Version: `0.1.0-alpha.1`

Local Foundation HEAD before report commits: `34a14a6`

## Executive result

The local V2 Foundation is complete and accepted as a self-contained Backend + database + Web stack. It no longer depends on GitHub Pages, the `data` branch, Raw GitHub JSON, a mirror scheduler, or Git push for runtime operation.

Publishing and the final main/tag transition are intentionally incomplete. A required fresh fetch found that `origin/main` had diverged, so the no-force/no-history-rewrite gate stopped all push and merge actions. Details are in [remote-main-divergence-report-2026-09-13.md](remote-main-divergence-report-2026-09-13.md).

## V1 snapshot

- Commit: `6959d4ecfb3d6786b8e7236ca0838b4a2f1373ff`
- Annotated tag: `v1-final-snapshot-2026-09-13`
- Tag message: `Final V1 development snapshot before V2 architecture reset.`
- Candidate Secret Scan: PASS
- Candidate large-file scan: PASS; no file above 5 MiB
- V1 known failures were documented rather than silently changed.
- V1 final inventory/status are archived under `docs/v1/`.

The commit and tag remain local because remote divergence was discovered before publishing. No push was attempted after that discovery.

## Git history

V2 was created from the V1 snapshot tag and contains these logical Foundation commits:

| Commit | Purpose |
|---|---|
| `c880408` | reorganize the monorepo and archive V1 paths |
| `2da75c9` | add V2 database, API, migration, logging, and tests |
| `1d3ec4b` | add the V2 local Web foundation |
| `cd5fe71` | validate and identify the transitional collector adapter |
| `cd6b18e` | add project-scoped local lifecycle scripts and CI |
| `34a14a6` | add V2 product, architecture, API, data, and migration docs |

Fresh remote state:

- `origin/main`: `2d46f7e`
- local `main`: `6959d4e`
- relation: ahead 4, behind 1
- no remote V1 tag, V2 branch, or V2 tag was observed

## Files committed and intentionally excluded

Committed source and durable policy include the active Backend, Web, collector adapter, tests, CI, migration utility, version/config template, local lifecycle scripts, V1 archive, V2 documentation, and directory policy READMEs.

Intentionally excluded:

| Asset | Reason |
|---|---|
| `backend/data/radar.db` | 1.2 GiB legacy V1 runtime database; local read-only migration source |
| `backend/data/observability/` and JSONL logs | multi-gigabyte/high-volume V1 runtime telemetry |
| root `.env` | may contain local credentials and tokens |
| `runtime/data/*.db` | generated V2 runtime state |
| `runtime/logs/`, `runtime/launcher/`, `runtime/pids/` | bounded but machine-local runtime artifacts |
| `data/analysis/v1-reset-migration-candidates.json` | generated real-data review artifact, not source |
| `.venv/`, `node_modules/`, `dist/` | reproducible dependencies and build artifacts |
| browser storage/session/profile data | credentials and private machine state |

The legacy database, logs, reports, and remote `data` branch were not deleted.

## Repository before and after

V1 mixed an active local Backend with GitHub mirror scripts, tracked static `public-data`, and a Pages Dashboard. V2 separates active application source from frozen history:

```text
apps/
  backend/
    app/                 active V2 Backend
    legacy_v1/           archived V1 Backend source
    tests/
  web/                   local Vite product surface
  collector-extension/   transitional collector adapter
docs/
  v1/                    V1 reports/contracts/static snapshot
  v2/                    V2 contracts and reports
legacy/v1/               old mirror/diagnostic/start scripts
scripts/                 V2 migration and lifecycle scripts
backend/data/            ignored preserved V1 runtime data
runtime/                 ignored V2 state
data/analysis/           ignored migration review output
```

The only active workflow is `.github/workflows/ci.yml`. The Pages workflow is preserved as documentation at `docs/v1/archive/pages-workflow.yml` and cannot deploy.

## V2 architecture and runtime

The active path is:

```text
X public page
  -> transitional MV3 collector
  -> localhost FastAPI Backend
  -> isolated V2 SQLite
  -> localhost Vite Web via /api/v2
```

Backend lifespan starts database initialization and bounded local logging only. Health explicitly reports `github_mirror_enabled=false` and `pages_dependency=false`. Static inspection of active source and built Web/Extension artifacts found no Raw GitHub URL, `refs/heads/data`, `public-data`, or deploy-pages request.

## V2 data contract

The isolated V2 schema contains:

- `tibo_posts`
- `reset_events`
- `reset_cycles`
- `post_analysis`
- `radar_judgements`
- `schema_versions`

Only a Full Reset closes the open cycle, opens a new cycle, and changes `last_full_reset`. A Special Reset cannot do so and always receives the `PURPLE` display tone. Radar Action/Horizon values are constrained to `GREEN`, `YELLOW`, `ORANGE`, `RED`, or `UNKNOWN`; no confidence field exists.

Routine collector heartbeats update in-memory state and are not inserted into long-term tables. Runtime logs use daily JSONL categories, five-day default retention, size-based shards, and a hard cap of twenty shards per category/day.

## API contract

The active API includes:

- `GET /api/v2/health`
- `GET /api/v2/radar`
- `GET /api/v2/posts`
- `GET /api/v2/resets`
- `POST /api/v2/resets`
- `POST /api/v2/collector/posts`
- `POST /api/v2/collector/heartbeat`

The current Extension remains usable through minimal `/api/ingest/tweets`, `/api/heartbeat`, and `/api/diagnostics*` compatibility routes. Compatibility diagnostics are accepted but not persisted in the V2 core database.

## Migration acceptance

The real V1 migration was run with the source opened through SQLite `mode=ro`.

| Check | Result |
|---|---|
| V1 rows / unique tweet IDs | 242 / 242 |
| V2 `tibo_posts` | 242 |
| V1 reset-review candidates | 5 |
| canonical V2 `reset_events` | 0 |
| V2 `reset_cycles` | 0 |
| V2 `radar_judgements` | 0 |
| source DB size/mtime after migration | unchanged |

The five candidates are generated only into the ignored review artifact with `REQUIRES_PROVENANCE_REVIEW`. No Reset history or Tibo content was invented. Initial Radar remains white `UNKNOWN`, and next Reset remains `waiting_for_verified_history`.

## Dashboard text acceptance

The local home page directly presents:

- main Action Level;
- NEXT RESET;
- 24H / 48H / 72H horizons;
- Special Reset Purple area;
- WHY/reason;
- Last Full Reset;
- Recent Tibo Posts;
- Data Health.

The minimal `/ops` route is reserved for future operations UI. Main Radar contains no confidence percentage, mirror freshness, Git branch, heartbeat table, or Pages terminology. Alpha 1 intentionally prioritizes correct information structure over final visual polish.

## Local startup and E2E

`start-v2-local.bat` starts only the active V2 Backend and Web. It records exact process ownership under `runtime/pids/`; `stop-v2-local.bat` verifies repository root, PID, process start time, executable, and command marker before stopping anything.

Observed smoke test:

| Check | Result |
|---|---|
| `GET http://127.0.0.1:8787/api/v2/health` | 200 / healthy |
| `GET http://127.0.0.1:8787/api/v2/radar` | 200 / UNKNOWN |
| `GET http://127.0.0.1:5173/` | 200 |
| Web-origin `/api/v2/health` proxy | healthy |
| migrated post count through API | 242 |
| mirror / Pages runtime flags | false / false |
| listeners after `stop-v2-local.bat` | 0 |

The Windows Python environment uses a launcher process; the script resolves and records the actual PID that owns port 8787. This was specifically tested to prevent a hidden orphan Backend.

## Tests and CI

Final local results:

- Backend: 9 passed
- Web: 5 passed; TypeScript PASS; production build PASS
- Collector Extension: 12 passed; TypeScript PASS; production build PASS
- PowerShell start/stop script parse: PASS
- local full-stack smoke: PASS

CI uses Python 3.12 and Node 20 to run the same three component suites. It performs tests, type checking, and builds only; it does not deploy Pages or publish runtime data.

`npm ci` reported five advisories in the Extension's development/build dependency tree (3 moderate, 1 high, 1 critical). The Extension has no production npm dependencies, and forcing breaking dependency upgrades was outside this repository-reset task. This should be reviewed in a dedicated dependency update before a production release.

## GitHub, Pages, and data branch state

- V1 push: blocked by remote divergence
- V2 branch push: not performed because the required V1 publish gate did not pass
- V2 merge to main: not performed
- V2 annotated release tag: not created
- repository description/topics: not changed while source publication is unresolved
- active Pages workflow in V2: retired locally
- GitHub Pages site: still enabled or unverified; **MANUAL ACTION REQUIRED after safe source publication**
- remote `data` branch: retained; fetched at `4be2418`; not deleted or written by V2

## Known limitations

- DeepSeek Judge is not implemented, so forward Radar judgement is correctly `UNKNOWN`.
- Reset candidates require manual provenance review.
- The current browser Extension is transitional, not the final server collector.
- Notifications are configured only as reserved fields; no real Alpha 1 delivery rule was activated or tested.
- `/ops` is a placeholder rather than a full operations console.
- No Docker, overseas host, reverse proxy, domain, TLS, or production secret workflow exists yet.
- Remote history must be reconciled before GitHub can represent the V2 Foundation.

## Acceptance matrix

| Item | Result | Evidence / blocker |
|---|---|---|
| V1 snapshot | PASS | local commit `6959d4e` |
| V1 pushed | FAIL | `origin/main` divergence gate |
| V1 tag | PASS local / FAIL remote | annotated local tag exists; remote ref absent |
| Repository reorganized | PASS | commit `c880408` |
| V2 DB created | PASS | isolated schema and real migration smoke |
| V2 API | PASS | contract tests and HTTP smoke |
| V2 Web | PASS | tests, typecheck, build, proxy smoke |
| GitHub runtime removed | PASS local | no active mirror/Pages path |
| Local E2E | PASS | Backend/Web/API/proxy/stop acceptance |
| Tests | PASS | 9 Backend + 5 Web + 12 Collector |
| Secret scan | PASS | final tracked-candidate scan |
| V2 pushed | FAIL | publication held behind V1 gate |
| V2 merged main | FAIL | remote divergence unresolved |
| V2 tag | FAIL | created only after safe main merge |
| Pages retired | MANUAL | workflow retired locally; site action deferred |
| Worktree clean | PASS after report commit | generated runtime/build artifacts ignored |

## Next-stage prerequisites

The next action is not Historical Corpus, Judge, final Dashboard, Server Collector, notification redesign, or deployment. First review and resolve the remote-main divergence through a normal merge, rerun all acceptance checks, and complete the required V1/V2 publish sequence. Only after GitHub main and both annotated tags are safely verified should Pages be disabled and later product phases begin.
