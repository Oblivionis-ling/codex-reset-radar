from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MonitorDiagnosticEvent, MonitorHealth, Tweet, TweetSource
from app.schemas import DiagnosticPayload, HeartbeatPayload, TweetPayload


logger = logging.getLogger("radar.ingestion")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ingest_one(session: Session, payload: TweetPayload) -> bool:
    """Insert or merge one Tweet. Return True for a new raw Tweet."""
    now = utc_now()
    tweet_id = payload.tweet_id.strip()
    tweet = session.get(Tweet, tweet_id)
    is_new = tweet is None

    if tweet is None:
        tweet = Tweet(
            tweet_id=tweet_id,
            author=payload.author.strip().lstrip("@").lower() or "thsottiaux",
            text=payload.text.strip(),
            created_at=payload.created_at,
            url=payload.url or f"https://x.com/thsottiaux/status/{tweet_id}",
            is_reply=payload.is_reply,
            reply_to=payload.reply_to,
            discovered_at=payload.discovered_at or now,
        )
        session.add(tweet)
        logger.info("Tweet discovered tweet_id=%s source=%s", tweet_id, payload.source)
    else:
        # A later collector can fill fields that an earlier DOM scan missed.
        if not tweet.text and payload.text:
            tweet.text = payload.text.strip()
        if tweet.created_at is None and payload.created_at:
            tweet.created_at = payload.created_at
        if not tweet.url and payload.url:
            tweet.url = payload.url
        if tweet.reply_to is None and payload.reply_to:
            tweet.reply_to = payload.reply_to
        tweet.is_reply = tweet.is_reply or payload.is_reply
        logger.info("Tweet deduplicated tweet_id=%s source=%s", tweet_id, payload.source)

    source = session.scalar(
        select(TweetSource).where(TweetSource.tweet_id == tweet_id, TweetSource.source == payload.source)
    )
    if source is None:
        session.add(TweetSource(tweet_id=tweet_id, source=payload.source, first_seen_at=now, last_seen_at=now))
    else:
        source.last_seen_at = now
        source.sightings += 1
    return is_new


def ingest_batch(session: Session, tweets: list[TweetPayload]) -> tuple[int, int]:
    created = 0
    for tweet in tweets:
        if ingest_one(session, tweet):
            created += 1
    session.commit()
    return created, len(tweets) - created


def record_heartbeat(session: Session, payload: HeartbeatPayload) -> MonitorHealth:
    now = payload.observed_at or utc_now()
    health = session.get(MonitorHealth, payload.component)
    if health is None:
        health = MonitorHealth(
            component=payload.component,
            state=payload.state,
            last_heartbeat=now,
            last_tweet_seen=payload.last_tweet_seen,
            last_error=payload.error,
            metadata_json=json.dumps(payload.metadata, ensure_ascii=False),
            updated_at=utc_now(),
        )
        session.add(health)
    else:
        health.state = payload.state
        health.last_heartbeat = now
        health.last_tweet_seen = payload.last_tweet_seen or health.last_tweet_seen
        health.last_error = payload.error
        health.metadata_json = json.dumps(payload.metadata, ensure_ascii=False)
        health.updated_at = utc_now()
    session.commit()
    logger.info("Monitor heartbeat component=%s state=%s", payload.component, payload.state)
    return health


def record_diagnostic(session: Session, payload: DiagnosticPayload) -> MonitorDiagnosticEvent:
    observed_at = payload.observed_at or utc_now()
    event = MonitorDiagnosticEvent(
        component=payload.component,
        event=payload.event,
        observed_at=observed_at,
        details_json=json.dumps(payload.details, ensure_ascii=False, default=str),
        created_at=utc_now(),
    )
    session.add(event)
    session.commit()
    logger.info(
        "Monitor diagnostic component=%s event=%s observed_at=%s",
        payload.component,
        payload.event,
        observed_at.isoformat(),
    )
    return event
