# Codex Reset Radar V1 Final Status

Snapshot date: 2026-09-13

V1 is preserved as its real final development state before the V2 architecture reset. This file records known failures without changing V1 behavior to make the snapshot appear healthier than it was.

## Final runtime position

- Local Backend was not running at the final audit: port 8787 had no listener and no matching Uvicorn process existed.
- GitHub Pages remained HTTP-reachable, but its public data snapshot was stale and last known to have been published on 2026-09-09.
- Current Edge Profile, Replies, Search tabs, Content Scripts, and Service Worker could not be inspected from the audit environment.
- The V1 runtime architecture was Local Backend → GitHub data branch → GitHub Pages. That architecture is frozen at this snapshot and is not the V2 runtime model.

## Known failures retained in V1

1. Health evaluator timezone bug: backend/app/main.py subtracts a SQLite naive datetime from an aware current time in the offline-to-healthy recovery path, producing `TypeError: can't subtract offset-naive and offset-aware datetimes`.
2. Extension TypeScript failure: extension/src/background.ts reads actual_heartbeat_elapsed_ms from a metadata type that does not declare the field.
3. H.5 lifecycle instrumentation is incomplete: no complete PING_CONTENT_SCRIPT, timer-registration/first-tick, pageshow, freeze/resume, context-invalidation, or timer-uniqueness evidence chain.
4. Backend startup blind spot: the 2026-09-12 instance that emitted PROCESS_STARTED and SQLITE_JOURNAL_MODE but never BACKEND_READY has no captured root stderr/exception.
5. Backend test invocation is path-sensitive: the suite passes from repository root but the documented backend-directory invocation fails to import scripts.
6. Mirror delivery reliability remained network-bound. Historical successful-publish intervals exceeded the 15-minute Dashboard freshness threshold 162 times.
7. The local Dashboard build and online Pages asset differed at final audit, so the latest working-tree UI could not be described as production-deployed.

## Historical test evidence

- Backend from repository root: 57 passed.
- Backend from backend directory: failed with ModuleNotFoundError for scripts.
- Dashboard: 8 tests passed; TypeScript/build passed.
- Collector Extension: 12 tests passed; Vite build passed; standalone TypeScript check failed.

## Data preservation

- The approximately 1.2 GiB V1 radar.db remains local and ignored.
- The approximately 3.0 GB backend/data tree, legacy observability logs, notification logs, and Mirror logs remain local and ignored.
- No V1 runtime database or log is included in Git.
- The data branch is not deleted. It is a legacy read-only snapshot for future migration and audit.

## Security

- .env is ignored and not tracked.
- Candidate secret scan passed without printing credential values.
- Candidate large-file scan passed.
- No production notification was sent while preparing the snapshot.

## V1 archive identity

The intended annotated tag is v1-final-snapshot-2026-09-13 with message:

> Final V1 development snapshot before V2 architecture reset.

The commit and remote publication state are recorded in the V2 Foundation report after the local snapshot and remote verification steps complete.
