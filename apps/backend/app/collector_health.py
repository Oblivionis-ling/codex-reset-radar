"""One read-only clock-aware view for API, scheduler and Judge."""
from datetime import UTC, datetime

FRESH_SECONDS = 15 * 60
FUTURE_SKEW_SECONDS = 120
REQUIRED = ('profile_monitor', 'replies_monitor')
COMPONENTS = (*REQUIRED, 'search_backfill')


def collector_health(states: dict, *, at: datetime | None = None) -> dict:
    current = at or datetime.now(UTC)
    items = {}
    for name in dict.fromkeys((*COMPONENTS, *states)):
        stored = states.get(name, {})
        age, reason = None, 'NO_HEARTBEAT'
        try:
            observed = datetime.fromisoformat(stored['last_seen_at'].replace('Z', '+00:00'))
            if observed.tzinfo is None:
                raise ValueError()
            age = (current - observed).total_seconds()
            reason = ('CLOCK_SKEW' if age < -FUTURE_SKEW_SECONDS else
                      'HEARTBEAT_EXPIRED' if age > FRESH_SECONDS else
                      'REPORTED_UNHEALTHY' if stored.get('state') not in ('healthy', 'warning') else 'FRESH')
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
        items[name] = {**stored, 'reported_state': stored.get('state'),
                       'state': stored.get('state') if reason == 'FRESH' else 'stale',
                       'age_seconds': round(age, 1) if age is not None else None,
                       'checked_at': current.isoformat().replace('+00:00', 'Z'), 'reason': reason}
    return {'data_health': 'HEALTHY' if all(items[n]['reason'] == 'FRESH' for n in REQUIRED) else 'STALE',
            'collector': items, 'freshness_seconds': FRESH_SECONDS}
