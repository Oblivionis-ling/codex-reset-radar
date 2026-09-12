from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HeartbeatHistory, MonitorDiagnosticEvent, MonitorHealth, Tweet, TweetSource
from app.observability import (
    BACKEND_INSTANCE_ID,
    append_event,
    current_request_id,
    current_trace_id,
    is_sqlite_lock_error,
    redact_secret,
    utc_now as observability_now,
    utc_iso,
)
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


def ingest_batch(session: Session, tweets: list[TweetPayload], *, trace_id: str | None = None) -> tuple[int, int]:
    created = 0
    for tweet in tweets:
        if ingest_one(session, tweet):
            created += 1
    db_started = observability_now()
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        event_name = "SQLITE_LOCK_DETECTED" if is_sqlite_lock_error(exc) else "DB_OPERATION_FAILED"
        append_event(
            "backend",
            event_name,
            level="ERROR",
            component="ingestion",
            trace_id=trace_id or current_trace_id(),
            error_type=type(exc).__name__,
            metadata={
                "operation": "tweet_ingestion",
                "table": "tweets/tweet_sources",
                "error": redact_secret(exc),
                "suspected_contention": "reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
            },
            operation="tweet_ingestion",
            table="tweets/tweet_sources",
            error=redact_secret(exc),
            duration_ms=round((observability_now() - db_started).total_seconds() * 1000, 3),
            suspected_contention="reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
        )
        raise
    duration_ms = round((observability_now() - db_started).total_seconds() * 1000, 3)
    append_event(
        "backend",
        "DB_OPERATION_COMPLETED",
        component="ingestion",
        trace_id=trace_id or current_trace_id(),
        duration_ms=duration_ms,
        result="success",
        metadata={"operation": "tweet_ingestion", "table": "tweets/tweet_sources"},
        operation="tweet_ingestion",
        table="tweets/tweet_sources",
    )
    if duration_ms > 500:
        append_event(
            "backend",
            "DB_SLOW_OPERATION",
            level="WARNING",
            component="ingestion",
            trace_id=trace_id or current_trace_id(),
            duration_ms=duration_ms,
            result="slow",
            metadata={"operation": "tweet_ingestion", "table": "tweets/tweet_sources"},
            operation="tweet_ingestion",
            table="tweets/tweet_sources",
        )
    return created, len(tweets) - created


def record_heartbeat(session: Session, payload: HeartbeatPayload) -> MonitorHealth:
    backend_received_at = observability_now()
    now = payload.observed_at or backend_received_at
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
    history_metadata = {
        **payload.metadata,
        "backend_instance_id": BACKEND_INSTANCE_ID,
    }
    history = HeartbeatHistory(
        component=payload.component,
        instance_id=payload.instance_id or (BACKEND_INSTANCE_ID if payload.component == "backend" else None),
        sequence=payload.sequence,
        trace_id=payload.trace_id or current_trace_id(),
        request_id=payload.request_id or current_request_id(),
        client_observed_at=now,
        backend_received_at=backend_received_at,
        state=payload.state,
        error=redact_secret(payload.error) if payload.error else None,
        metadata_json=json.dumps(history_metadata, ensure_ascii=False, default=str),
    )
    if history.sequence is not None and history.instance_id:
        previous_history = session.scalar(
            select(HeartbeatHistory)
            .where(
                HeartbeatHistory.component == payload.component,
                HeartbeatHistory.instance_id == history.instance_id,
                HeartbeatHistory.sequence.is_not(None),
            )
            .order_by(HeartbeatHistory.sequence.desc())
            .limit(1)
        )
        if previous_history and history.sequence > (previous_history.sequence or 0) + 1:
            append_event(
                "backend",
                "HEARTBEAT_SEQUENCE_GAP",
                level="WARNING",
                component=payload.component,
                instance_id=history.instance_id,
                trace_id=history.trace_id,
                request_id=history.request_id,
                sequence=history.sequence,
                metadata={
                    "previous_sequence": previous_history.sequence,
                    "current_sequence": history.sequence,
                    "missing_from": (previous_history.sequence or 0) + 1,
                    "missing_to": history.sequence - 1,
                },
                previous_sequence=previous_history.sequence,
                current_sequence=history.sequence,
            )
    session.add(history)
    db_started = observability_now()
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        event_name = "SQLITE_LOCK_DETECTED" if is_sqlite_lock_error(exc) else "BACKEND_HEARTBEAT_DB_WRITE_FAILED"
        append_event(
            "backend",
            event_name,
            level="ERROR",
            component="backend",
            instance_id=payload.instance_id or (BACKEND_INSTANCE_ID if payload.component == "backend" else None),
            trace_id=payload.trace_id or current_trace_id(),
            request_id=payload.request_id or current_request_id(),
            sequence=payload.sequence,
            error_type=type(exc).__name__,
            metadata={
                "component": payload.component,
                "table": "monitor_health/heartbeat_history",
                "error": redact_secret(exc),
                "suspected_contention": "reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
            },
            operation="heartbeat_write",
            table="monitor_health/heartbeat_history",
            error=redact_secret(exc),
            duration_ms=round((observability_now() - db_started).total_seconds() * 1000, 3),
            suspected_contention="reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
        )
        logger.exception("BACKEND_HEARTBEAT_DB_WRITE_FAILED component=%s", payload.component)
        raise
    db_committed_at = observability_now()
    history.db_committed_at = db_committed_at
    # The timestamp above is intentionally stored after the first commit.  A
    # second tiny commit makes the client/backend/DB timing explicit while
    # preserving the existing monitor_health semantics.
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        event_name = "SQLITE_LOCK_DETECTED" if is_sqlite_lock_error(exc) else "BACKEND_HEARTBEAT_DB_WRITE_FAILED"
        append_event(
            "backend",
            event_name,
            level="ERROR",
            component="backend",
            instance_id=payload.instance_id or (BACKEND_INSTANCE_ID if payload.component == "backend" else None),
            trace_id=payload.trace_id or current_trace_id(),
            request_id=payload.request_id or current_request_id(),
            sequence=payload.sequence,
            error_type=type(exc).__name__,
            metadata={
                "component": payload.component,
                "table": "heartbeat_history",
                "error": redact_secret(exc),
                "suspected_contention": "reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
            },
            operation="heartbeat_history_commit_timestamp",
            table="heartbeat_history",
            error=redact_secret(exc),
            duration_ms=round((observability_now() - db_started).total_seconds() * 1000, 3),
            suspected_contention="reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
        )
        logger.exception("BACKEND_HEARTBEAT_DB_WRITE_FAILED component=%s table=heartbeat_history", payload.component)
        raise
    db_duration_ms = round((db_committed_at - db_started).total_seconds() * 1000, 3)
    append_event(
        "backend",
        "HEARTBEAT_DB_COMMITTED",
        component="backend",
        instance_id=payload.instance_id or (BACKEND_INSTANCE_ID if payload.component == "backend" else None),
        trace_id=payload.trace_id or current_trace_id(),
        request_id=payload.request_id or current_request_id(),
        sequence=payload.sequence,
        duration_ms=db_duration_ms,
        result="success",
        metadata={
            "component": payload.component,
            "backend_instance_id": BACKEND_INSTANCE_ID,
            "client_observed_at": utc_iso(now),
            "backend_received_at": utc_iso(backend_received_at),
            "db_committed_at": utc_iso(db_committed_at),
            "db_duration_ms": db_duration_ms,
        },
        client_observed_at=utc_iso(now),
        backend_received_at=utc_iso(backend_received_at),
        db_committed_at=utc_iso(db_committed_at),
        backend_instance_id=BACKEND_INSTANCE_ID,
    )
    logger.info("Monitor heartbeat component=%s state=%s", payload.component, payload.state)
    return health


