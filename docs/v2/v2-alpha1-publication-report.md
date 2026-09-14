# Codex Reset Radar V2 Alpha 1 Publication Report

Date: 2026-09-14

Application version: `2.0.0-alpha.1`

## Outcome

The original V1 snapshot is safely published under a dedicated archive branch and its unchanged annotated tag. The V2 candidate preserves both local and remote histories through a normal merge, keeps the GitHub runtime retired, passes local and GitHub CI validation, and is prepared for normal promotion to `main` and the `v2.0.0-alpha.1` tag.

The final main/tag SHAs, final CI run, and Pages API result are reported in the delivery summary after this report commit is itself validated. This avoids a self-referential documentation commit.

## 1. Divergence verification

Remote refs were checked through both GitHub's live API and Git Smart HTTP. The system DNS route to one official GitHub Web IP was unavailable, so individual Git commands used another current IP returned by GitHub's own Meta endpoint through `http.curloptResolve`. No hosts file, global DNS, Git configuration, or proxy was changed.

| Object | Verified value |
|---|---|
| common ancestor | `2a6b132f6b382dec0e8ee0bb110df127cecd56ca` |
| original local V1 snapshot | `6959d4ecfb3d6786b8e7236ca0838b4a2f1373ff` |
| V2 integration start | `20d10246a813f0cc1a9c0f90e4d8df0e6289bfd8` |
| verified remote `main` baseline | `2d46f7ef80d871bbf8cc02f069636a52671bbdae` |
| local-only V1 commits after common base | `82ef23f`, `9099423`, `b901c30`, `6959d4e` |
| remote-only commit after common base | `2d46f7e` |

The remote and local commits named `feat: add mirror and dashboard timing logs` are different Git objects. However, `git diff --ignore-cr-at-eol --exit-code b901c30 origin/main` succeeds for all ten affected paths. The remote commit consolidates changes represented by three local commits and differs byte-for-byte mainly because of line endings and parent history.

### Disposition table

| Remote modification | Local corresponding implementation | Content relationship | V2 handling | Evidence |
|---|---|---|---|---|
| `backend/app/main.py` | final V1 copy in `apps/backend/legacy_v1/app/main.py`; new V2 in `apps/backend/app/main.py` | remote equals local `b901c30`; final V1 changed again | keep newer V1 archive and V2 Backend; do not restore old path | per-path CRLF-insensitive diff plus `b901c30..6959d4e` diff |
| `backend/tests/conftest.py`, `backend/tests/test_phase_d.py` | `apps/backend/legacy_v1/tests/`; new V2 tests | remote equals local `b901c30`; final V1 changed again | preserve legacy tests only in archive; use V2 suite actively | same comparison and test-path audit |
| `dashboard/src/data.test.ts`, `data.ts`, `main.ts`, `style.css` | V1 tag/history; V2 replacement under `apps/web/` | remote equals local `b901c30`; most files later changed in V1 snapshot | do not restore obsolete static Dashboard path | per-path diff and active-source audit |
| `docs/live-mirror-cadence-fix-report.md`, `docs/live-mirror-timing-log.md` | `docs/v1/` | remote equals local `b901c30`; timing log later extended | retain archived V1 documents; avoid root duplicates | per-path diff and repository tree |
| `scripts/sync-github-data.ps1` | `legacy/v1/scripts/sync-github-data.ps1` | remote equals local `b901c30`; final V1 changed again | keep as V1-only script; do not reactivate | per-path diff and active runtime audit |

No remote-only product behavior remained after accounting for the equivalent local lineage. Old Mirror/Pages changes are preserved historically without being copied back into active V2 code.

## 2. V1 preservation

Before upload, all 23 commits reachable from the V1 snapshot were scanned for known token/key forms, private-key markers, literal bearer credentials, forbidden runtime paths, and blobs above 5 MiB. Results: PASS, with no candidates.

Remote verification:

| Ref | Verified object |
|---|---|
| `archive/v1-final-2026-09-13` | `6959d4ecfb3d6786b8e7236ca0838b4a2f1373ff` |
| annotated tag object `v1-final-snapshot-2026-09-13` | `49cf607df0eb640e277bafbb093da378e4cf0bc6` |
| annotated tag peeled target | `6959d4ecfb3d6786b8e7236ca0838b4a2f1373ff` |

Remote content checks successfully read `backend/app/main.py`, `scripts/sync-github-data.ps1`, and `docs/v1-final-status.md` from the archive branch. No database, JSONL runtime log, `.env`, virtual environment, browser profile, or node_modules tree is reachable from the archived snapshot.

## 3. Integration record

- Branch: `release/v2-alpha1-integration`
- Start: `20d10246a813f0cc1a9c0f90e4d8df0e6289bfd8`
- Remote baseline: `2d46f7ef80d871bbf8cc02f069636a52671bbdae`
- Normal merge commit: `b5ab6ab`

The merge produced eight modify/delete conflicts in old Backend, Dashboard, and mirror-script paths, plus two root-level V1 mirror documents. Each remote file was first proven equivalent to the local `b901c30` form. The obsolete root paths were then individually kept deleted because their newer V1 form or history is already preserved and their active V2 replacement exists. No repository-wide `ours`/`theirs` strategy was used.

The resulting merge tree matched the pre-merge V2 tree while the merge commit connected both histories. Subsequent dedicated commits aligned the release version, fixed the collector build dependency advisories, centralized Extension manifest version generation, and clarified GitHub's source-only role.

## 4. Version alignment

