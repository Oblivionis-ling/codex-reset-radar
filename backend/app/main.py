from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select, text

from app.config import get_settings
from app.database import create_database
from app.ingestion import ingest_batch, record_diagnostic, record_heartbeat
from app.classifiers.service import classify_tweet, classify_tweet_ids, translate_tweet_ids
from app.intelligence.forecast import build_forecast, build_reset_history, derive_usage_advice
from app.intelligence.radar import update_radar
from app.models import (
    Alert,
    Classification,
    HealthStateHistory,
    HeartbeatHistory,
    MonitorDiagnosticEvent,
    MonitorHealth,
    RadarState,
    ResetEvent,
    Tweet,
    TweetSource,
)
from app.notifications.alert_manager import AlertManager, NOTIFICATION_DIAGNOSTIC_LOG_PATH, NOTIFICATION_TEST_LOG_PATH, derived_monitor_state
from app.observability import (
    BACKEND_INSTANCE_ID,
    BACKEND_EVENTS_PATH,
    EVENTS_DIR,
    RUNTIME_LOG_PATH,
    PROCESS_STARTED_AT,
    TaskSupervisor,
    append_event,
    backend_ready,
    backend_shutdown_completed,
    backend_shutdown_started,
    configure_runtime_logging,
    current_request_id,
    current_trace_id,
    event_loop_watchdog,
    initialise_backend_process,
    install_asyncio_exception_handler,
    install_exception_hooks,
    is_sqlite_lock_error,
    new_id,
    observability_context,
    prune_jsonl,
    prune_event_shards,
    read_all_events,
    read_events,
    register_atexit_shutdown,
    redact_secret,
    utc_iso,
)
from app.schemas import DiagnosticBatchPayload, DiagnosticPayload, HeartbeatPayload, TweetBatch


configure_runtime_logging()
install_exception_hooks()
register_atexit_shutdown()
logger = logging.getLogger("radar")

