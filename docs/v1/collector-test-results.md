# Collector verification — 2026-08-28

## Automated results

- Backend: `3 passed` with the local Python 3.12 environment.
  - One Tweet ingested from `profile_dom`, `search`, and `with_replies` remains one SQLite row with three source records.
  - `/health` and component heartbeat records are observable.
  - All eight Phase A/core-reserved SQLite tables are created on startup.
- Extension: `5 passed`.
  - Semantic Tweet card parsing.
  - Nested/quoted card filtering.
  - Replies and parent status extraction.
  - Structural fallback parsing.
  - UTC day-window generation for a 72-hour search pass.
- TypeScript: `npx tsc --noEmit` passed.
- MV3 build: `npm run build` passed and generated `extension/dist/manifest.json`, `background.js`, and `content.js`.

## Live DOM check

The available in-app browser was able to load `https://x.com/thsottiaux` on 2026-08-28. The visible Profile DOM contained `article` Tweet cards, relative `/thsottiaux/status/<numeric-id>` links, readable Tweet text, and relative `<time>` links. The sample visible status IDs included `2093207246977318928`, `2093074717590921245`, `2093014447833116908`, `2092862554632826968`, and `2092756702349398036`.

The same browser session reported:

- `https://x.com/thsottiaux/with_replies`: X displayed “出错了，请尝试重新加载” and no reply cards were available to inspect.
- `https://x.com/search?q=from%3Athsottiaux&src=typed_query&f=live`: X displayed the login wall; no Search result cards were available.

The extension was not installed into the live browser during this verification, so the results above are a live DOM compatibility check plus automated parser/ingestion tests, not a continuous end-to-end run against an authenticated X session.

## Current漏报风险

1. **High — Search backfill is unverified until X is logged in.** The current Search page is blocked by X's login wall. The extension reports `search_backfill=warning` instead of treating the empty page as “no Tweets”.
2. **High — Replies page behavior is currently an X-side error.** The collector cannot recover replies from a page that exposes no cards. It reports a warning and will retry on the next route change/fallback scan.
3. **Medium — DOM churn.** The parser uses semantic selectors plus `article`/link/text fallbacks, but X can still change markup or accessibility labels. Numeric status links are the strongest identity signal.
4. **Medium — Only rendered/loaded cards can be observed.** Profile discovery depends on X's virtualized timeline and the page's current scroll position; Search backfill scrolls six viewport steps per UTC day window.
5. **Medium — Browser lifecycle and throttling.** Chrome/Edge may delay alarms or background tabs. Persistent extension queues and SQLite deduplication protect delivery after short backend/network interruptions, but they cannot recover cards that X never rendered.
6. **Low — Missing `<time datetime>`.** A Tweet is still ingested if its ID/text are available, but `created_at` remains null when X does not expose an absolute timestamp.

The next gate is an authenticated, multi-hour run with Profile, Replies, and Search tabs open, followed by deliberate page reload and backend restart checks. AI Classification should wait until those collector observations are available.