| Surface | Result |
|---|---|
| product | Codex Reset Radar V2 |
| root `VERSION` | `2.0.0-alpha.1` |
| Backend health/FastAPI version | `2.0.0-alpha.1` |
| Web package and visible footer build value | `2.0.0-alpha.1` |
| Collector package / `version_name` | `2.0.0-alpha.1` |
| Chrome numeric manifest version | `2.0.0` |
| release tag | `v2.0.0-alpha.1` |

Backend and Web already read the root `VERSION`. The Collector build now does the same and generates `dist/manifest.json`; the redundant tracked source manifest was removed. Package metadata remains synchronized as required by npm.

## 5. Security and dependency review

### Repository scans

- V1 reachable-history Secret Scan: PASS
- V1 forbidden-path scan: PASS
- V1 blob scan above 5 MiB: PASS
- integrated candidate reachable-history Secret Scan: PASS
- candidate forbidden-path scan: PASS
- candidate blob scan above 5 MiB: PASS
- Web/Collector built-bundle Secret Scan: PASS
- active external GitHub runtime string audit: PASS
- active Mirror scheduler audit: PASS
- active workflow inventory: only `.github/workflows/ci.yml`

### Collector build dependency findings

The Foundation lock resolved direct `vite@5.4.21` and `vitest@2.1.9`, with transitive `esbuild@0.21.5`, `@vitest/mocker@2.1.9`, and `vite-node@2.1.9`. `npm audit` reported five affected package nodes (3 moderate, 1 high, 1 critical):

| Advisory | Severity | Package / condition | Exposure and decision |
|---|---|---|---|
| `1102341` | moderate | esbuild dev server allowed cross-origin requests through `<=0.24.2` | local/CI build tooling, not Extension runtime; fixed |
| `1116229` | high | Vite optimized-deps source-map path traversal through `<=6.4.1` | local dev server/build tooling; fixed |
| `1120784` | high contributor | Vite launch-editor UNC path could disclose NTLMv2 hash on Windows through `<=6.4.2` | relevant to Windows development; fixed |
| `1123525` | high contributor | Vite `server.fs.deny` bypass on Windows alternate paths through `<=6.4.2` | relevant to local dev server; fixed |
| `1139528` | critical contributor | Vitest UI server arbitrary file read/execution below `3.2.6` | UI server was not enabled, but vulnerable tooling remained installed; fixed |
| `1193683`, `1193684` | critical/moderate contributors | Vitest/@vitest-mocker redirect-mock path traversal before `4.1.11` | test tooling and CI; fixed |

Dedicated commit `06ef02d` upgrades Vite to `6.4.3`, Vitest and `@vitest/mocker` to `4.1.11`, esbuild to `0.25.12`, and removes the old `vite-node` dependency path. `npm audit` then reports zero vulnerabilities. Tests, type checking, and builds pass after a clean `npm ci`. No force audit fix was used.

The package manager also prints an allow-scripts review notice for esbuild's install script. This is not an audit vulnerability; the pinned lock, clean CI install, successful build, and zero-vulnerability audit make it a non-blocking package-manager policy notice for this alpha.

## 6. Local acceptance

Final integrated local validation:

| Component | Result |
|---|---|
| Backend | 9 passed |
| Web | 5 passed; TypeScript PASS; build PASS |
| Collector | 12 passed; TypeScript PASS; build PASS |
| PowerShell launcher/parser | PASS |
| `git diff --check` | PASS |

An isolated smoke database and log directory were used; no production data was modified and no external provider was enabled. The smoke verified:

- `/api/v2/health`: healthy and version `2.0.0-alpha.1`;
- `/api/v2/radar`: white `UNKNOWN` and `waiting_for_verified_history`;
- Web and Web-origin `/api/v2` proxy: HTTP 200/healthy;
- no confidence or confidence percentage field;
- a synthetic Special Reset in the isolated database rendered `PURPLE` and did not create a Full Reset;
- `github_mirror_enabled=false` and `pages_dependency=false`;
- no established external connection from the Backend/Web processes;
- `stop-v2-local.bat` left zero listeners on ports 8787 and 5173;
- the isolated smoke database/log directory was removed afterward.

## 7. Candidate publication and CI

The integration branch was pushed normally; no force option was used. Pull Request #1, `Release V2 Foundation Alpha 1`, targets `main` from `release/v2-alpha1-integration`.

Initial candidate CI:

- run: `34806666608`;
- event: `pull_request`;
- tested commit: `75703963f29883461f3cf62392a0992dfe603cd9`;
- Backend: success;
- Web tests/typecheck/build: success;
- Collector tests/typecheck/build: success.

This report and the final single-version-source adjustment are pushed through the same PR and must receive a second successful CI run before normal merge. The exact final candidate, remote main, and release-tag targets are intentionally captured in the delivery summary.

## 8. Runtime retirement state

- Pages deployment workflow: removed from active workflows and archived under `docs/v1/archive/`.
- CI responsibilities: tests, type checking, and build verification only.
- GitHub runtime requests: absent from active Backend/Web/Collector code.
- `data` branch baseline: `4be2418aa31d1b5b87789c24c17661e2d771402f`; it is preserved and must remain unchanged.
- GitHub Pages repository setting: reported enabled before final promotion. It is disabled only after V1 refs, final main CI, and the V2 annotated tag are all verified; the post-publication API result is in the delivery summary.

## 9. Scope and residual limitations

No historical corpus collection, DeepSeek Judge, server collector, notification redesign, overseas deployment, production data cleanup, or fake Reset/Tibo record was added. Alpha 1 intentionally starts with `UNKNOWN`; production notifications remain disabled.

The final GitHub ref and Pages operations occur after this document's commit passes CI. Any failure in those operations is a publication blocker and must be reported rather than hidden or bypassed.
