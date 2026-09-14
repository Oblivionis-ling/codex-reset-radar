# Remote Main Divergence Report — 2026-09-13

> Historical divergence record. The 2026-09-14 publication closeout implements the controlled normal-merge resolution described here without rewriting either history.

## Outcome

V1 and V2 publishing was stopped before any push because the required fresh fetch found an unexpected remote commit. No force push, history rewrite, merge, or tag push was performed.

## Observed refs

| Ref | Commit |
|---|---|
| local `main` / local V1 snapshot | `6959d4ecfb3d6786b8e7236ca0838b4a2f1373ff` |
| local `v2` before this report commit | `34a14a6` |
| fetched `origin/main` | `2d46f7ef80d871bbf8cc02f069636a52671bbdae` |
| merge base | `2a6b132f6b382dec0e8ee0bb110df127cecd56ca` |

`git rev-list --left-right --count main...origin/main` returned `4 1`: local `main` is ahead by four commits and behind by one.

The remote has no `v2` branch, `v1-final-snapshot-2026-09-13` tag, or `v2.0.0-alpha.1` tag as of the read-only `ls-remote` check at `2026-09-12T18:46:35Z`.

## Divergent commit analysis

Remote commit `2d46f7e` and local commit `b901c30` share the subject `feat: add mirror and dashboard timing logs`, but they are not the same Git object:

- remote parent: `2a6b132`;
- local parent: `9099423`;
- author identity and timestamp differ;
- tree hashes differ;
- the remote commit consolidates work that exists as three local commits after the common base.

`git diff --ignore-cr-at-eol --exit-code b901c30 origin/main` returned success. The ten affected files therefore have matching semantic line content when CRLF differences are ignored, but Git history and byte-level trees still diverge. That evidence reduces product-conflict risk but does not authorize rewriting or overwriting the remote branch.

## Safety decision

The task explicitly requires the V1 push flow to stop when fresh `origin/main` makes the local branch behind. Therefore:

- V1 snapshot commit: local only;
- V1 annotated tag: local only;
- V2 commits: local only;
- no V2 release tag was created;
- repository metadata was not mutated;
- Pages was not disabled, because that action is allowed only after both V1 and V2 are safely published.

## Recommended controlled resolution

After user review, use a normal non-force merge that preserves both histories:

1. merge `origin/main` into local `main` without rebasing or resetting either side;
2. resolve only verified line-ending conflicts, preserving the already-reviewed V1 snapshot content;
3. rerun V1 safety checks and push `main` plus the V1 annotated tag;
4. merge the reconciled local `main` into `v2`, rerun the complete Alpha 1 acceptance suite, and push `v2`;
5. only then merge V2 normally into `main`, create/push `v2.0.0-alpha.1`, update repository metadata, and retire Pages.

No step should use `--force`, `--force-with-lease`, rebase, reset of a published ref, or deletion of the legacy `data` branch.
