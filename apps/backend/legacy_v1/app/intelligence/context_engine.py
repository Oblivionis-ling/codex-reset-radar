from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ResetEvent, StatusEvent, Tweet


RELATED_TERMS = ("codex", "quota", "limit", "usage", "reset", "button", "dust", "gift", "surprise", "milestone")


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def tweet_dict(tweet: Tweet | None) -> dict[str, Any] | None:
    if tweet is None:
        return None
    return {
        "tweet_id": tweet.tweet_id,
        "author": tweet.author,
        "text": tweet.text,
        "created_at": as_utc(tweet.created_at).isoformat() if tweet.created_at else None,
        "url": tweet.url,
        "is_reply": tweet.is_reply,
        "reply_to": tweet.reply_to,
    }


def build_context(session: Session, tweet: Tweet) -> dict[str, Any]:
    parent = session.get(Tweet, tweet.reply_to) if tweet.reply_to else None
    candidates = session.scalars(
        select(Tweet).where(Tweet.tweet_id != tweet.tweet_id).order_by(Tweet.discovered_at.desc()).limit(100)
    ).all()
    scored: list[tuple[int, datetime, Tweet]] = []
    for candidate in candidates:
        text = candidate.text.casefold()
        score = sum(2 for term in RELATED_TERMS if term in text)
        if candidate.tweet_id == tweet.reply_to:
            score += 20
        if tweet.reply_to and candidate.reply_to == tweet.reply_to:
            score += 8
        if score:
            scored.append((score, as_utc(candidate.discovered_at) or datetime.min.replace(tzinfo=timezone.utc), candidate))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    reset = session.scalar(select(ResetEvent).order_by(ResetEvent.event_time.desc()).limit(1))
    status_events = session.scalars(select(StatusEvent).order_by(StatusEvent.event_time.desc()).limit(5)).all()
    return {
        "current_tweet": tweet_dict(tweet),
        "parent_context": tweet_dict(parent),
        "recent_related_tweets": [tweet_dict(candidate) for _, _, candidate in scored[:10]],
        "last_confirmed_reset": {
            "event_time": as_utc(reset.event_time).isoformat() if reset else None,
            "source": reset.source if reset else None,
            "evidence_tweet_id": reset.evidence_tweet_id if reset else None,
            "notes": reset.notes if reset else None,
        }
        if reset
        else None,
        "recent_status_events": [
            {"event_time": as_utc(event.event_time).isoformat(), "status": event.status, "summary": event.summary}
            for event in status_events
        ],
    }

