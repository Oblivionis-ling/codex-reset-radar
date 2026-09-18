# GPT reference review procedure

GPT reference review is a development-time content audit, not a production model call and not a second
online judge.

## Freeze and independence

1. Create a SQLite online backup and verify `quick_check` and foreign keys.
2. Record cutoff, database hash, Git HEAD, worktree fingerprint, corpus version, model, and Prompt versions.
3. Export all canonical posts, formal events, and existing cases to `crr-corpus-v1`.
4. Review source content before reading the new isolated DeepSeek replay output.
5. Mark pre-existing product analyses/cases as exposure; do not claim those objects are blind tests.

The current Codex main model is the GPT reviewer. If the exact deployment identifier is not exposed, the
manifest says so rather than guessing a model name. No DeepSeek output may be relabelled as GPT.

## Per-object output

Each post result records author/content integrity, translation status, semantic category, event type and
stage, Special subtype, scope/time basis, cycle impact, multiple effects, a short evidence quote,
missing input, and exposure. Formal events and existing cases receive their own results. Judge references
are grouped by `as_of` window, never one colour per isolated Tweet.

Translated browser text is not reverse-translated into a supposed English original. Missing parent text,
truncation, UI-shell captures, and likely quoted/non-Tibo body content are explicit insufficiencies.
Unknown outcomes are not negative labels. Same-post completion examples are event-recognition material,
not successful advance warnings.

## Human boundary

GPT results may become `GPT_REVIEWED`. They may become `AGREED` when the product result has no material
difference, but neither state is human approval. A real person must decide event mechanism/stage/scope,
event merge/split, future-vs-completed, cycle impact, Action Level, and timing disagreements before the
reference field can become `HUMAN_DECIDED`.

One-off GPT batch helpers and full review packages remain local and ignored. Only this procedure, the
standard, minimal synthetic tests, and confirmed product fixes belong in Git.
