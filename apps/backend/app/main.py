from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, load_settings
from .db import Database, next_reset_baseline
from .deepseek import DeepSeekClient
from .intelligence import JsonModel
from .logging_runtime import RuntimeLog
from .pipeline import IntelligencePipeline
from .schemas import CollectorBatch, CollectorHeartbeat, DiagnosticBatch, DiagnosticPayload, ResetEventCreate
from .version import APP_VERSION, runtime_commit


def create_app(settings: Settings | None = None, intelligence_client: JsonModel | None = None) -> FastAPI:
    runtime_settings = settings or load_settings()
    database = Database(runtime_settings.database_path)
    runtime_log = RuntimeLog(
        runtime_settings.log_dir,
        runtime_settings.log_retention_days,
        runtime_settings.log_max_bytes,
    )
    collector_state: dict[str, dict[str, Any]] = {}
    pipeline: IntelligencePipeline | None = None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal pipeline
        database.initialize()
        application.state.database = database
        application.state.collector_state = collector_state
        model_client = intelligence_client
        if model_client is None and runtime_settings.deepseek_api_key:
            model_client = DeepSeekClient(
                api_key=runtime_settings.deepseek_api_key,
                base_url=runtime_settings.deepseek_base_url,
                model=runtime_settings.deepseek_model,
                timeout_seconds=runtime_settings.deepseek_timeout_seconds,
                retries=runtime_settings.deepseek_retries,
                runtime_log=runtime_log,
            )
        if model_client is not None:
            pipeline = IntelligencePipeline(
                database=database,
                client=model_client,
                runtime_log=runtime_log,
                collector_state=collector_state,
                repository_root=runtime_settings.database_path.resolve().parents[2],
                judge_interval_seconds=runtime_settings.judge_interval_seconds,
            )
            await pipeline.start()
        else:
            database.set_state("pipeline", {"status": "blocked", "enabled": False, "last_error": "DeepSeek API key is not configured"})
            database.set_state("judge", {"status": "blocked", "last_error": "DeepSeek API key is not configured"})
        application.state.pipeline = pipeline
        runtime_log.write(
            "app",
            "V2_BACKEND_READY",
            metadata={"version": APP_VERSION, "commit": runtime_commit(), "mirror_scheduler": False, "intelligence_pipeline": pipeline is not None},
        )
        yield
        if pipeline is not None:
            await pipeline.stop()

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
        judge_state = database.get_state("judge", {"status": "waiting"})
        pipeline_state = database.get_state("pipeline", {"status": "waiting"})
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
                "valid_until": judgement.get("valid_until"),
                "estimated_start": judgement.get("estimated_start"),
                "estimated_end": judgement.get("estimated_end"),
                "estimate_basis": judgement.get("estimate_basis"),
                "judgement_id": judgement["id"],
                "corpus_version": judgement.get("corpus_version"),
                "historical_case_ids": judgement.get("historical_case_ids") or [],
                "judgement_state": "stale" if judgement.get("valid_until") and judgement["valid_until"] < datetime.now(UTC).isoformat().replace("+00:00", "Z") else "ready",
            }
        else:
            state = str(judge_state.get("status") or pipeline_state.get("status") or "waiting")
            reason = {
                "processing": "采集正常，首次 DeepSeek 判断正在进行中。",
                "failed": f"采集数据仍保留，但模型请求失败：{judge_state.get('last_error') or '未知错误'}",
                "blocked": "DeepSeek 未配置，无法生成可靠判断。",
            }.get(state, "首次判断尚未完成。")
            payload = {
                "action_level": "UNKNOWN",
                "horizon_24h": "UNKNOWN",
                "horizon_48h": "UNKNOWN",
                "horizon_72h": "UNKNOWN",
                "data_health": "UNKNOWN",
                "reason_summary": reason,
                "evidence_post_ids": [],
                "special_event_ids": [],
                "model": None,
                "prompt_version": "v2-reset-judge-1",
                "judged_at": None,
                "valid_until": None,
                "estimated_start": None,
                "estimated_end": None,
                "estimate_basis": "当前尚无已完成的模型判断。",
                "judgement_id": None,
                "corpus_version": database.corpus_version(),
                "historical_case_ids": [],
                "judgement_state": state,
            }
        return {
            "version": APP_VERSION,
            **payload,
            "next_reset": next_reset_baseline(last_full),
            "last_full_reset": last_full,
            "special_resets": special,
            "judge_runtime": judge_state,
            "pipeline": pipeline_state,
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
                "intelligence_enabled": pipeline is not None,
                "intelligence_model": runtime_settings.deepseek_model if pipeline is not None else None,
            },
            "intelligence": {
                "pipeline": database.get_state("pipeline", {"status": "waiting"}),
                "judge": database.get_state("judge", {"status": "waiting"}),
                "pending_jobs": database.pending_job_count(),
                "corpus": database.corpus_inventory(),
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
        return {"items": database.list_reset_events(limit), "last_full_reset": database.last_full_reset(), "candidates": database.list_candidates(limit)}

    @application.post("/api/v2/resets", status_code=status.HTTP_201_CREATED)
    def create_reset(payload: ResetEventCreate) -> dict[str, Any]:
        try:
            event = database.record_reset_event(payload.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        runtime_log.write("app", "RESET_EVENT_RECORDED", metadata={"event_id": event["id"], "event_type": event["event_type"]})
        if pipeline is not None:
            pipeline.request_judge("manual_reset_event")
        return event

    def ingest_batch(payload: CollectorBatch) -> dict[str, Any]:
        results = database.upsert_posts_detailed(post.as_record() for post in payload.tweets)
        counts = {name: sum(item["status"] == name for item in results) for name in ("new", "updated", "duplicate")}
        queued = pipeline.enqueue_ingest(results) if pipeline is not None else 0
        accepted = counts["new"] + counts["updated"]
        if payload.tweets:
            runtime_log.write("collector", "POST_BATCH_INGESTED", metadata={"received": len(payload.tweets), "accepted": accepted, "new": counts["new"], "updated": counts["updated"], "duplicate": counts["duplicate"], "queued": queued})
        return {"accepted": accepted, "received": len(payload.tweets), **counts, "queued": queued, "items": results}

    @application.post("/api/v2/collector/posts")
    def collector_posts(payload: CollectorBatch) -> dict[str, Any]:
        return ingest_batch(payload)

    @application.post("/api/ingest/tweets")
    def legacy_collector_posts(payload: CollectorBatch) -> dict[str, Any]:
        return ingest_batch(payload)

    def receive_heartbeat(payload: CollectorHeartbeat) -> dict[str, Any]:
        required = ("profile_monitor", "replies_monitor")
        before_ready = all(name in collector_state for name in required)
        previous_state = collector_state.get(payload.component, {}).get("state")
        observed = payload.observed_at or datetime.now(UTC)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        collector_state[payload.component] = {
            "state": payload.state,
            "instance_id": payload.instance_id,
            "sequence": payload.sequence,
            "last_seen_at": observed.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        after_ready = all(name in collector_state for name in required)
        if pipeline is not None and ((not before_ready and after_ready) or (previous_state is not None and previous_state != payload.state)):
            pipeline.request_judge("collector_health_transition")
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