def record_diagnostic(
    session: Session,
    payload: DiagnosticPayload,
    *,
    commit: bool = True,
) -> MonitorDiagnosticEvent:
    observed_at = payload.observed_at or utc_now()
    details = dict(payload.details)
    if payload.instance_id is not None:
        details.setdefault("instance_id", payload.instance_id)
    if payload.sequence is not None:
        details.setdefault("sequence", payload.sequence)
    if payload.trace_id is not None:
        details.setdefault("trace_id", payload.trace_id)
    if payload.request_id is not None:
        details.setdefault("request_id", payload.request_id)
    event = MonitorDiagnosticEvent(
        component=payload.component,
        event=payload.event,
        observed_at=observed_at,
        details_json=json.dumps(details, ensure_ascii=False, default=str),
        created_at=utc_now(),
    )
    session.add(event)
    if not commit:
        # Batch callers commit once after adding all events. The event ID is
        # populated by that commit, so no per-event flush is needed.
        return event
    db_started = observability_now()
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        event_name = "SQLITE_LOCK_DETECTED" if is_sqlite_lock_error(exc) else "DB_OPERATION_FAILED"
        append_event(
            "backend",
            event_name,
            level="ERROR",
            component="backend",
            trace_id=payload.trace_id or current_trace_id(),
            request_id=payload.request_id or current_request_id(),
            sequence=payload.sequence,
            error_type=type(exc).__name__,
            metadata={
                "operation": "diagnostic_write",
                "table": "monitor_diagnostic_events",
                "error": redact_secret(exc),
                "suspected_contention": "reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
            },
            operation="diagnostic_write",
            table="monitor_diagnostic_events",
            error=redact_secret(exc),
            duration_ms=round((observability_now() - db_started).total_seconds() * 1000, 3),
            suspected_contention="reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
        )
        raise
    logger.info(
        "Monitor diagnostic component=%s event=%s observed_at=%s",
        payload.component,
        payload.event,
        observed_at.isoformat(),
    )
    duration_ms = round((observability_now() - db_started).total_seconds() * 1000, 3)
    # Successful per-event DB completion is intentionally not duplicated in
    # Backend JSONL. The authoritative row is monitor_diagnostic_events;
    # only slow or failed writes become structured Backend events.
    if duration_ms > 500:
        append_event(
            "backend",
            "DB_SLOW_OPERATION",
            level="WARNING",
            component="diagnostics",
            trace_id=payload.trace_id or current_trace_id(),
            request_id=payload.request_id or current_request_id(),
            sequence=payload.sequence,
            duration_ms=duration_ms,
            result="slow",
            metadata={"operation": "diagnostic_write", "table": "monitor_diagnostic_events"},
            operation="diagnostic_write",
            table="monitor_diagnostic_events",
        )
    return event
