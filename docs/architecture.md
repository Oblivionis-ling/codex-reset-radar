# Minimal architecture

## Scope of this delivery

Milestones 0–2 implement one local process plus one browser extension:

```text
X Profile / with_replies / Search Latest
              |
       Chrome MV3 extension
              | HTTP localhost
              v
       FastAPI + SQLite backend
              |
       Rule → Context → optional DeepSeek
              |
       Resolver → Radar State
```

The extension is responsible for observing the rendered X DOM. It uses a `MutationObserver` for low-latency discovery and a 60-second fallback scan. A background service worker schedules a five-minute 72-hour search backfill and a six-hour seven-day reconciliation pass. The backend is the source of truth for normalized Tweets and their discovery sources.

All outbound calls in this phase are initiated by the local machine. No server, tunnel, public IP, X paid API, queue broker, or cloud database is used.

## Reliability choices

- Tweet identity is the X numeric status ID, with a database primary key and a unique `(tweet_id, source)` index.
- The extension keeps a bounded local seen-ID cache for reload efficiency; SQLite remains the authoritative deduplicator.
- Failed ingestion is retained in the extension's local pending queue and retried by the service worker.
- Every collector sends heartbeats. `healthy`, `warning`, and `offline` are derived from last heartbeat age; no Tweet is treated as evidence that the monitor is alive.
- Profile extraction accepts both current semantic selectors and structural fallbacks. It only accepts cards whose author links resolve to `thsottiaux`, preventing quoted Tweets from being ingested as Tibo posts.
- Search windows use UTC calendar days and X's exclusive `until` boundary.

## Phase B classification path

Every newly ingested Tweet is stored first, then classified in a background task. The rule layer is ordered and denial-first. Only ambiguous signals, hints, replies, and context-sensitive cases are eligible for DeepSeek. Rule, AI (when available), and final results are retained as separate audit rows. Provider failures leave the Tweet and Rule result intact, mark the Final result as pending, and never crash the collector.

The Radar engine derives one of the six fixed states from non-expired Final results and appends state changes to history. It does not calculate unsupported probability forecasts.

## Deliberate non-goals

No notification channel, GitHub mirror, or Dashboard is wired yet. Those remain later phases and do not participate in the local classification path.
