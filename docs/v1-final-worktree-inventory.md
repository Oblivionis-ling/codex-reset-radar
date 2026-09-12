# Codex Reset Radar V1 Final Worktree Inventory

Inventory date: 2026-09-13  
Baseline branch: main  
Baseline HEAD: b901c3094bd40da58a1bb32f04972b85e79bde30

This inventory was created before changing V1 business behavior. Its purpose is to preserve the real final V1 development state and to define the exact Git candidate set.

## Remote preflight

- git fetch --prune origin: FAILED because the GitHub HTTPS connection was reset.
- GitHub API main-ref check: FAILED because the SSL connection could not be established.
- Locally cached origin/main: 2a6b132f6b382dec0e8ee0bb110df127cecd56ca.
- Local divergence against the cached ref: 3 ahead, 0 behind.
- Decision: local snapshot work may continue, but push remains gated until the remote ref is confirmed. No force push is permitted.

## Candidate classification

### SOURCE — include

- backend/app/classifiers/service.py
- backend/app/database/core.py
- backend/app/ingestion.py
- backend/app/main.py
- backend/app/models/__init__.py
- backend/app/notifications/alert_manager.py
- backend/app/notifications/wxpusher.py
- backend/app/schemas.py
- backend/app/observability.py
- dashboard/src/data.ts
- dashboard/src/main.ts
- extension/src/background.ts
- extension/src/content.ts
- extension/src/types.ts

These files contain the final uncommitted V1 classification, translation, observability, notification, Mirror timing, Dashboard timing, and Extension diagnostic work.

### TEST — include

- backend/tests/conftest.py
- backend/tests/test_phase_d.py
- backend/tests/test_phase_h.py
- backend/tests/test_phase_h1.py
- backend/tests/test_wxpusher_diagnostics.py
- dashboard/src/data.test.ts

### SCRIPT — include

- scripts/sync-github-data.ps1
- scripts/diagnose.py
- scripts/stop-backend.ps1
- stop-backend.bat

### DOC — include

- docs/current-development-state-audit-2026-09-13.md
- docs/live-data-mirror.md
- docs/live-mirror-delivery-diagnostic-report.md
- docs/live-mirror-reliability-fix-report.md
- docs/live-mirror-timing-log.md
- docs/observability-architecture.md
- docs/observability-contract.md
- docs/operations.md
- docs/phase-h-observability-report.md
- docs/phase-h1-observability-performance-report.md
- docs/profile-replies-offline-root-cause-report.md
- docs/project-status-report-2026-09-07.md
- docs/troubleshooting-runbook.md
- docs/wxpusher-delivery-diagnostic-report.md
- docs/v1-final-worktree-inventory.md
- docs/v1-final-status.md

### CONFIG_TEMPLATE — include

- .gitignore: add an exact ignore rule for the unreferenced local design mockup.
- .env.example is already tracked and unchanged at snapshot time.

### GENERATED — exclude and preserve locally

- docs/Codex 图像 2026年8月31日 14_37_30.png

The file is an unreferenced design mockup containing fabricated 2025 example signals. It is not required by any document, conflicts with the no-fake-Tibo-data rule, and is retained locally through an exact .gitignore rule rather than deleted.

### RUNTIME_DATA — exclude and preserve locally

- backend/data/**, including radar.db, SQLite sidecars, runtime JSONL, mirror logs, notification logs, and observability shards.
- _tmp/**, including historical Mirror worktrees.

### SECRET — exclude

- .env
- Any browser cookies, sessions, credentials, authorization headers, Git credential-helper content, WxPusher credentials, DeepSeek keys, or GitHub tokens.

### BUILD_ARTIFACT / DEPENDENCY / CACHE — exclude

- backend/.venv/**
- dashboard/node_modules/**
- dashboard/dist/**
- extension/node_modules/**
- extension/dist/**
- .pytest_cache/** and Python caches

### UNKNOWN

None after inspection.

## Scan results

- Candidate secret scan: PASS. No known OpenAI/DeepSeek, GitHub, WxPusher, private-key, or JWT token pattern was detected in tracked and untracked candidate text files.
- Candidate large-file scan: PASS. No candidate exceeds 5 MiB; therefore none exceeds 20 MiB or 50 MiB.
- Largest excluded local mockup: approximately 1.28 MiB.
- Runtime database and multi-gigabyte logs are ignored and are not part of the candidate commit.

## Snapshot decision

All include-listed source, tests, scripts, sanitized documentation, and config-template changes are eligible for the V1 snapshot. Excluded data remains on disk and must not be staged. Known V1 failures are intentionally documented rather than repaired before the snapshot.
