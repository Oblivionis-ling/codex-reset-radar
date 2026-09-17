# Historical Import and Verification

## Entry point

```powershell
backend\.venv\Scripts\python.exe scripts\import_historical_corpus.py --dry-run `
  --start 2025-09-17T01:35:00Z --cutoff 2026-09-17T01:35:00Z
```

Remove `--dry-run` only after reviewing the preview. The default source set is ModelYard plus AIPlanWatch. Source and date filters, an AIPlanWatch page cap, a stable batch prefix, local snapshot suppression, and conservative batch rollback are available through `--help`.

## Four stages

1. Fetch all selected public source pages with finite retries and a descriptive User-Agent.
2. Normalize Tweet IDs, source text, timestamps, source labels, completeness, and verification metadata in memory.
3. Preview statistics without touching SQLite.
4. Commit one short transaction per record, record a batch checkpoint/change pre-image, then write an ignored local snapshot.

Network requests never run inside a SQLite write transaction.

After a successful source import, `corpus_coverage` is rebuilt for that batch as half-open UTC calendar-month windows (`[month start, next month start)`). The rows report material actually obtained, not a percentage of an unknown complete archive. Re-running the same batch replaces that batch's prior aggregate/coverage rows instead of duplicating them.

## Idempotency and precedence

- `tibo_posts.tweet_id` remains the canonical post key.
- `(source_id, source_record_key)` uniquely identifies a source observation.
- Re-running a source updates that evidence row instead of duplicating it.
- Multiple sources for one Tweet create multiple evidence rows, not multiple posts.
- A directly verified English source can replace a browser-translated Chinese “original” while preserving the Chinese text as translation.
- Conflicting English text is not silently replaced; both observations remain attributable and the post is marked for review.

## Resume and rollback

A failed import is marked `PARTIAL` with its last source record key. Re-running with the same batch prefix is idempotent and continues through already-recorded source keys. A rollback is scoped to one exact batch:

```powershell
backend\.venv\Scripts\python.exe scripts\import_historical_corpus.py `
  --rollback-batch historical-20260917T0135-modelyard
```

The rollback restores prior evidence/post state only if no newer update superseded it, removes batch-only historical posts, preserves unrelated evidence, and reports newer changes it deliberately skipped. It never truncates a corpus table or clears the database.

## Event verification

External labels are retained under `post_source_evidence.metadata_json`. A canonical event still requires an independent V2 review of mechanism, scope, execution stage, time basis, and evidence. Banked/reset-card/extra-credit cases are Special Resets and never advance the Full Reset cycle.

Schema v5 also stores the external label in `source_claimed_status` and the V2 result in
`local_verification_status`. Round-2 claims are separately persisted in
`historical_event_dispositions`; a zero row count in `reset_event_candidates` must not be interpreted as
zero unresolved historical claims.

`scripts/import_historical_corpus_round2.py` reads only the bounded requested sources. Git inputs are
pinned, TypeScript data is statically JSON-decoded, APIs are page/size/retry limited, and source
snapshots remain ignored. Stable source and disposition keys make reruns idempotent.

## Judge retrieval

Reviewed `historical_cases` store the post, context note, known historical outcome, outcome time precision, verification status, pattern tags, related Tweet IDs, and coverage limitation. The Judge receives at most six cases with outcome diversity. Retrieval is keyword/structure based in SQLite; no vector database or embedding service was added.

For historical replay, cases whose known outcome occurred after the replay cutoff are excluded. Current real-time judgement may use already completed history, but the prompt explicitly identifies it as analogy rather than current evidence.
