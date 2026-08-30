# Live public data mirror

Codex Reset Radar keeps the runtime system local. The public Dashboard reads a
small, allow-listed JSON mirror from GitHub; it does not call the local
Backend, SQLite, X, DeepSeek, or WxPusher.

## Data flow

```text
local SQLite
    ↓ read-only public_export.py
temporary data-branch worktree
    ↓ git push origin data
GitHub raw JSON on data branch
    ↓ browser fetch with cache: no-store
GitHub Pages Dashboard
```

The sync script never checks out `data` in the active development worktree. It
stages only `index.json`, `tweets.json`, `radar.json`, `health.json`, and
`meta.json`. The data branch contains no Backend, extension, database, logs,
`.env`, or credentials. The tracked `public-data/` directory remains a
development/sample snapshot and is not the production runtime source.

## Schedule and events

The Backend starts a lightweight `asyncio` mirror loop when
`GITHUB_MIRROR_ENABLED=true`. It runs at a five-minute cadence and can wake
early after a new Tweet, high-value classification, Radar transition, or
monitor state change. The 60-second monitor heartbeats do not each create a
GitHub commit. Each sync cycle allows at most three push attempts, then waits
for the next cycle.

The sync runs in a worker thread and its failure is isolated: a GitHub timeout,
authentication error, rate limit, or push failure is logged as
`PUBLIC_MIRROR_SYNC_FAILED` and does not stop collection, classification,
SQLite, Radar, or notifications.

## Dashboard source and freshness

Production data is fetched from:

`https://raw.githubusercontent.com/Oblivionis-ling/codex-reset-radar/refs/heads/data/`

The base URL is centralized in `dashboard/src/config.ts`. Local Vite
development may use `/public-data/`; the build-time copy is only a fallback
sample and is not used by the production URL. The page refreshes all five JSON
files every 60 seconds and uses `cache: "no-store"`.

Freshness is based on `meta.mirror_synced_at`, then the snapshot generation
time. A snapshot is fresh for 15 minutes and stale after that:

- `fresh` + reported `healthy` → `正常` / `HEALTHY`;
- `fresh` + reported `offline` → `离线` / `OFFLINE`;
- stale, regardless of the old reported state → `数据过期` / `STALE`, with the
  last known state shown;
- missing or invalid component/freshness data → `未知` / `UNKNOWN`.

Thus an old `healthy` heartbeat is never rewritten to `offline`, and an old
`offline` value is not treated as proof that the monitor is still offline.
Data Mirror has its own `fresh` / `stale` / `unknown` row. Radar and Latest
Signal retain their values when stale but are labeled as last known.

If an individual refresh fails, the page keeps the last successful value for
that file and shows a refresh-failed notice. If no usable value exists, the
page remains rendered and shows `Data unavailable` or `未知`; it never becomes a
blank page.

## Local operation

Keep the local Backend running with the normal `start-radar.bat` flow and keep
the GitHub CLI/keyring available to the Git remote. The mirror can also be run
manually from the repository root:

```powershell
.\scripts\sync-github-data.ps1
```

No GitHub token is placed in the Dashboard bundle. The mirror credentials are
used only by the local Git operation and are not exported.
