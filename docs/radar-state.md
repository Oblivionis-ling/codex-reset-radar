# Radar State rules

The Radar State engine exposes only `QUIET`, `WATCH`, `LIKELY`, `IMMINENT`, `ANNOUNCED`, and `CONFIRMED`.

- `QUIET`: no active signal.
- `WATCH`: weak hint (`reset_hint` confidence 0.50–0.74) or recent quota information.
- `LIKELY`: `reset_hint` confidence >= 0.75 without a clear time window.
- `IMMINENT`: `reset_hint` confidence >= 0.85 with `now`, `within_6h`, or `within_24h` urgency.
- `ANNOUNCED`: high-confidence `reset_announcement` or `reset_in_progress`.
- `CONFIRMED`: `reset_confirmed`.

Signal expiry is intentionally bounded and depends on urgency:

- `reset_hint`: 12 hours for `now`/`within_6h`, 36 hours for `within_24h`, and 72 hours otherwise.
- `quota_information`: 24 hours from the classification timestamp.
- `reset_in_progress`: 24 hours from the classification timestamp.
- `reset_announcement`: remains until a confirmed event or manual handling in a later phase.
- `reset_confirmed`: remains an event-level state.

Every state or trigger change is appended to `radar_state_history`; the current singleton is available through `GET /api/radar`.
