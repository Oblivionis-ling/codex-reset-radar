from __future__ import annotations

import asyncio
import json
import logging
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
from app.classifiers.service import classify_tweet, classify_tweet_ids
from app.intelligence.radar import update_radar
from app.models import Alert, Classification, MonitorDiagnosticEvent, MonitorHealth, RadarState, Tweet, TweetSource
from app.notifications.alert_manager import AlertManager, derived_monitor_state
from app.schemas import DiagnosticPayload, HeartbeatPayload, TweetBatch


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("radar")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def create_app(database_url: str | None = None, database_path: Path | None = None) -> FastAPI:
    settings = get_settings()
    db_url = database_url or settings.database_url
    engine, session_factory = create_database(db_url, database_path or settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.heartbeat_stop = asyncio.Event()
        app.state.monitor_alert_stop = asyncio.Event()
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
        try:
            yield
        finally:
            app.state.heartbeat_stop.set()
            app.state.monitor_alert_stop.set()
            task.cancel()
            monitor_task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            try:
                await monitor_task
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
            background_tasks.add_task(classify_tweet_ids, request.app.state.session_factory, [tweet.tweet_id for tweet in payload.tweets])
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
            health_record = record_heartbeat(session, payload)
            request.app.state.alert_manager.evaluate_monitor_health(session)
            session.commit()
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
        return await classify_tweet_ids(request.app.state.session_factory, list(tweet_ids), force=force)

    @app.get("/api/radar")
    def radar(request: Request) -> dict[str, Any]:
        session = request.app.state.session_factory()
        try:
            decision = update_radar(session)
            request.app.state.alert_manager.handle_radar_transition(session, decision)
            session.commit()
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


def _evaluate_monitor_alerts(session_factory, alert_manager: AlertManager) -> None:
    with session_factory() as session:
        alert_manager.evaluate_monitor_health(session)
        session.commit()


app = create_app()
