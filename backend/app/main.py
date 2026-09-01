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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.config import get_settings
from app.database import create_database
from app.ingestion import ingest_batch, record_diagnostic, record_heartbeat
from app.classifiers.service import classify_tweet, classify_tweet_ids, translate_tweet_ids
from app.intelligence.forecast import build_forecast, build_reset_history, derive_usage_advice
from app.intelligence.radar import update_radar
from app.models import Alert, Classification, MonitorDiagnosticEvent, MonitorHealth, RadarState, ResetEvent, Tweet, TweetSource
from app.notifications.alert_manager import AlertManager, derived_monitor_state
from app.schemas import DiagnosticPayload, HeartbeatPayload, TweetBatch


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("radar")

MIRROR_CADENCE_LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "mirror-cadence.jsonl"
_MIRROR_LOG_LOCK = threading.Lock()
_MIRROR_LOG_SCALAR_FIELDS = (
    "cycle_started_at",
    "sync_finished_at",
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
    "exit_code",
)
_MIRROR_LOG_NUMERIC_FIELDS = {
    "duration_ms",
    "seconds_since_previous_success",
    "cycle_interval_seconds",
    "scheduler_cycle_interval_seconds",
    "configured_interval_seconds",
    "push_attempt",
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


def _append_mirror_log(event: str, *, source: str, **fields: Any) -> None:
    """Persist safe mirror timing records without making logging a hard dependency."""
    record: dict[str, Any] = {
        "event": event,
        "logged_at": _mirror_timestamp(utc_now()),
        "source": source,
    }
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = _redact_mirror_text(value)[:500]
        record[key] = value
    try:
        MIRROR_CADENCE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _MIRROR_LOG_LOCK:
            with MIRROR_CADENCE_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.warning("PUBLIC_MIRROR_LOG_WRITE_FAILED reason=%s", _redact_mirror_text(str(exc)[:300]))


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


def _log_mirror_script_events(output: str) -> None:
    for line in output.splitlines():
        if "PUBLIC_MIRROR_" in line:
            redacted = _redact_mirror_text(line)
            logger.info("%s", redacted)
            parsed = _parse_mirror_log_line(redacted)
            if parsed:
                event, fields = parsed
                _append_mirror_log(event, source="sync-script", **fields)


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


def create_app(database_url: str | None = None, database_path: Path | None = None) -> FastAPI:
    settings = get_settings()
    db_url = database_url or settings.database_url
    engine, session_factory = create_database(db_url, database_path or settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.heartbeat_stop = asyncio.Event()
        app.state.monitor_alert_stop = asyncio.Event()
        app.state.mirror_stop = asyncio.Event()
        app.state.mirror_event = asyncio.Event()
        with session_factory() as session:
            record_heartbeat(session, HeartbeatPayload(component="backend", state="healthy"))
            update_radar(session)
            session.commit()
            app.state.alert_manager.initialize_baseline(session)
            session.commit()
        task = asyncio.create_task(_backend_heartbeat_loop(session_factory, app.state.heartbeat_stop))
        monitor_task = asyncio.create_task(
            _monitor_alert_loop(session_factory, app.state.monitor_alert_stop, app.state.alert_manager)
        )
        mirror_task = asyncio.create_task(
            _public_mirror_loop(settings, app.state.mirror_stop, app.state.mirror_event)
        ) if settings.github_mirror_enabled else None
        try:
            yield
        finally:
            app.state.heartbeat_stop.set()
            app.state.monitor_alert_stop.set()
            app.state.mirror_stop.set()
            task.cancel()
            monitor_task.cancel()
            if mirror_task:
                mirror_task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            if mirror_task:
                try:
                    await mirror_task
                except asyncio.CancelledError:
                    pass
            engine.dispose()

    app = FastAPI(title="Codex Reset Radar", version="0.1.0", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.engine = engine
    app.state.alert_manager = AlertManager(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://127.0.0.1", "chrome-extension://", "edge-extension://"],
        allow_origin_regex=r"(chrome-extension|edge-extension)://.*",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            record_heartbeat(session, HeartbeatPayload(component="backend", state="healthy"))
            tweet_count = session.scalar(select(func.count()).select_from(Tweet)) or 0
            return {"status": "ok", "service": "codex-reset-radar", "tweets": tweet_count, "time": utc_now().isoformat()}
        finally:
            session.close()

    @app.post("/api/ingest/tweets")
    def ingest_tweets(payload: TweetBatch, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            created, deduplicated = ingest_batch(session, payload.tweets)
            background_tasks.add_task(
                classify_tweet_ids,
                request.app.state.session_factory,
                [tweet.tweet_id for tweet in payload.tweets],
                mirror_event=request.app.state.mirror_event,
            )
            if created:
                request.app.state.mirror_event.set()
            return {"ok": True, "created": created, "deduplicated": deduplicated, "received": len(payload.tweets)}
        except Exception:
            session.rollback()
            logger.exception("Tweet ingestion failed")
            raise
        finally:
            session.close()

    @app.post("/api/heartbeat")
    def heartbeat(payload: HeartbeatPayload, request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            previous = session.get(MonitorHealth, payload.component)
            previous_state = previous.state if previous else None
            health_record = record_heartbeat(session, payload)
            request.app.state.alert_manager.evaluate_monitor_health(session)
            session.commit()
            if previous_state != payload.state:
                request.app.state.mirror_event.set()
            return {
                "ok": True,
                "component": health_record.component,
                "state": health_record.state,
                "last_heartbeat": serialize_datetime(health_record.last_heartbeat),
            }
        finally:
            session.close()

    @app.post("/api/diagnostics")
    def diagnostics_event(payload: DiagnosticPayload, request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
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
            request.app.state.alert_manager.evaluate_monitor_health(session, now=now)
            session.commit()
            return result
        finally:
            session.close()

    @app.get("/api/diagnostics")
    def diagnostic_events(
        request: Request,
        component: str | None = None,
        event: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        session = request.app.state.session_factory()
        try:
            query = select(MonitorDiagnosticEvent).order_by(MonitorDiagnosticEvent.id.desc()).limit(limit)
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
            }
        finally:
            session.close()

    return app


async def _backend_heartbeat_loop(session_factory, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(60)
        if stop_event.is_set():
            return
        with session_factory() as session:
            record_heartbeat(session, HeartbeatPayload(component="backend", state="healthy"))


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
        except Exception:
            logger.exception("Monitor alert evaluation failed")


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
            "configured_interval_seconds=%s previous_success_at=%s trigger=%s result=started",
            _mirror_timestamp(cycle_started_at),
            f"{cycle_interval:.3f}" if cycle_interval is not None else "-",
            f"{scheduler_cycle_interval:.3f}" if scheduler_cycle_interval is not None else "-",
            interval,
            _mirror_timestamp(previous_success_at),
            trigger,
        )
        _append_mirror_log(
            "PUBLIC_MIRROR_CYCLE_STARTED",
            source="scheduler",
            cycle_started_at=_mirror_timestamp(cycle_started_at),
            cycle_interval_seconds=round(cycle_interval, 3) if cycle_interval is not None else None,
            scheduler_cycle_interval_seconds=(
                round(scheduler_cycle_interval, 3) if scheduler_cycle_interval is not None else None
            ),
            configured_interval_seconds=interval,
            previous_success_at=_mirror_timestamp(previous_success_at),
            trigger=trigger,
            result="started",
        )
        success = await asyncio.to_thread(
            _run_public_mirror_sync,
            settings,
            trigger=trigger,
            cycle_started_at=cycle_started_at,
            previous_success_at=previous_success_at,
        )
        sync_finished_at = utc_now()
        duration_ms = int(max(0.0, (sync_finished_at - cycle_started_at).total_seconds() * 1000))
        if success == "published":
            successful_interval = (
                (sync_finished_at - previous_success_at).total_seconds() if previous_success_at else None
            )
            logger.info(
                "PUBLIC_MIRROR_SYNC_SUCCESS cycle_started_at=%s sync_finished_at=%s duration_ms=%s "
                "previous_success_at=%s seconds_since_previous_success=%s trigger=%s result=success",
                _mirror_timestamp(cycle_started_at),
                _mirror_timestamp(sync_finished_at),
                duration_ms,
                _mirror_timestamp(previous_success_at),
                f"{successful_interval:.3f}" if successful_interval is not None else "-",
                trigger,
            )
            last_success_at = sync_finished_at
        elif success == "skipped":
            logger.info(
                "PUBLIC_MIRROR_SYNC_SKIPPED cycle_started_at=%s sync_finished_at=%s duration_ms=%s "
                "previous_success_at=%s seconds_since_previous_success=%s trigger=%s result=skipped reason=no_changes",
                _mirror_timestamp(cycle_started_at),
                _mirror_timestamp(sync_finished_at),
                duration_ms,
                _mirror_timestamp(previous_success_at),
                f"{(sync_finished_at - previous_success_at).total_seconds():.3f}" if previous_success_at else "-",
                trigger,
            )
        else:
            logger.warning(
                "PUBLIC_MIRROR_SYNC_FAILED cycle_started_at=%s sync_finished_at=%s duration_ms=%s "
                "previous_success_at=%s seconds_since_previous_success=%s trigger=%s result=failed",
                _mirror_timestamp(cycle_started_at),
                _mirror_timestamp(sync_finished_at),
                duration_ms,
                _mirror_timestamp(previous_success_at),
                f"{(sync_finished_at - previous_success_at).total_seconds():.3f}" if previous_success_at else "-",
                trigger,
            )
        last_cycle_started_at = cycle_started_at
        if trigger == "scheduled":
            last_scheduled_cycle_started_at = cycle_started_at

        # Event syncs must not move the next scheduled deadline. If a long
        # sync crossed one or more scheduled windows, record those windows and
        # advance the deadline without creating a burst of back-to-back runs.
        while next_scheduled_at <= loop.time():
            logger.info(
                "PUBLIC_MIRROR_SYNC_SKIPPED cycle_started_at=%s sync_finished_at=%s duration_ms=%s "
                "previous_success_at=%s seconds_since_previous_success=%s trigger=scheduled result=skipped reason=%s",
                _mirror_timestamp(cycle_started_at),
                _mirror_timestamp(sync_finished_at),
                duration_ms,
                _mirror_timestamp(previous_success_at),
                "-",
                "cycle_overrun" if trigger == "scheduled" else "event_covered_scheduled_window",
            )
            next_scheduled_at += interval


def _run_public_mirror_sync(
    settings,
    *,
    trigger: str = "manual",
    cycle_started_at: datetime | None = None,
    previous_success_at: datetime | None = None,
) -> str:
    script = Path(__file__).resolve().parents[2] / "scripts" / "sync-github-data.ps1"
    powershell = shutil.which("pwsh") or shutil.which("powershell.exe") or "powershell.exe"
    command = [powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    if cycle_started_at:
        command.extend(["-Trigger", trigger, "-CycleStartedAt", _mirror_timestamp(cycle_started_at)])
    if previous_success_at:
        command.extend(["-PreviousSuccessAt", _mirror_timestamp(previous_success_at)])
    try:
        result = subprocess.run(
            command,
            cwd=script.parents[1],
            capture_output=True,
            text=True,
            timeout=max(120, settings.github_mirror_interval_seconds),
            check=False,
        )
    except Exception as exc:
        sync_finished_at = utc_now()
        logger.warning(
            "PUBLIC_MIRROR_SYNC_FAILED cycle_started_at=%s sync_finished_at=%s duration_ms=- "
            "previous_success_at=%s seconds_since_previous_success=- trigger=%s result=failed reason=%s",
            _mirror_timestamp(cycle_started_at),
            _mirror_timestamp(utc_now()),
            _mirror_timestamp(previous_success_at),
            trigger,
            _redact_mirror_text(str(exc)[:300]),
        )
        _append_mirror_log(
            "PUBLIC_MIRROR_SYNC_FAILED",
            source="scheduler",
            cycle_started_at=_mirror_timestamp(cycle_started_at),
            sync_finished_at=_mirror_timestamp(sync_finished_at),
            previous_success_at=_mirror_timestamp(previous_success_at),
            trigger=trigger,
            result="failed",
            reason=str(exc)[:300],
        )
        return "failed"
    output = _redact_mirror_text(result.stdout or "")
    error = _redact_mirror_text(result.stderr or "")
    _log_mirror_script_events(output)
    _log_mirror_script_events(error)
    if result.returncode != 0:
        sync_finished_at = utc_now()
        logger.warning(
            "PUBLIC_MIRROR_SYNC_FAILED cycle_started_at=%s sync_finished_at=%s duration_ms=- "
            "previous_success_at=%s seconds_since_previous_success=- trigger=%s result=failed "
            "exit_code=%s output=%s error=%s",
            _mirror_timestamp(cycle_started_at),
            _mirror_timestamp(utc_now()),
            _mirror_timestamp(previous_success_at),
            trigger,
            result.returncode,
            output[-500:],
            error[-500:],
        )
        _append_mirror_log(
            "PUBLIC_MIRROR_SYNC_FAILED",
            source="scheduler",
            cycle_started_at=_mirror_timestamp(cycle_started_at),
            sync_finished_at=_mirror_timestamp(sync_finished_at),
            previous_success_at=_mirror_timestamp(previous_success_at),
            trigger=trigger,
            result="failed",
            exit_code=result.returncode,
            reason=(error or output)[-500:],
        )
        return "failed"
    outcome = "skipped" if "PUBLIC_MIRROR_SYNC_SKIPPED" in output else "published"
    logger.info(
        "PUBLIC_MIRROR_SYNC_SCRIPT_COMPLETED cycle_started_at=%s sync_finished_at=%s duration_ms=- "
        "previous_success_at=%s seconds_since_previous_success=- trigger=%s result=completed output=%s",
        _mirror_timestamp(cycle_started_at),
        _mirror_timestamp(utc_now()),
        _mirror_timestamp(previous_success_at),
        trigger,
        output[-500:],
    )
    return outcome


def _evaluate_monitor_alerts(session_factory, alert_manager: AlertManager) -> None:
    with session_factory() as session:
        alert_manager.evaluate_monitor_health(session)
        session.commit()


app = create_app()
