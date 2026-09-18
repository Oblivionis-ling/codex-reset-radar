# Notification preparation and workspace cleanup

Status date: 2026-09-19

Branch: `notification-prep-20260919`

Accepted base: `2.0.0-alpha.4` at `d526fe236bcdd232760271b51c787dba03924556`

## Scope and safety result

This round prepared notification transports and simplified active workspace entry points. It did not
change corpus prompts, adjudications, Reset semantics, Judge logic or the product database. The
notification package remains disconnected from production events and schedulers.

- Real WeChat sends: **0**
- Real email sends: **0**
- Account registrations/binding changes: **0**
- DeepSeek calls caused by this work: **0**

## Workspace organisation

The root README is now the concise current index. The three current notification/maintenance entries
are:

- `docs/notifications/README.md`
- `docs/notifications/testing-guide.md`
- `docs/maintenance/notification-prep-and-cleanup.md`

The workspace already had a meaningful historical split: V1 reports live under `docs/v1/`, and corpus
phase evidence under `docs/v2/corpus/`. Those files were not mass-moved because manifests, reports and
operator notes use their stable paths. The user-provided task document
`docs/notification_preparation_and_workspace_cleanup.md` was preserved unchanged.

Before cleanup, `docs/` contained 81 files / 3,449,870 bytes. One-time tool sources totalled 95,066
bytes. No reviewed corpus package, database, backup, Extension `dist`, Python environment,
`node_modules` tree or pre-existing `_tmp` content was deleted.

### Retired local tools

The following untracked, one-time historical tools left active source/test directories and were moved
to ignored `local-archive/20260919-historical-tools/`, preserving their relative paths:

```text
apps/backend/app/corpus.py
apps/backend/app/corpus_round2.py
apps/backend/tests/test_historical_corpus.py
scripts/analyse_historical_corpus_round2.py
scripts/import_historical_corpus.py
scripts/import_historical_corpus_round2.py
scripts/run_round2_corpus_judge.py
```

Tracked product code has no imports from these files. Moving files to an archive does not free disk
space, so the release attributable to this move is **0 bytes**. Large but required/rebuildable areas
were retained: `backend/.venv` is still the launcher fallback; Web/Collector `node_modules` support
local validation; Extension `dist` may be loaded by Edge; runtime databases/logs and corpus material
are business/test assets.

## Shared implementation

- Added one optional Backend-local notification configuration loader.
- Added one `httpx` transport as the only HTTP retry owner (maximum two retries by configuration).
- Added thin provider adapters with provider-specific authentication, business codes and status
  parsing.
- Reused the same PushPlus/WPush adapters for ClawBot channel variants.
- Consolidated WxPusher send/status behaviour into active V2 code without importing legacy V1.
- Added verified-TLS SMTP, a separate SQLite delivery/dedup ledger and a one-hop email fallback.
- Added `scripts/common-v2.ps1`; start and notification wrappers now share Python environment discovery.
- Added one Windows entry, `test-notifications.bat`; non-live commands are network-blocked.

No message broker, plugin framework or production event wiring was added.

## Channel readiness

| Channel | Code/offline state | User-dependent state |
| --- | --- | --- |
| PushPlus WeChat | Implemented, `OFFLINE_PASS` | Needs token and manual phone test |
| PushPlus ClawBot | Shared implementation, `OFFLINE_PASS` | Conditional QR binding/interaction; user decision |
| Server酱 Turbo | Implemented, `OFFLINE_PASS` | Needs SendKey and manual phone test |
| IYUU | Implemented, `OFFLINE_PASS` | Needs token and manual phone test |
| WPush WeChat | Implemented with status query, `OFFLINE_PASS` | Needs API Key/channel binding and manual test |
| WPush ClawBot | Shared implementation with status query, `OFFLINE_PASS` | Conditional binding; user decision |
| WxPusher | Implemented with status query, `OFFLINE_PASS` | Local config detected; no live send performed |
| ShowDoc | Contract verified and implemented, `OFFLINE_PASS` | Needs token and manual phone test |
| Independent SMTP | Implemented, `OFFLINE_PASS` | Needs user-selected mailbox configuration and manual test |

## Validation

Targeted notification tests cover request construction, business failure under HTTP 200, asynchronous
pending/unknown, status queries, absent optional config, redaction, Unicode/length handling, bounded
retry, SMTP success/auth/refusal/TLS/timeout, fallback dedup and network blocking. Results and full
product regression are recorded below after final execution.

<!-- FINAL_VALIDATION_RESULTS -->

## Stop point

The prepared code does not claim phone delivery. The next action is the user's manual configuration
and one-channel-at-a-time test following `docs/notifications/testing-guide.md`. No production
notification automation should be enabled before those observations are recorded.
