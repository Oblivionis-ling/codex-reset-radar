# Product pipeline cross-check procedure

The DeepSeek side of corpus review is the current product, not a separate reviewer script or Prompt.

## Isolated environment

Use a database and log directory below `runtime/review/<run-id>/`, a distinct run ID, and no notification
delivery. Never target `runtime/data/codex-reset-radar-v2.db`; the replay entry point rejects that path.
The package contains no GPT labels when it is imported.

Existing reviewed historical cases may be loaded as the product’s baseline corpus, but they retain an
exposure marker. A case is unavailable before its outcome time, and a current post cannot retrieve its
own case.

## Required product path

```text
standard post import
  -> Database.upsert_posts_detailed
  -> persistent processing_jobs
  -> IntelligencePipeline workers
  -> current DeepSeek analysis and translation Prompts
  -> current event/candidate normalization
  -> reset cycle rebuild
  -> current historical-case retrieval
  -> current DeepSeek Judge
  -> persisted results
  -> current API serialization and Web read
```

`scripts/replay_corpus_pipeline.py` only orchestrates isolation, queueing, bounded waiting, historical
clock values, and result export. It calls `IntelligencePipeline`; it has no classification Prompt and no
answer key.

Targeted reruns may select repeated `--tweet-id` arguments and use `--no-existing-cases` to exclude the
old case library entirely. Label such runs as targeted semantic/regression checks, not a complete
historical forecast reconstruction. `--max-requests` caps actual provider HTTP attempts including retries;
normal product workers still perform analysis, translation, event normalization, and Judge. Partial
persisted results are exported on exit. Result exports include candidates as well as formal events, so
an announcement left pending cannot disappear from the evidence. Runtime and log paths remain isolated.

## Historical clock

Database post, event, cycle, previous-Judge, and historical-case queries accept `as_of`. The Judge uses
the same `as_of` as its business time. Network timeouts, retry delays, and task scheduling continue to use
real/monotonic time. This prevents future posts, events, outcomes, or judgements from leaking into an old
window without triggering thousands of hourly jobs.

Representative windows cover pre-announcement hints, explicit announcements, in-progress propagation,
completion, delay/correction, Special-only banked events, compensation, and ordinary product discussion.
Historical outputs are labelled replay results and are never described as evidence that the old online
service predicted them live.

## Comparison

Compare facts first: author/body integrity, negation, event mechanism, scope, stage, time basis,
multi-effects, merge/split, and cycle impact. Then compare Action Level, 24/48/72-hour horizons, estimate,
evidence, validity, and future leakage. Wording differences are informational unless they change meaning.

Missing execution, invented quotes, future announcements promoted to completed events, Full/Special
confusion, dropped effects, wrong cycle movement, and substantive Judge differences enter
`NEEDS_HUMAN_REVIEW`. The comparison tool leaves `human_decision` null.