MIRROR_CADENCE_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "mirror-cadence.jsonl"
_MIRROR_LOG_LOCK = threading.Lock()
_MIRROR_JOB_LOCK = threading.Lock()
_MIRROR_LOG_SCALAR_FIELDS = (
    "cycle_started_at",
    "snapshot_generated_at",
    "push_started_at",
    "sync_finished_at",
    "published_at",
    "mirror_synced_at",
    "duration_ms",
    "previous_success_at",
    "seconds_since_previous_success",
    "cycle_interval_seconds",
    "scheduler_cycle_interval_seconds",
    "configured_interval_seconds",
    "trigger",
    "result",
    "push_attempt",
    "attempt",
    "next_attempt",
    "retry_delay_seconds",
    "error_type",
    "terminal",
    "exit_code",
    "trace_id",
    "snapshot_id",
)
_MIRROR_LOG_NUMERIC_FIELDS = {
    "duration_ms",
    "seconds_since_previous_success",
    "cycle_interval_seconds",
    "scheduler_cycle_interval_seconds",
    "configured_interval_seconds",
    "push_attempt",
    "attempt",
    "next_attempt",
    "retry_delay_seconds",
    "exit_code",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _mirror_timestamp(value: datetime | None) -> str:
    return value.isoformat().replace("+00:00", "Z") if value else "-"


def _redact_mirror_text(value: str) -> str:
    redacted = " ".join(str(value or "").split())
    for name in ("GITHUB_TOKEN", "DEEPSEEK_API_KEY", "WXPUSHER_APP_TOKEN", "WXPUSHER_UID"):
        secret = os.getenv(name, "").strip()
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = re.sub(r"(https?://)([^/\s:@]+):([^@\s]+)@", r"\1[redacted]@", redacted)
    return redacted


def _classify_mirror_error(value: str) -> str:
    text = _redact_mirror_text(value).lower()
    if re.search(r"auth|authentication|permission denied|could not read username|401|403|repository not found", text):
        return "auth_failed"
    if re.search(r"non-fast-forward|rejected|conflict|would be overwritten", text):
        return "git_conflict"
    if re.search(r"dns|could not resolve host|name resolution|temporary failure in name resolution", text):
        return "network_dns"
    if re.search(r"timed out|timeout|time-out|operation timed out", text):
        return "network_timeout"
    if re.search(r"connection reset|recv failure|connection was reset|reset by peer", text):
        return "network_reset"
    if re.search(r"could not connect|failed to connect|connection failure|network is unreachable|network down", text):
        return "network_connect"
    if re.search(r"\bclone\b", text):
        return "clone_failed"
    if re.search(r"\bfetch\b", text):
        return "fetch_failed"
    if re.search(r"\bpush\b", text):
        return "push_failed"
    return "unknown"


def _parse_mirror_datetime(value: Any) -> datetime | None:
    if not value or value == "-":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class MirrorSyncResult:
    status: str
    sync_finished_at: datetime | None = None
    published_at: datetime | None = None
    attempt: int | None = None
    error_type: str | None = None
    reason: str | None = None


def _append_mirror_log(event: str, *, source: str, **fields: Any) -> None:
    """Persist mirror events through the unified writer and legacy path."""
    append_event(
        "mirror",
        event,
        component="mirror",
        instance_id=BACKEND_INSTANCE_ID,
        trace_id=fields.pop("trace_id", None),
        legacy_paths=(MIRROR_CADENCE_LOG_PATH,),
        source=source,
        **fields,
    )


def _parse_mirror_log_line(line: str) -> tuple[str, dict[str, Any]] | None:
    match = re.search(r"(PUBLIC_MIRROR_[A-Z_]+)(?:\s+(.*))?$", line.strip())
    if not match:
        return None
    event, payload = match.group(1), (match.group(2) or "").replace("|", " ")
    fields: dict[str, Any] = {}
    for key in _MIRROR_LOG_SCALAR_FIELDS:
        value_match = re.search(rf"(?:^|\s){re.escape(key)}=([^\s]+)", payload)
        if not value_match:
            continue
        value: Any = value_match.group(1)
        if key in _MIRROR_LOG_NUMERIC_FIELDS:
            try:
                value = float(value) if "." in value else int(value)
            except ValueError:
                pass
        fields[key] = value
    reason_match = re.search(r"(?:^|\s)reason=(.+?)(?=\s+(?:output|error)=|$)", payload)
    if reason_match:
        fields["reason"] = _redact_mirror_text(reason_match.group(1).strip())[:500]
    return event, fields


def _log_mirror_script_events(output: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in output.splitlines():
        if "PUBLIC_MIRROR_" in line:
            redacted = _redact_mirror_text(line)
            logger.info("%s", redacted)
            parsed = _parse_mirror_log_line(redacted)
            if parsed:
                event, fields = parsed
                _append_mirror_log(event, source="sync-script", **fields)
                events.append({"event": event, **fields})
    return events


def serialize_datetime(value: datetime | None) -> str | None:
    return as_utc(value).isoformat() if value else None


def as_utc(value: datetime) -> datetime:
    """SQLite returns timezone columns as naive datetimes; normalize before arithmetic."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {"_parse_error": True}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _forecast_payload(session, now: datetime | None = None) -> dict[str, Any]:
    """Build forecast data from explicit events or latest final classifications."""

    rows = session.execute(
        select(Classification, Tweet)
        .join(Tweet, Tweet.tweet_id == Classification.tweet_id)
        .where(Classification.classifier_type == "final")
        .order_by(Classification.id.desc())
    ).all()
    latest_by_tweet: dict[str, tuple[Classification, Tweet]] = {}
    for classification, tweet in rows:
        latest_by_tweet.setdefault(tweet.tweet_id, (classification, tweet))

    confirmed = [
        {
            "event_time": tweet.created_at or classification.created_at,
            "evidence_tweet_id": tweet.tweet_id,
            "text": tweet.text,
        }
        for classification, tweet in latest_by_tweet.values()
        if classification.category == "reset_confirmed"
    ]
    explicit = [
        {
            "event_time": event.event_time,
            "source": event.source,
            "evidence_tweet_id": event.evidence_tweet_id,
            "notes": event.notes,
        }
        for event in session.scalars(select(ResetEvent).order_by(ResetEvent.event_time.desc())).all()
    ]
    history = build_reset_history(explicit, confirmed)
    hints = [
        {
            "event_time": tweet.created_at or classification.created_at,
            "evidence_tweet_id": tweet.tweet_id,
            "text": tweet.text,
            "urgency": classification.urgency,
        }
        for classification, tweet in latest_by_tweet.values()
        if classification.category == "reset_hint"
    ]
    announcements = [
        {
            "event_time": tweet.created_at or classification.created_at,
            "evidence_tweet_id": tweet.tweet_id,
            "text": tweet.text,
        }
        for classification, tweet in latest_by_tweet.values()
        if classification.category == "reset_announcement"
    ]
    forecast = build_forecast(history, hints, announcements, now=now)
    record = session.get(RadarState, 1)
    advice = derive_usage_advice(record.state if record else "QUIET", forecast, now=now)
    return {"forecast": forecast, "usage_advice": advice, "reset_history": history}


def _observability_event_json(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in {"payload", "body"}}


def _require_local_observability(request: Request) -> None:
    host = request.client.host if request.client else None
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Observability API is local-only")


MAX_OBSERVABILITY_LIMIT = 500
MAX_OBSERVABILITY_WINDOW = timedelta(days=14)


def _observability_since(value: str | None, *, default: timedelta = timedelta(hours=24)) -> datetime:
    now = utc_now()
    if not value:
        return now - default
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="since must be an ISO-8601 timestamp") from exc
    parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed < now - MAX_OBSERVABILITY_WINDOW:
        raise HTTPException(status_code=400, detail="since exceeds the 14-day observability window")
    return parsed


def create_app(database_url: str | None = None, database_path: Path | None = None) -> FastAPI:
    settings = get_settings()
    db_url = database_url or settings.database_url
    resolved_database_path = database_path or settings.database_path
    initialise_backend_process(resolved_database_path)
    engine, session_factory = create_database(db_url, resolved_database_path)
    try:
        with session_factory() as session:
            initial_tweet_count = int(session.scalar(select(func.count()).select_from(Tweet)) or 0)
    except Exception:
        initial_tweet_count = None
    try:
        with engine.connect() as connection:
            journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar()
        append_event(
            "backend",
            "SQLITE_JOURNAL_MODE",
            component="database",
            result="observed",
            metadata={"journal_mode": journal_mode},
            journal_mode=journal_mode,
        )
    except Exception as exc:
        append_event(
            "backend",
            "DB_OPERATION_FAILED",
            level="ERROR",
            component="database",
            error_type=type(exc).__name__,
            metadata={"operation": "read_journal_mode", "error": redact_secret(exc)},
            operation="read_journal_mode",
            error=redact_secret(exc),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.heartbeat_stop = asyncio.Event()
        app.state.monitor_alert_stop = asyncio.Event()
        app.state.mirror_stop = asyncio.Event()
        app.state.mirror_event = asyncio.Event()
        app.state.event_loop_stop = asyncio.Event()
        app.state.observability_retention_stop = asyncio.Event()
        app.state.ready = False
        supervisor = TaskSupervisor()
        app.state.task_supervisor = supervisor
        loop = asyncio.get_running_loop()
        install_asyncio_exception_handler(loop)
        with session_factory() as session:
            record_heartbeat(
                session,
                HeartbeatPayload(
                    component="backend",
                    instance_id=BACKEND_INSTANCE_ID,
                    sequence=0,
                    trace_id=new_id("hb-backend"),
                    state="healthy",
                ),
            )
            update_radar(session)
            session.commit()
            app.state.alert_manager.initialize_baseline(session)
            session.commit()
        tasks: list[str] = []
        supervisor.create_task(_backend_heartbeat_loop(session_factory, app.state.heartbeat_stop), "backend-heartbeat")
        tasks.append("backend-heartbeat")
        supervisor.create_task(
            _monitor_alert_loop(session_factory, app.state.monitor_alert_stop, app.state.alert_manager),
            "health-evaluator",
        )
        tasks.append("health-evaluator")
        supervisor.create_task(event_loop_watchdog(app.state.event_loop_stop, supervisor), "event-loop-watchdog")
        tasks.append("event-loop-watchdog")
        supervisor.create_task(
            _observability_retention_loop(session_factory, app.state.observability_retention_stop),
            "observability-retention",
        )
        tasks.append("observability-retention")
        mirror_started = False
        if settings.github_mirror_enabled:
            supervisor.create_task(_public_mirror_loop(settings, app.state.mirror_stop, app.state.mirror_event), "mirror-scheduler")
            tasks.append("mirror-scheduler")
            mirror_started = True
        app.state.ready = True
        backend_ready(
            tasks=tasks,
            db_ready=True,
            scheduler_started=True,
            mirror_started=mirror_started,
            alert_manager_ready=True,
        )
        try:
            yield
        finally:
            app.state.ready = False
            backend_shutdown_started("lifespan_shutdown")
            app.state.heartbeat_stop.set()
            app.state.monitor_alert_stop.set()
            app.state.mirror_stop.set()
            app.state.observability_retention_stop.set()
            app.state.event_loop_stop.set()
            await supervisor.shutdown()
            backend_shutdown_completed("lifespan_shutdown")
            engine.dispose()

    app = FastAPI(title="Codex Reset Radar", version="0.1.0", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.engine = engine
    app.state.alert_manager = AlertManager(settings)
    app.state.tweet_count = initial_tweet_count
    app.state.ready = False
    app.state.task_supervisor = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://127.0.0.1", "chrome-extension://", "edge-extension://"],
        allow_origin_regex=r"(chrome-extension|edge-extension)://.*",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def observability_http_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or new_id("req")
        trace_id = request.headers.get("x-trace-id") or None
        started = utc_now()
        with observability_context(trace_id=trace_id, request_id=request_id):
            append_event(
                "backend",
                "HTTP_REQUEST_STARTED",
                component="backend",
                trace_id=trace_id,
                request_id=request_id,
                metadata={
                    "method": request.method,
                    "route": request.url.path,
                    "client": request.client.host if request.client else None,
                },
                method=request.method,
                route=request.url.path,
                client=request.client.host if request.client else None,
            )
            try:
                response = await call_next(request)
                finished = utc_now()
                duration_ms = round((finished - started).total_seconds() * 1000, 3)
                route = getattr(request.scope.get("route"), "path", request.url.path)
                append_event(
                    "backend",
                    "HTTP_REQUEST_COMPLETED",
                    component="backend",
                    trace_id=trace_id,
                    request_id=request_id,
                    duration_ms=duration_ms,
                    result="success" if response.status_code < 400 else "error",
                    metadata={"method": request.method, "route": route, "status": response.status_code},
                    method=request.method,
                    route=route,
                    status=response.status_code,
                )
                if duration_ms > 1000:
                    append_event(
                        "backend",
                        "SLOW_HTTP_REQUEST",
                        level="WARNING",
                        component="backend",
                        trace_id=trace_id,
                        request_id=request_id,
                        duration_ms=duration_ms,
                        result="slow",
                        metadata={"method": request.method, "route": route, "status": response.status_code},
                        method=request.method,
                        route=route,
                        status=response.status_code,
                    )
                response.headers["X-Request-ID"] = request_id
                return response
            except Exception as exc:
                finished = utc_now()
                duration_ms = round((finished - started).total_seconds() * 1000, 3)
                append_event(
                    "backend",
                    "HTTP_REQUEST_FAILED",
                    level="ERROR",
                    component="backend",
                    trace_id=trace_id,
                    request_id=request_id,
                    duration_ms=duration_ms,
                    result="failed",
                    error_type=type(exc).__name__,
                    metadata={"method": request.method, "route": request.url.path, "error": redact_secret(exc)},
                    method=request.method,
                    route=request.url.path,
                    error=redact_secret(exc),
                )
                raise

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        # Keep this probe independent from SQLite and all observability files.
        return {
            "status": "ok",
            "ready": bool(getattr(request.app.state, "ready", False)),
            "service": "codex-reset-radar",
            "tweets": getattr(request.app.state, "tweet_count", None),
            "time": utc_iso(),
            "backend_instance_id": BACKEND_INSTANCE_ID,
        }

    @app.post("/api/ingest/tweets")
    def ingest_tweets(payload: TweetBatch, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        session = request.app.state.session_factory()
        ingest_trace_id = request.headers.get("x-trace-id") or new_id("tweet-ingest")
        try:
            created, deduplicated = ingest_batch(session, payload.tweets, trace_id=ingest_trace_id)
            if request.app.state.tweet_count is not None:
                request.app.state.tweet_count += created
            append_event(
                "backend",
                "TWEETS_INGESTED",
                component="ingestion",
                trace_id=ingest_trace_id,
                result="success",
                metadata={
                    "tweet_ids": [tweet.tweet_id for tweet in payload.tweets[:100]],
                    "created": created,
                    "deduplicated": deduplicated,
                },
                tweet_ids=[tweet.tweet_id for tweet in payload.tweets[:100]],
                created=created,
                deduplicated=deduplicated,
            )
            background_tasks.add_task(
                classify_tweet_ids,
                request.app.state.session_factory,
                [tweet.tweet_id for tweet in payload.tweets],
                mirror_event=request.app.state.mirror_event,
            )
            if created:
                request.app.state.mirror_event.set()
            return {"ok": True, "created": created, "deduplicated": deduplicated, "received": len(payload.tweets)}
        except Exception as exc:
            session.rollback()
            append_event(
                "backend",
                "DB_OPERATION_FAILED",
                level="ERROR",
                component="ingestion",
                trace_id=ingest_trace_id,
                error_type=type(exc).__name__,
                metadata={"operation": "tweet_ingestion", "table": "tweets/tweet_sources", "error": redact_secret(exc)},
                operation="tweet_ingestion",
                table="tweets/tweet_sources",
                error=redact_secret(exc),
            )
            logger.exception("Tweet ingestion failed")
            raise
        finally:
            session.close()

    @app.post("/api/heartbeat")
    def heartbeat(payload: HeartbeatPayload, request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            payload.request_id = payload.request_id or current_request_id()
            payload.trace_id = payload.trace_id or current_trace_id()
            append_event(
                "backend",
                "HEARTBEAT_BACKEND_RECEIVED",
                component="backend",
                instance_id=payload.instance_id or (BACKEND_INSTANCE_ID if payload.component == "backend" else None),
                trace_id=payload.trace_id,
                request_id=payload.request_id,
                sequence=payload.sequence,
                metadata={
                    "component": payload.component,
                    "backend_instance_id": BACKEND_INSTANCE_ID,
                    "client_observed_at": utc_iso(payload.observed_at) if payload.observed_at else None,
                    "state": payload.state,
                },
                state=payload.state,
                backend_instance_id=BACKEND_INSTANCE_ID,
            )
            previous = session.get(MonitorHealth, payload.component)
            previous_state = previous.state if previous else None
            health_record = record_heartbeat(session, payload)
            if previous_state != payload.state:
                request.app.state.mirror_event.set()
            return {
                "ok": True,
                "component": health_record.component,
                "state": health_record.state,
                "last_heartbeat": serialize_datetime(health_record.last_heartbeat),
                "backend_instance_id": BACKEND_INSTANCE_ID,
                "trace_id": payload.trace_id,
                "request_id": payload.request_id,
            }
        finally:
            session.close()

    @app.post("/api/diagnostics")
    def diagnostics_event(payload: DiagnosticPayload, request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            payload.request_id = payload.request_id or current_request_id()
            payload.trace_id = payload.trace_id or current_trace_id()
            event = record_diagnostic(session, payload)
            return {
                "ok": True,
                "id": event.id,
                "component": event.component,
                "event": event.event,
                "observed_at": serialize_datetime(event.observed_at),
            }
        finally:
            session.close()

    @app.post("/api/diagnostics/batch")
    def diagnostics_batch(payload: DiagnosticBatchPayload, request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        db_started = utc_now()
        try:
            events = []
            for item in payload.events:
                item.request_id = item.request_id or current_request_id()
                item.trace_id = item.trace_id or current_trace_id()
                events.append(record_diagnostic(session, item, commit=False))
            session.commit()
            duration_ms = round((utc_now() - db_started).total_seconds() * 1000, 3)
            if duration_ms > 500:
                append_event(
                    "backend",
                    "DB_SLOW_OPERATION",
                    level="WARNING",
                    component="diagnostics",
                    duration_ms=duration_ms,
                    result="slow",
                    metadata={
                        "operation": "diagnostic_batch_write",
                        "table": "monitor_diagnostic_events",
                        "count": len(events),
                    },
                    operation="diagnostic_batch_write",
                    table="monitor_diagnostic_events",
                    count=len(events),
                )
            return {"ok": True, "accepted": len(events), "ids": [event.id for event in events]}
        except Exception as exc:
            session.rollback()
            event_name = "SQLITE_LOCK_DETECTED" if is_sqlite_lock_error(exc) else "DB_OPERATION_FAILED"
            error_text = redact_secret(exc)
            append_event(
                "backend",
                event_name,
                level="ERROR",
                component="backend",
                error_type=type(exc).__name__,
                duration_ms=round((utc_now() - db_started).total_seconds() * 1000, 3),
                result="failed",
                metadata={
                    "operation": "diagnostic_batch_write",
                    "table": "monitor_diagnostic_events",
                    "error": error_text,
                    "count": len(payload.events),
                    "suspected_contention": "reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
                },
                operation="diagnostic_batch_write",
                table="monitor_diagnostic_events",
                error=error_text,
                count=len(payload.events),
                suspected_contention="reader_or_writer_contention" if event_name == "SQLITE_LOCK_DETECTED" else None,
            )
            raise
        finally:
            session.close()

    @app.get("/api/health")
    def health_detail(request: Request) -> list[dict[str, Any]]:
        session = request.app.state.session_factory()
        try:
            now = utc_now()
            records = session.scalars(select(MonitorHealth).order_by(MonitorHealth.component)).all()
            result = []
            for record in records:
                age_seconds = max(0, (now - as_utc(record.last_heartbeat)).total_seconds())
                derived_state = derived_monitor_state(record, now)
                result.append(
                    {
                        "component": record.component,
                        "state": derived_state,
                        "reported_state": record.state,
                        "last_heartbeat": serialize_datetime(record.last_heartbeat),
                        "last_tweet_seen": serialize_datetime(record.last_tweet_seen),
                        "last_error": record.last_error,
                        "metadata": _parse_metadata(record.metadata_json),
                        "age_seconds": round(age_seconds),
                    }
                )
            return result
        finally:
            session.close()

    @app.get("/api/diagnostics")
    def diagnostic_events(
        request: Request,
        component: str | None = None,
        event: str | None = None,
        limit: int = 100,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, MAX_OBSERVABILITY_LIMIT))
        since_at = _observability_since(since)
        session = request.app.state.session_factory()
        try:
            query = (
                select(MonitorDiagnosticEvent)
                .where(MonitorDiagnosticEvent.created_at >= since_at)
                .order_by(MonitorDiagnosticEvent.id.desc())
                .limit(limit)
            )
            if component:
                query = query.where(MonitorDiagnosticEvent.component == component)
            if event:
                query = query.where(MonitorDiagnosticEvent.event == event)
            rows = session.scalars(query).all()
            return [
                {
                    "id": row.id,
                    "component": row.component,
                    "event": row.event,
                    "observed_at": serialize_datetime(row.observed_at),
                    "created_at": serialize_datetime(row.created_at),
                    "details": _parse_metadata(row.details_json),
                }
                for row in rows
            ]
        finally:
            session.close()

    @app.get("/api/tweets")
    def tweets(request: Request, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        session = request.app.state.session_factory()
        try:
            rows = session.scalars(select(Tweet).order_by(Tweet.discovered_at.desc()).limit(limit)).all()
            result = []
            for tweet in rows:
                sources = session.scalars(select(TweetSource.source).where(TweetSource.tweet_id == tweet.tweet_id)).all()
                result.append(
                    {
                        "tweet_id": tweet.tweet_id,
                        "author": tweet.author,
                        "text": tweet.text,
                        "translation_zh": tweet.translated_zh,
                        "translation_model": tweet.translation_model,
                        "translation_version": tweet.translation_version,
                        "translated_at": serialize_datetime(tweet.translated_at),
                        "created_at": serialize_datetime(tweet.created_at),
                        "url": tweet.url,
                        "is_reply": tweet.is_reply,
                        "reply_to": tweet.reply_to,
                        "discovered_at": serialize_datetime(tweet.discovered_at),
                        "sources": list(sources),
                    }
                )
            return result
        finally:
            session.close()

    @app.get("/api/tweets/{tweet_id}/classification")
    def tweet_classification(tweet_id: str, request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            if session.get(Tweet, tweet_id) is None:
                raise HTTPException(status_code=404, detail="Tweet not found")
            rows = session.scalars(
                select(Classification)
                .where(Classification.tweet_id == tweet_id)
                .order_by(Classification.created_at.asc(), Classification.id.asc())
            ).all()
            return {
                "tweet_id": tweet_id,
                "classifications": [
                    {
                        "id": row.id,
                        "classifier_type": row.classifier_type,
                        "category": row.category,
                        "confidence": row.confidence,
                        "urgency": row.urgency,
                        "explicitness": row.explicitness,
                        "reason": row.reason,
                        "model_name": row.model_name,
                        "prompt_version": row.prompt_version,
                        "classification_pending": row.classification_pending,
                        "classification_conflict": row.classification_conflict,
                        "created_at": serialize_datetime(row.created_at),
                    }
                    for row in rows
                ],
            }
        finally:
            session.close()

    @app.post("/api/tweets/{tweet_id}/reclassify")
    async def reclassify_tweet(tweet_id: str, request: Request, force: bool = True) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            result = await classify_tweet(tweet_id=tweet_id, session=session, force=force)
            return result
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            session.rollback()
            logger.exception("Manual reclassification failed tweet_id=%s", tweet_id)
            raise HTTPException(status_code=500, detail="Classification failed") from exc
        finally:
            session.close()

    @app.post("/api/classify/backfill")
    async def classify_backfill(request: Request, limit: int = 500, force: bool = False) -> dict[str, int]:
        limit = max(1, min(limit, 5000))
        session = request.app.state.session_factory()
        try:
            tweet_ids = session.scalars(select(Tweet.tweet_id).order_by(Tweet.discovered_at.asc()).limit(limit)).all()
        finally:
            session.close()
        return await classify_tweet_ids(
            request.app.state.session_factory,
            list(tweet_ids),
            force=force,
            mirror_event=request.app.state.mirror_event,
        )

    @app.post("/api/translate/backfill")
    async def translate_backfill(
        request: Request,
        limit: int = 20,
        force: bool = False,
    ) -> dict[str, int]:
        """Translate the recent Tweet window plus every high-value reset signal."""

        limit = max(1, min(limit, 500))
        session = request.app.state.session_factory()
        try:
            recent_ids = session.scalars(
                select(Tweet.tweet_id).order_by(Tweet.created_at.desc(), Tweet.discovered_at.desc()).limit(limit)
            ).all()
            signal_ids = session.scalars(
                select(Classification.tweet_id)
                .where(
                    Classification.classifier_type == "final",
                    Classification.category.in_(
                        [
                            "reset_hint",
                            "reset_announcement",
                            "reset_in_progress",
                            "reset_confirmed",
                            "reset_denial",
                            "quota_information",
                        ]
                    ),
                )
                .order_by(Classification.created_at.desc(), Classification.id.desc())
            ).all()
        finally:
            session.close()
        result = await translate_tweet_ids(
            request.app.state.session_factory,
            list(dict.fromkeys([*recent_ids, *signal_ids])),
            force=force,
        )
        if result["translated"]:
            request.app.state.mirror_event.set()
        return result

    @app.get("/api/radar")
    def radar(request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            decision = update_radar(session)
            request.app.state.alert_manager.handle_radar_transition(session, decision)
            session.commit()
            if decision.changed:
                request.app.state.mirror_event.set()
            record = session.get(RadarState, 1)
            return {
                "state": record.state,
                "confidence": record.confidence,
                "urgency": record.urgency,
                "trigger_tweet_id": record.trigger_tweet_id,
                "updated_at": serialize_datetime(record.updated_at),
                "expires_at": serialize_datetime(record.expires_at),
                "reason": record.reason,
            }
        finally:
            session.close()

    @app.get("/api/forecast")
    def forecast(request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            return _forecast_payload(session)
        finally:
            session.close()

    @app.get("/api/alerts")
    def alerts(request: Request, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        session = request.app.state.session_factory()
        try:
            rows = session.scalars(select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit)).all()
            return [
                {
                    "id": row.id,
                    "alert_type": row.alert_type,
                    "tweet_id": row.tweet_id,
                    "radar_state": row.radar_state,
                    "channel": row.channel,
                    "status": row.status,
                    "created_at": serialize_datetime(row.created_at),
                    "sent_at": serialize_datetime(row.sent_at),
                    "error": row.error,
                }
                for row in rows
            ]
        finally:
            session.close()

    @app.post("/api/alerts/test")
    def test_alert(request: Request, channel: str = "wxpusher") -> dict[str, Any]:
        client_host = request.client.host if request.client else None
        if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise HTTPException(status_code=403, detail="Local test endpoint only")
        session = request.app.state.session_factory()
        try:
            try:
                row = request.app.state.alert_manager.send_test_alert(session, channel)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            session.commit()
            if row is None:
                raise HTTPException(status_code=503, detail="No notification channel configured")
            return {
                "ok": row.status in {"sent", "dry_run"},
                "alert_id": row.id,
                "channel": row.channel,
                "status": row.status,
                "error": row.error,
                "delivery": request.app.state.alert_manager.last_delivery_details or {},
            }
        finally:
            session.close()

    @app.get("/api/observability/summary")
    def observability_summary(request: Request, since: str | None = None) -> dict[str, Any]:
        _require_local_observability(request)
        since_at = _observability_since(since)
        session = request.app.state.session_factory()
        try:
            now = utc_now()
            components: list[dict[str, Any]] = []
            for record in session.scalars(select(MonitorHealth).order_by(MonitorHealth.component)).all():
                age_seconds = max(0.0, (now - as_utc(record.last_heartbeat)).total_seconds())
                metadata = _parse_metadata(record.metadata_json)
                components.append(
                    {
                        "component": record.component,
                        "state": derived_monitor_state(record, now),
                        "reported_state": record.state,
                        "last_heartbeat": serialize_datetime(record.last_heartbeat),
                        "age_seconds": round(age_seconds, 3),
                        "last_error": record.last_error,
                        "instance_id": metadata.get("content_instance_id") or metadata.get("instance_id") or metadata.get("service_worker_instance_id"),
                        "backend_instance_id": metadata.get("backend_instance_id") or BACKEND_INSTANCE_ID,
                        "sequence": metadata.get("sequence"),
                    }
                )
        finally:
            session.close()
        # Keep the database transaction closed before touching JSONL. Each
        # read is a bounded tail, so summary remains independent of storage
        # size and cannot hold a SQLite read transaction during file I/O.
        mirror_events = read_events(
            "mirror",
            20,
            event_filter={"PUBLIC_MIRROR_SYNC_SUCCESS", "PUBLIC_MIRROR_SYNC_FAILED"},
            since=since_at,
        )
        notification_events = read_events(
            "notifications",
            20,
            event_filter={"WXPUSHER_REQUEST_SUCCESS", "WXPUSHER_REQUEST_FAILED"},
            since=since_at,
        )
        backend_lag_events = read_events("backend", 20, event_filter="EVENT_LOOP_LAG_DETECTED", since=since_at)
        return {
            "backend": {
                "instance_id": BACKEND_INSTANCE_ID,
                "pid": os.getpid(),
                "started_at": utc_iso(PROCESS_STARTED_AT),
                "uptime_seconds": round((now - PROCESS_STARTED_AT).total_seconds(), 3),
                "ready": bool(getattr(request.app.state, "ready", False)),
                "runtime_log": str(RUNTIME_LOG_PATH),
                "tasks": request.app.state.task_supervisor.snapshot() if request.app.state.task_supervisor else [],
                "event_loop": backend_lag_events[-1] if backend_lag_events else None,
            },
            "components": components,
            "mirror": next(reversed(mirror_events), None),
            "notifications": next(reversed(notification_events), None),
        }

    @app.get("/api/observability/trace/{trace_id}")
    def observability_trace(
        trace_id: str,
        request: Request,
        limit: int = 200,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        _require_local_observability(request)
        limit = max(1, min(limit, MAX_OBSERVABILITY_LIMIT))
        since_at = _observability_since(since)
        # Read the file-backed side before opening SQLite. A known trace is
        # still bounded to a recent window and to a small tail per shard.
        records: list[dict[str, Any]] = [
            _observability_event_json(event)
            for event in read_all_events(
                min(max(limit * 2, 20), MAX_OBSERVABILITY_LIMIT),
                trace_id=trace_id,
                since=since_at,
            )
        ]
        session = request.app.state.session_factory()
        try:
            for row in session.scalars(
                select(HeartbeatHistory)
                .where(
                    HeartbeatHistory.trace_id == trace_id,
                    HeartbeatHistory.backend_received_at >= since_at,
                )
                .order_by(HeartbeatHistory.id.desc())
                .limit(limit)
            ).all():
                records.append(
                    {
                        "timestamp": serialize_datetime(row.backend_received_at),
                        "event": "HEARTBEAT_DB_COMMITTED",
                        "level": "INFO",
                        "component": row.component,
                        "instance_id": row.instance_id,
                        "trace_id": row.trace_id,
                        "request_id": row.request_id,
                        "sequence": row.sequence,
                        "result": "success",
                        "client_observed_at": serialize_datetime(row.client_observed_at),
                        "backend_received_at": serialize_datetime(row.backend_received_at),
                        "db_committed_at": serialize_datetime(row.db_committed_at),
                    }
                )
            diagnostic_rows = session.scalars(
                select(MonitorDiagnosticEvent)
                .where(
                    MonitorDiagnosticEvent.created_at >= since_at,
                    MonitorDiagnosticEvent.details_json.like(f"%{trace_id}%"),
                )
                .order_by(MonitorDiagnosticEvent.id.desc())
                .limit(limit)
            ).all()
            for row in diagnostic_rows:
                details = _parse_metadata(row.details_json)
                if details.get("trace_id") == trace_id:
                    records.append(
                        {
                            "timestamp": serialize_datetime(row.observed_at),
                            "event": row.event,
                            "level": "INFO",
                            "component": row.component,
                            "trace_id": trace_id,
                            "details": details,
                        }
                    )
            records.sort(key=lambda item: str(item.get("timestamp") or ""))
            return records[-limit:]
        finally:
            session.close()

    @app.get("/api/observability/component/{component}")
    def observability_component(
        component: str,
        request: Request,
        limit: int = 50,
        since: str | None = None,
    ) -> dict[str, Any]:
        _require_local_observability(request)
        limit = max(1, min(limit, MAX_OBSERVABILITY_LIMIT))
        since_at = _observability_since(since)
        aliases = {"profile": "profile_monitor", "replies": "replies_monitor", "search": "search_backfill"}
        component_name = aliases.get(component, component)
        session = request.app.state.session_factory()
        try:
            health = session.get(MonitorHealth, component_name)
            transitions = session.scalars(
                select(HealthStateHistory)
                .where(
                    HealthStateHistory.component == component_name,
                    HealthStateHistory.changed_at >= since_at,
                )
                .order_by(HealthStateHistory.id.desc())
                .limit(limit)
            ).all()
            heartbeats = session.scalars(
                select(HeartbeatHistory)
                .where(
                    HeartbeatHistory.component == component_name,
                    HeartbeatHistory.backend_received_at >= since_at,
                )
                .order_by(HeartbeatHistory.id.desc())
                .limit(limit)
            ).all()
            diagnostics = session.scalars(
                select(MonitorDiagnosticEvent)
                .where(
                    MonitorDiagnosticEvent.component == component_name,
                    MonitorDiagnosticEvent.created_at >= since_at,
                )
                .order_by(MonitorDiagnosticEvent.id.desc())
                .limit(limit)
            ).all()
            return {
                "component": component_name,
                "current": {
                    "state": derived_monitor_state(health) if health else "unknown",
                    "reported_state": health.state if health else None,
                    "last_heartbeat": serialize_datetime(health.last_heartbeat) if health else None,
                    "last_error": health.last_error if health else None,
                    "metadata": _parse_metadata(health.metadata_json) if health else {},
                },
                "transitions": [
                    {
                        "previous_state": row.previous_state,
                        "new_state": row.new_state,
                        "reason": row.reason,
                        "changed_at": serialize_datetime(row.changed_at),
                        "heartbeat_age_seconds": row.heartbeat_age_seconds,
                    }
                    for row in reversed(transitions)
                ],
                "heartbeats": [
                    {
                        "sequence": row.sequence,
                        "instance_id": row.instance_id,
                        "trace_id": row.trace_id,
                        "request_id": row.request_id,
                        "client_observed_at": serialize_datetime(row.client_observed_at),
                        "backend_received_at": serialize_datetime(row.backend_received_at),
                        "db_committed_at": serialize_datetime(row.db_committed_at),
                        "state": row.state,
                        "error": row.error,
                    }
                    for row in reversed(heartbeats)
                ],
                "diagnostics": [
                    {
                        "event": row.event,
                        "observed_at": serialize_datetime(row.observed_at),
                        "created_at": serialize_datetime(row.created_at),
                        "details": _parse_metadata(row.details_json),
                    }
                    for row in reversed(diagnostics)
                ],
            }
        finally:
            session.close()

    @app.get("/api/observability/errors")
    def observability_errors(
        request: Request,
        limit: int = 100,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        _require_local_observability(request)
        limit = max(1, min(limit, MAX_OBSERVABILITY_LIMIT))
        since_at = _observability_since(since)
        records = [
            event for event in read_all_events(
                min(max(limit * 2, 20), MAX_OBSERVABILITY_LIMIT),
                since=since_at,
            )
            if event.get("level") in {"ERROR", "CRITICAL"}
            or "FAILED" in str(event.get("event"))
            or "LAG_DETECTED" in str(event.get("event"))
        ]
        return records[-limit:]

    return app


async def _backend_heartbeat_loop(session_factory, stop_event: asyncio.Event) -> None:
    interval_seconds = 60
    loop = asyncio.get_running_loop()
    next_deadline = loop.time() + interval_seconds
    previous_tick_at: float | None = None
    sequence = 0
    append_event(
        "backend",
        "BACKEND_HEARTBEAT_LOOP_STARTED",
        component="backend",
        instance_id=BACKEND_INSTANCE_ID,
        metadata={"expected_interval_ms": interval_seconds * 1000},
        expected_interval_ms=interval_seconds * 1000,
    )
    while not stop_event.is_set():
        await asyncio.sleep(max(0.0, next_deadline - loop.time()))
        if stop_event.is_set():
            return
        ticked_at = loop.time()
        actual_interval_ms = round((ticked_at - previous_tick_at) * 1000, 3) if previous_tick_at is not None else None
        schedule_drift_ms = round((ticked_at - next_deadline) * 1000, 3)
        previous_tick_at = ticked_at
        next_deadline += interval_seconds
        sequence += 1
        tick_at = utc_now()
        trace_id = f"hb-backend-{BACKEND_INSTANCE_ID}-{sequence}"
        append_event(
            "backend",
            "BACKEND_HEARTBEAT_TICK",
            component="backend",
            instance_id=BACKEND_INSTANCE_ID,
            trace_id=trace_id,
            sequence=sequence,
            metadata={
                "expected_interval_ms": interval_seconds * 1000,
                "actual_interval_ms": actual_interval_ms,
                "schedule_drift_ms": schedule_drift_ms,
                "event_loop_lag_ms": max(0.0, schedule_drift_ms),
            },
            expected_interval_ms=interval_seconds * 1000,
            actual_interval_ms=actual_interval_ms,
            schedule_drift_ms=schedule_drift_ms,
            event_loop_lag_ms=max(0.0, schedule_drift_ms),
        )
        db_started = utc_now()
        append_event(
            "backend",
            "BACKEND_HEARTBEAT_DB_WRITE_STARTED",
            component="backend",
            instance_id=BACKEND_INSTANCE_ID,
            trace_id=trace_id,
            sequence=sequence,
            metadata={"component": "backend", "table": "monitor_health/heartbeat_history"},
            operation="heartbeat_write",
            table="monitor_health/heartbeat_history",
        )
        try:
            with session_factory() as session:
                record_heartbeat(
                    session,
                    HeartbeatPayload(
                        component="backend",
                        instance_id=BACKEND_INSTANCE_ID,
                        sequence=sequence,
                        trace_id=trace_id,
                        observed_at=tick_at,
                        state="healthy",
                    ),
                )
            db_duration_ms = round((utc_now() - db_started).total_seconds() * 1000, 3)
            append_event(
                "backend",
                "BACKEND_HEARTBEAT_DB_WRITE_SUCCESS",
                component="backend",
                instance_id=BACKEND_INSTANCE_ID,
                trace_id=trace_id,
                sequence=sequence,
                duration_ms=db_duration_ms,
                result="success",
                metadata={"component": "backend", "table": "monitor_health/heartbeat_history"},
                operation="heartbeat_write",
                table="monitor_health/heartbeat_history",
            )
        except Exception as exc:
            error_text = redact_secret(exc)
            error_type = type(exc).__name__
            event = "SQLITE_LOCK_DETECTED" if is_sqlite_lock_error(exc) else "BACKEND_HEARTBEAT_DB_WRITE_FAILED"
            append_event(
                "backend",
                event,
                level="ERROR",
                component="backend",
                instance_id=BACKEND_INSTANCE_ID,
                trace_id=trace_id,
                sequence=sequence,
                duration_ms=round((utc_now() - db_started).total_seconds() * 1000, 3),
                result="failed",
                error_type=error_type,
                metadata={
                    "component": "backend",
                    "table": "monitor_health/heartbeat_history",
                    "error": error_text,
                    "suspected_contention": "reader_or_writer_contention" if event == "SQLITE_LOCK_DETECTED" else None,
                },
                operation="heartbeat_write",
                table="monitor_health/heartbeat_history",
                error=error_text,
                suspected_contention="reader_or_writer_contention" if event == "SQLITE_LOCK_DETECTED" else None,
            )
            logger.exception("BACKEND_HEARTBEAT_DB_WRITE_FAILED sequence=%s", sequence)


async def _monitor_alert_loop(
    session_factory,
    stop_event: asyncio.Event,
    alert_manager: AlertManager,
) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(60)
        if stop_event.is_set():
            return
        try:
            await asyncio.to_thread(_evaluate_monitor_alerts, session_factory, alert_manager)
        except Exception as exc:
            append_event(
                "backend",
                "HEALTH_EVALUATOR_CYCLE_FAILED",
                level="ERROR",
                component="health_evaluator",
                error_type=type(exc).__name__,
                metadata={"error": redact_secret(exc)},
                error=redact_secret(exc),
            )
            logger.exception("Monitor alert evaluation failed")


def _record_health_state_transitions(session, now: datetime | None = None) -> None:
    current_time = now or utc_now()
    components = ("backend", "profile_monitor", "replies_monitor", "search_backfill")
    records = {record.component: record for record in session.scalars(select(MonitorHealth)).all()}
    for component in components:
        record = records.get(component)
        current_state = derived_monitor_state(record, current_time)
        previous_history = session.scalar(
            select(HealthStateHistory)
            .where(HealthStateHistory.component == component)
            .order_by(HealthStateHistory.id.desc())
            .limit(1)
        )
        previous_state = previous_history.new_state if previous_history else None
        if previous_history is None and current_state == "unknown":
            continue
        if previous_state == current_state:
            continue
        latest_heartbeat = session.scalar(
            select(HeartbeatHistory)
            .where(HeartbeatHistory.component == component)
            .order_by(HeartbeatHistory.id.desc())
            .limit(1)
        )
        recent_backend_events = read_events("backend", 1000)

        def latest_event(*event_names: str) -> dict[str, Any] | None:
            for event in reversed(recent_backend_events):
                if event.get("event") not in event_names:
                    continue
                event_component = event.get("component")
                metadata_component = event.get("metadata", {}).get("component") if isinstance(event.get("metadata"), dict) else None
                if event_component == component or metadata_component == component or component == "backend":
                    return event
            return None

        recent_lag = latest_event("EVENT_LOOP_LAG_DETECTED")
        recent_db_error = latest_event(
            "DB_OPERATION_FAILED",
            "BACKEND_HEARTBEAT_DB_WRITE_FAILED",
            "SQLITE_LOCK_DETECTED",
        )
        recent_http_error = latest_event("HTTP_REQUEST_FAILED")
        trace_id = latest_heartbeat.trace_id if latest_heartbeat else None
        age_seconds = (
            max(0.0, (current_time - as_utc(record.last_heartbeat)).total_seconds())
            if record and record.last_heartbeat
            else None
        )
        reason = (
            f"reported_state={record.state}; heartbeat_age_seconds={round(age_seconds, 3) if age_seconds is not None else 'unknown'}"
            if record
            else "no heartbeat record"
        )
        transition = HealthStateHistory(
            component=component,
            previous_state=previous_state,
            new_state=current_state,
            reason=reason,
            last_heartbeat_at=record.last_heartbeat if record else None,
            heartbeat_age_seconds=age_seconds,
            instance_id=latest_heartbeat.instance_id if latest_heartbeat else (BACKEND_INSTANCE_ID if component == "backend" else None),
            trace_id=trace_id,
            changed_at=current_time,
        )
        session.add(transition)
        append_event(
            "backend",
            "HEALTH_STATE_CHANGED",
            component=component,
            instance_id=transition.instance_id,
            trace_id=trace_id,
            result="transition",
            metadata={
                "previous_state": previous_state,
                "new_state": current_state,
                "reason": reason,
                "last_heartbeat_at": utc_iso(record.last_heartbeat) if record else None,
                "heartbeat_age_seconds": age_seconds,
                "trace_id": trace_id,
            },
            previous_state=previous_state,
            new_state=current_state,
            reason=reason,
            last_heartbeat_at=utc_iso(record.last_heartbeat) if record else None,
            heartbeat_age_seconds=age_seconds,
        )
        if current_state == "offline":
            append_event(
                "backend",
                "FAILURE_BREADCRUMB",
                level="WARNING",
                component=component,
                instance_id=transition.instance_id,
                trace_id=trace_id,
                result="offline",
                metadata={
                    "component": component,
                    "last_success": utc_iso(record.last_heartbeat) if record else None,
                    "last_heartbeat": utc_iso(record.last_heartbeat) if record else None,
                    "last_error": redact_secret(record.last_error) if record and record.last_error else None,
                    "instance_id": transition.instance_id,
                    "sequence": latest_heartbeat.sequence if latest_heartbeat else None,
                    "recent_event_loop_lag": recent_lag,
                    "recent_db_error": recent_db_error,
                    "recent_http_error": recent_http_error,
                },
                last_heartbeat_at=utc_iso(record.last_heartbeat) if record else None,
                last_error=redact_secret(record.last_error) if record and record.last_error else None,
                recent_event_loop_lag=recent_lag,
                recent_db_error=recent_db_error,
                recent_http_error=recent_http_error,
            )
        if previous_state == "offline" and current_state == "healthy":
            outage_started_at = previous_history.changed_at if previous_history else current_time
            duration_ms = round((current_time - outage_started_at).total_seconds() * 1000, 3)
            append_event(
                "backend",
                "COMPONENT_RECOVERED",
                component=component,
                instance_id=transition.instance_id,
                trace_id=trace_id,
                duration_ms=duration_ms,
                result="recovered",
                metadata={
                    "component": component,
                    "outage_started_at": utc_iso(outage_started_at),
                    "recovered_at": utc_iso(current_time),
                    "duration_ms": duration_ms,
                    "recovery": "automatic_health_evaluator",
                },
                outage_started_at=utc_iso(outage_started_at),
                recovered_at=utc_iso(current_time),
                recovery="automatic_health_evaluator",
            )


async def _public_mirror_loop(settings, stop_event: asyncio.Event, mirror_event: asyncio.Event) -> None:
    """Run scheduled and event-triggered mirror cycles without blocking the API."""
    interval = max(60, settings.github_mirror_interval_seconds)
    loop = asyncio.get_running_loop()
    next_scheduled_at = loop.time() + interval
    last_cycle_started_at: datetime | None = None
    last_scheduled_cycle_started_at: datetime | None = None
    last_success_at: datetime | None = None
    while not stop_event.is_set():
        trigger = "scheduled"
        timeout = max(0.0, next_scheduled_at - loop.time())
        try:
            await asyncio.wait_for(mirror_event.wait(), timeout=timeout)
            trigger = "event"
        except asyncio.TimeoutError:
            trigger = "scheduled"
        if stop_event.is_set():
            return
        if trigger == "scheduled":
            # Consume the deadline that woke this cycle before running the
            # sync. The post-cycle loop below should only report additional
            # windows missed while the export/push was in progress.
            next_scheduled_at += interval
        mirror_event.clear()
        cycle_started_at = utc_now()
        trace_id = new_id("mirror")
        cycle_interval = ((cycle_started_at - last_cycle_started_at).total_seconds() if last_cycle_started_at else None)
        scheduler_cycle_interval = (
            (cycle_started_at - last_scheduled_cycle_started_at).total_seconds()
            if trigger == "scheduled" and last_scheduled_cycle_started_at
            else None
        )
        previous_success_at = last_success_at
        logger.info(
            "PUBLIC_MIRROR_CYCLE_STARTED cycle_started_at=%s cycle_interval_seconds=%s "
            "scheduler_cycle_interval_seconds=%s "
            "configured_interval_seconds=%s previous_success_at=%s trigger=%s trace_id=%s result=started",
            _mirror_timestamp(cycle_started_at),
            f"{cycle_interval:.3f}" if cycle_interval is not None else "-",
            f"{scheduler_cycle_interval:.3f}" if scheduler_cycle_interval is not None else "-",
            interval,
            _mirror_timestamp(previous_success_at),
            trigger,
            trace_id,
        )
        _append_mirror_log(
            "PUBLIC_MIRROR_CYCLE_STARTED",
            source="scheduler",
            cycle_started_at=_mirror_timestamp(cycle_started_at),
            snapshot_generated_at="-",
            push_started_at="-",
            sync_finished_at="-",
            published_at="-",
            cycle_interval_seconds=round(cycle_interval, 3) if cycle_interval is not None else None,
            scheduler_cycle_interval_seconds=(
                round(scheduler_cycle_interval, 3) if scheduler_cycle_interval is not None else None
            ),
            configured_interval_seconds=interval,
            previous_success_at=_mirror_timestamp(previous_success_at),
            trigger=trigger,
            trace_id=trace_id,
            result="started",
        )
        sync_result = await asyncio.to_thread(
            _run_public_mirror_sync,
            settings,
            trigger=trigger,
            cycle_started_at=cycle_started_at,
            previous_success_at=previous_success_at,
            trace_id=trace_id,
        )
        if sync_result.status == "published":
            last_success_at = sync_result.sync_finished_at or sync_result.published_at or utc_now()
        last_cycle_started_at = cycle_started_at
        if trigger == "scheduled":
            last_scheduled_cycle_started_at = cycle_started_at

        if mirror_event.is_set():
            logger.info("PUBLIC_MIRROR_EVENT_DIRTY trigger=%s result=pending", trigger)

        # Event syncs must not move the next scheduled deadline. If a long
        # sync crossed one or more scheduled windows, record those windows and
        # advance the deadline without creating a burst of back-to-back runs.
        while next_scheduled_at <= loop.time():
            skipped_at = utc_now()
            logger.info(
                "PUBLIC_MIRROR_SYNC_SKIPPED cycle_started_at=%s sync_finished_at=%s duration_ms=%s "
                "previous_success_at=%s seconds_since_previous_success=%s trigger=scheduled "
                "result=skipped attempt=0 terminal=true reason=job_already_running",
                _mirror_timestamp(cycle_started_at),
                _mirror_timestamp(skipped_at),
                int(max(0.0, (skipped_at - cycle_started_at).total_seconds() * 1000)),
                _mirror_timestamp(previous_success_at),
                f"{(skipped_at - previous_success_at).total_seconds():.3f}" if previous_success_at else "-",
            )
            _append_mirror_log(
                "PUBLIC_MIRROR_SYNC_SKIPPED",
                source="scheduler",
                cycle_started_at=_mirror_timestamp(cycle_started_at),
                snapshot_generated_at="-",
                push_started_at="-",
                sync_finished_at=_mirror_timestamp(skipped_at),
                published_at="-",
                duration_ms=int(max(0.0, (skipped_at - cycle_started_at).total_seconds() * 1000)),
                previous_success_at=_mirror_timestamp(previous_success_at),
                seconds_since_previous_success=(
                    round((skipped_at - previous_success_at).total_seconds(), 3) if previous_success_at else "-"
                ),
                trigger="scheduled",
                trace_id=trace_id,
                attempt=0,
                terminal=True,
                result="skipped",
                reason="job_already_running",
            )
            next_scheduled_at += interval


def _run_public_mirror_sync(
    settings,
    *,
    trigger: str = "manual",
    cycle_started_at: datetime | None = None,
    previous_success_at: datetime | None = None,
    trace_id: str | None = None,
) -> MirrorSyncResult:
    cycle_started = cycle_started_at or utc_now()
    if not _MIRROR_JOB_LOCK.acquire(blocking=False):
        skipped_at = utc_now()
        _append_mirror_log(
            "PUBLIC_MIRROR_SYNC_SKIPPED",
            source="scheduler",
            cycle_started_at=_mirror_timestamp(cycle_started),
            snapshot_generated_at="-",
            push_started_at="-",
            sync_finished_at=_mirror_timestamp(skipped_at),
            published_at="-",
            duration_ms=int(max(0.0, (skipped_at - cycle_started).total_seconds() * 1000)),
            previous_success_at=_mirror_timestamp(previous_success_at),
            seconds_since_previous_success=(
                round((skipped_at - previous_success_at).total_seconds(), 3) if previous_success_at else "-"
            ),
            trigger=trigger,
            trace_id=trace_id,
            attempt=0,
            terminal=True,
            result="skipped",
            reason="job_already_running",
        )
        return MirrorSyncResult("skipped", sync_finished_at=skipped_at, reason="job_already_running")

    script = Path(__file__).resolve().parents[2] / "scripts" / "sync-github-data.ps1"
    powershell = shutil.which("pwsh") or shutil.which("powershell.exe") or "powershell.exe"
    command = [powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    if cycle_started_at:
        command.extend(["-Trigger", trigger, "-CycleStartedAt", _mirror_timestamp(cycle_started_at)])
    if previous_success_at:
        command.extend(["-PreviousSuccessAt", _mirror_timestamp(previous_success_at)])
    if trace_id:
        command.extend(["-TraceId", trace_id])
    command.extend(["-MaxAttempts", "4"])
    try:
        try:
            result = subprocess.run(
                command,
                cwd=script.parents[1],
                capture_output=True,
                text=True,
                timeout=max(900, settings.github_mirror_interval_seconds + 600),
                check=False,
            )
        except Exception as exc:
            sync_finished_at = utc_now()
            error_type = _classify_mirror_error(str(exc))
            reason = _redact_mirror_text(str(exc)[:500])
            _append_mirror_log(
                "PUBLIC_MIRROR_SYNC_FAILED",
                source="scheduler",
                cycle_started_at=_mirror_timestamp(cycle_started),
                snapshot_generated_at="-",
                push_started_at="-",
                sync_finished_at=_mirror_timestamp(sync_finished_at),
                published_at="-",
                duration_ms=int(max(0.0, (sync_finished_at - cycle_started).total_seconds() * 1000)),
                previous_success_at=_mirror_timestamp(previous_success_at),
                seconds_since_previous_success=(
                    round((sync_finished_at - previous_success_at).total_seconds(), 3) if previous_success_at else "-"
                ),
                trigger=trigger,
                trace_id=trace_id,
                attempt=4,
                terminal=True,
                result="failed",
                error_type=error_type,
                reason=reason,
            )
            return MirrorSyncResult("failed", sync_finished_at=sync_finished_at, error_type=error_type, reason=reason)

        # Keep stdout/stderr line boundaries intact: the script emits one
        # structured PUBLIC_MIRROR_* event per line. Redact each line inside
        # _log_mirror_script_events so separate events cannot be merged into a
        # single misleading record.
        output = result.stdout or ""
        error = result.stderr or ""
        events = _log_mirror_script_events(output)
        events.extend(_log_mirror_script_events(error))
        success_event = next((event for event in reversed(events) if event["event"] == "PUBLIC_MIRROR_SYNC_SUCCESS"), None)
        skipped_event = next((event for event in reversed(events) if event["event"] == "PUBLIC_MIRROR_SYNC_SKIPPED"), None)
        failed_event = next((event for event in reversed(events) if event["event"] == "PUBLIC_MIRROR_SYNC_FAILED"), None)

        if result.returncode != 0:
            if failed_event is None:
                finished = utc_now()
                reason = (error or output)[-500:] or f"sync script exited with code {result.returncode}"
                error_type = _classify_mirror_error(reason)
                _append_mirror_log(
                    "PUBLIC_MIRROR_SYNC_FAILED",
                    source="scheduler",
                    cycle_started_at=_mirror_timestamp(cycle_started),
                    snapshot_generated_at="-",
                    push_started_at="-",
                    sync_finished_at=_mirror_timestamp(finished),
                    published_at="-",
                    duration_ms=int(max(0.0, (finished - cycle_started).total_seconds() * 1000)),
                    previous_success_at=_mirror_timestamp(previous_success_at),
                    seconds_since_previous_success=(
                        round((finished - previous_success_at).total_seconds(), 3) if previous_success_at else "-"
                    ),
                    trigger=trigger,
                    trace_id=trace_id,
                    attempt=4,
                    terminal=True,
                    result="failed",
                    exit_code=result.returncode,
                    error_type=error_type,
                    reason=reason,
                )
                return MirrorSyncResult("failed", sync_finished_at=finished, error_type=error_type, reason=reason)
            failed_finished = _parse_mirror_datetime(failed_event.get("sync_finished_at")) or utc_now()
            return MirrorSyncResult(
                "failed",
                sync_finished_at=failed_finished,
                attempt=int(failed_event["attempt"]) if isinstance(failed_event.get("attempt"), (int, float)) else None,
                error_type=str(failed_event.get("error_type")) if failed_event.get("error_type") else None,
                reason=str(failed_event.get("reason")) if failed_event.get("reason") else None,
            )
        if success_event is not None:
            sync_finished = _parse_mirror_datetime(success_event.get("sync_finished_at")) or utc_now()
            published_at = _parse_mirror_datetime(success_event.get("published_at")) or sync_finished
            attempt_value = success_event.get("attempt", success_event.get("push_attempt"))
            return MirrorSyncResult(
                "published",
                sync_finished_at=sync_finished,
                published_at=published_at,
                attempt=int(attempt_value) if isinstance(attempt_value, (int, float)) else None,
            )
        if skipped_event is not None:
            skipped_finished = _parse_mirror_datetime(skipped_event.get("sync_finished_at")) or utc_now()
            return MirrorSyncResult("skipped", sync_finished_at=skipped_finished, reason=str(skipped_event.get("reason", "skipped")))

        finished = utc_now()
        reason = "Mirror script completed without a structured outcome."
        _append_mirror_log(
            "PUBLIC_MIRROR_SYNC_FAILED",
            source="scheduler",
            cycle_started_at=_mirror_timestamp(cycle_started),
            snapshot_generated_at="-",
            push_started_at="-",
            sync_finished_at=_mirror_timestamp(finished),
            published_at="-",
            duration_ms=int(max(0.0, (finished - cycle_started).total_seconds() * 1000)),
            previous_success_at=_mirror_timestamp(previous_success_at),
            seconds_since_previous_success=(
                round((finished - previous_success_at).total_seconds(), 3) if previous_success_at else "-"
            ),
            trigger=trigger,
            trace_id=trace_id,
            attempt=4,
            terminal=True,
            result="failed",
            error_type="unknown",
            reason=reason,
        )
        return MirrorSyncResult("failed", sync_finished_at=finished, error_type="unknown", reason=reason)
    finally:
        _MIRROR_JOB_LOCK.release()


def _evaluate_monitor_alerts(session_factory, alert_manager: AlertManager) -> None:
    with session_factory() as session:
        now = utc_now()
        _record_health_state_transitions(session, now=now)
        alert_manager.evaluate_monitor_health(session, now=now)
        session.commit()


def _run_observability_retention(session_factory) -> None:
    started = utc_now()
    deleted_rows = {
        "heartbeat_history": 0,
        "monitor_diagnostic_events": 0,
        "health_state_history": 0,
    }
    try:
        heartbeat_cutoff = started - timedelta(days=14)
        diagnostic_cutoff = started - timedelta(days=14)
        health_cutoff = started - timedelta(days=30)
        with session_factory() as session:
            result = session.execute(delete(HeartbeatHistory).where(HeartbeatHistory.backend_received_at < heartbeat_cutoff))
            deleted_rows["heartbeat_history"] = int(result.rowcount or 0)
            result = session.execute(delete(MonitorDiagnosticEvent).where(MonitorDiagnosticEvent.created_at < diagnostic_cutoff))
            deleted_rows["monitor_diagnostic_events"] = int(result.rowcount or 0)
            result = session.execute(delete(HealthStateHistory).where(HealthStateHistory.changed_at < health_cutoff))
            deleted_rows["health_state_history"] = int(result.rowcount or 0)
            session.commit()
        # Dated shards are retired by filename; do not parse the active
        # Backend stream during a retention run. Legacy compatibility logs
        # are small enough for streaming pruning and are kept separate from
        # the large archived backend JSONL.
        pruned_events = prune_event_shards(
            retention_days={"backend": 14, "mirror": 30, "notifications": 30},
            now=started,
        )
        pruned_events += prune_jsonl(MIRROR_CADENCE_LOG_PATH, max_age_days=30)
        pruned_events += prune_jsonl(NOTIFICATION_DIAGNOSTIC_LOG_PATH, max_age_days=30)
        pruned_events += prune_jsonl(NOTIFICATION_TEST_LOG_PATH, max_age_days=30)
        append_event(
            "backend",
            "OBSERVABILITY_RETENTION_COMPLETED",
            component="observability",
            result="success",
            duration_ms=round((utc_now() - started).total_seconds() * 1000, 3),
            metadata={
                "deleted_rows": deleted_rows,
                "pruned_event_rows": pruned_events,
                "heartbeat_retention_days": 14,
                "diagnostic_retention_days": 14,
                "health_state_retention_days": 30,
                "mirror_retention_days": 30,
                "notification_retention_days": 30,
            },
            deleted_rows=deleted_rows,
            pruned_event_rows=pruned_events,
        )
    except Exception as exc:
        append_event(
            "backend",
            "OBSERVABILITY_RETENTION_FAILED",
            level="ERROR",
            component="observability",
            result="failed",
            error_type=type(exc).__name__,
            duration_ms=round((utc_now() - started).total_seconds() * 1000, 3),
            metadata={"deleted_rows": deleted_rows, "error": redact_secret(exc)},
            error=redact_secret(exc),
        )
        logger.exception("OBSERVABILITY_RETENTION_FAILED")


async def _observability_retention_loop(session_factory, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=6 * 60 * 60)
        except asyncio.TimeoutError:
            if not stop_event.is_set():
                await asyncio.to_thread(_run_observability_retention, session_factory)


app = create_app()
