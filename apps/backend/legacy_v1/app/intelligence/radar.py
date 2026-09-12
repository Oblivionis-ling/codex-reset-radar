from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Classification, RadarState, RadarStateHistory


RADAR_STATES = ("QUIET", "WATCH", "LIKELY", "IMMINENT", "ANNOUNCED", "CONFIRMED")
STATE_RANK = {state: index for index, state in enumerate(RADAR_STATES)}


@dataclass(frozen=True)
class RadarDecision:
    state: str
    confidence: float
    urgency: str
    trigger_tweet_id: str | None
    reason: str
    expires_at: datetime | None
    previous_state: str | None = None
    changed: bool = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def signal_expiry(category: str, urgency: str | None, signal_time: datetime) -> datetime | None:
    """Return a bounded lifetime for non-terminal signals."""
    if category == "reset_hint":
        if urgency in {"now", "within_6h"}:
            return signal_time + timedelta(hours=12)
        if urgency == "within_24h":
            return signal_time + timedelta(hours=36)
        return signal_time + timedelta(hours=72)
    if category == "quota_information":
        return signal_time + timedelta(hours=24)
    if category == "reset_in_progress":
        return signal_time + timedelta(hours=24)
    # Announcements remain visible until a later confirmed event; confirmed is
    # an event-level state rather than a temporary prediction.
    return None


def classify_signal(row: Classification, now: datetime) -> RadarDecision | None:
    confidence = max(0.0, min(1.0, row.confidence or 0.0))
    signal_time = as_utc(row.created_at) or now
    if row.classifier_type != "final":
        return None
    if row.category == "reset_confirmed":
        return RadarDecision("CONFIRMED", confidence, row.urgency or "now", row.tweet_id, row.reason or "Reset confirmed.", None)
    if row.category == "reset_announcement":
        return RadarDecision("ANNOUNCED", confidence, row.urgency or "unknown", row.tweet_id, row.reason or "Reset announced.", None)
    if row.category == "reset_in_progress":
        return RadarDecision("ANNOUNCED", confidence, row.urgency or "now", row.tweet_id, row.reason or "Reset appears in progress.", signal_expiry(row.category, row.urgency, signal_time))
    if row.category == "reset_hint":
        if confidence >= 0.85 and row.urgency in {"now", "within_6h", "within_24h"}:
            state = "IMMINENT"
        elif confidence >= 0.75:
            state = "LIKELY"
        elif confidence >= 0.50:
            state = "WATCH"
        else:
            return None
        return RadarDecision(state, confidence, row.urgency or "unknown", row.tweet_id, row.reason or "Reset hint detected.", signal_expiry(row.category, row.urgency, signal_time))
    if row.category == "quota_information" and confidence >= 0.50:
        return RadarDecision("WATCH", confidence, row.urgency or "unknown", row.tweet_id, row.reason or "Quota information detected.", signal_expiry(row.category, row.urgency, signal_time))
    return None


def recompute_radar(session: Session, now: datetime | None = None) -> RadarDecision:
    current_time = now or utc_now()
    rows = session.scalars(select(Classification).where(Classification.classifier_type == "final")).all()
    latest_by_tweet: dict[str, Classification] = {}
    for row in rows:
        previous = latest_by_tweet.get(row.tweet_id)
        if previous is None or (as_utc(row.created_at) or current_time) > (as_utc(previous.created_at) or current_time):
            latest_by_tweet[row.tweet_id] = row
    signals = [signal for row in latest_by_tweet.values() if (signal := classify_signal(row, current_time)) is not None]
    active = [signal for signal in signals if signal.expires_at is None or signal.expires_at > current_time]
    if not active:
        return RadarDecision("QUIET", 0.0, "unknown", None, "No active reset signal.", None)
    return max(active, key=lambda signal: (STATE_RANK[signal.state], signal.confidence))


def update_radar(session: Session, now: datetime | None = None) -> RadarDecision:
    decision = recompute_radar(session, now)
    record = session.get(RadarState, 1)
    previous_state = record.state if record else None
    if record is None:
        record = RadarState(id=1)
        session.add(record)
    changed = previous_state != decision.state or record.trigger_tweet_id != decision.trigger_tweet_id
    record.state = decision.state
    record.confidence = decision.confidence
    record.urgency = decision.urgency
    record.trigger_tweet_id = decision.trigger_tweet_id
    record.reason = decision.reason
    record.updated_at = utc_now()
    record.expires_at = decision.expires_at
    if changed:
        session.add(
            RadarStateHistory(
                state=decision.state,
                confidence=decision.confidence,
                urgency=decision.urgency,
                trigger_tweet_id=decision.trigger_tweet_id,
                reason=decision.reason,
                changed_at=utc_now(),
                expires_at=decision.expires_at,
            )
        )
    session.flush()
    return RadarDecision(
        state=decision.state,
        confidence=decision.confidence,
        urgency=decision.urgency,
        trigger_tweet_id=decision.trigger_tweet_id,
        reason=decision.reason,
        expires_at=decision.expires_at,
        previous_state=previous_state,
        changed=changed,
    )
