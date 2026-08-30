# Data model

The SQLite schema is created on backend startup.

- `tweets`: one normalized raw Tweet per `tweet_id`.
- `tweet_sources`: every collector that saw a Tweet, with first/last seen time and sighting count.
- `classifications`: reserved for transparent rule/AI results in the intelligence phase.
- `ai_usage`: one row per attempted DeepSeek call, including outcome and optional token counts.
- `reset_events`: reserved for confirmed Reset events and signal lead-time links.
- `status_events`: reserved for the independent OpenAI Status collector.
- `alerts`: reserved for `(tweet_id, alert_type)` notification deduplication.
- `monitor_health`: latest heartbeat and state for each collector/backend component.
- `sync_queue`: durable retry records for the future GitHub mirror.
- `radar_state`: current derived Radar state.
- `radar_state_history`: append-only state-change audit trail.

The ingestion endpoint is idempotent. A repeated Tweet updates its source sighting rather than creating another raw Tweet.
