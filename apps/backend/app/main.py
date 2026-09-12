from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, load_settings
from .db import Database, next_reset_baseline
from .logging_runtime import RuntimeLog
from .schemas import CollectorBatch, CollectorHeartbeat, DiagnosticBatch, DiagnosticPayload, ResetEventCreate
from .version import APP_VERSION, runtime_commit


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or load_settings()
    database = Database(runtime_settings.database_path)
    runtime_log = RuntimeLog(
        runtime_settings.log_dir,
        runtime_settings.log_retention_days,
        runtime_settings.log_max_bytes,
    )
    collector_state: dict[str, dict[str, Any]] = {}

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        application.state.database = database
        application.state.collector_state = collector_state
        runtime_log.write(
            "app",
            "V2_BACKEND_READY",
            metadata={"version": APP_VERSION, "commit": runtime_commit(), "mirror_scheduler": False},
        )
        yield

    application = FastAPI(
        title="Codex Reset Radar V2",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    if runtime_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(runtime_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Request-ID", "X-Trace-ID", "X-Extension-Instance-ID"],
        )

    def radar_payload() -> dict[str, Any]:
        judgement = database.latest_judgement()
        last_full = database.last_full_reset()
        special = [
            event
            for event in database.list_reset_events(20)
            if event["event_type"] == "SPECIAL_RESET"
        ][:5]
        if judgement:
            payload = {
                "action_level": judgement["action_level"],
                "horizon_24h": judgement["horizon_24h"],
                "horizon_48h": judgement["horizon_48h"],
                "horizon_72h": judgement["horizon_72h"],
                "data_health": judgement["data_health"],
                "reason_summary": judgement["reason_summary"],
                "evidence_post_ids": judgement["evidence_post_ids"],
                "special_event_ids": judgement["special_event_ids"],
                "model": judgement["model"],
                "prompt_version": judgement["prompt_version"],
                "judged_at": judgement["created_at"],
            }
        else:
            payload = {
                "action_level": "UNKNOWN",
                "horizon_24h": "UNKNOWN",
                "horizon_48h": "UNKNOWN",
                "horizon_72h": "UNKNOWN",
                "data_health": "UNKNOWN",
                "reason_summary": "V2 Judge is not enabled. No reliable forward judgement is available.",
                "evidence_post_ids": [],
                "special_event_ids": [],
                "model": None,
                "prompt_version": "v2-contract-alpha1",
                "judged_at": None,
            }
        return {
            "version": APP_VERSION,
            **payload,
            "next_reset": next_reset_baseline(last_full),
            "last_full_reset": last_full,
            "special_resets": special,
        }

    @application.get("/api/v2/health")
    @application.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "healthy",
            "service": "codex-reset-radar-v2",
            "version": APP_VERSION,
            "commit": runtime_commit(),
            "database": {"status": "ready", "counts": database.counts()},
            "collector": collector_state,
            "runtime": {
                "github_mirror_enabled": False,
                "pages_dependency": False,
                "log_retention_days": runtime_settings.log_retention_days,
            },
        }

    @application.get("/api/v2/radar")
    def radar() -> dict[str, Any]:
        return radar_payload()

    @application.get("/api/v2/posts")
    def posts(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"items": database.list_posts(limit), "count": database.counts()["tibo_posts"]}

    @application.get("/api/v2/resets")
    def resets(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return {"items": database.list_reset_events(limit), "last_full_reset": database.last_full_reset()}

    @application.post("/api/v2/resets", status_code=status.HTTP_201_CREATED)
    def create_reset(payload: ResetEventCreate) -> dict[str, Any]:
        try:
            event = database.record_reset_event(payload.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        runtime_log.write("app", "RESET_EVENT_RECORDED", metadata={"event_id": event["id"], "event_type": event["event_type"]})
        return event

    def ingest_batch(payload: CollectorBatch) -> dict[str, Any]:
        accepted = database.upsert_posts(post.as_record() for post in payload.tweets)
        if payload.tweets:
            runtime_log.write("collector", "POST_BATCH_INGESTED", metadata={"received": len(payload.tweets), "accepted": accepted})
        return {"accepted": accepted, "received": len(payload.tweets)}

    @application.post("/api/v2/collector/posts")
    def collector_posts(payload: CollectorBatch) -> dict[str, Any]:
        return ingest_batch(payload)

    @application.post("/api/ingest/tweets")
    def legacy_collector_posts(payload: CollectorBatch) -> dict[str, Any]:
        return ingest_batch(payload)

    def receive_heartbeat(payload: CollectorHeartbeat) -> dict[str, Any]:
        observed = payload.observed_at or datetime.now(UTC)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        collector_state[payload.component] = {
            "state": payload.state,
            "instance_id": payload.instance_id,
            "sequence": payload.sequence,
            "last_seen_at": observed.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        return {"accepted": True, "persisted": False}

    @application.post("/api/v2/collector/heartbeat")
    def collector_heartbeat(payload: CollectorHeartbeat) -> dict[str, Any]:
        return receive_heartbeat(payload)

    @application.post("/api/heartbeat")
    def legacy_collector_heartbeat(payload: CollectorHeartbeat) -> dict[str, Any]:
        return receive_heartbeat(payload)

    @application.post("/api/diagnostics", status_code=status.HTTP_202_ACCEPTED)
    def legacy_diagnostic(_: DiagnosticPayload) -> dict[str, Any]:
        return {"accepted": True, "persisted": False}

    @application.post("/api/diagnostics/batch", status_code=status.HTTP_202_ACCEPTED)
    def legacy_diagnostic_batch(payload: DiagnosticBatch) -> dict[str, Any]:
        return {"accepted": len(payload.events), "persisted": False}

    @application.exception_handler(Exception)
    async def unexpected_error(_: Request, error: Exception):
        runtime_log.write("errors", "UNHANDLED_REQUEST_ERROR", result="failure", metadata={"error_type": type(error).__name__})
        raise error

    return application


app = create_app()
