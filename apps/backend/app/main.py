from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, load_settings
from .collector_health import collector_health, FUTURE_SKEW_SECONDS
from .db import Database, next_reset_baseline
from .deepseek import DeepSeekClient
from .intelligence import JsonModel
from .logging_runtime import RuntimeLog
from .pipeline import IntelligencePipeline
from .schemas import CollectorBatch, CollectorHeartbeat, DiagnosticBatch, DiagnosticPayload, ResetEventCreate
from .version import APP_VERSION, runtime_commit


def create_app(settings: Settings | None = None, intelligence_client: JsonModel | None = None) -> FastAPI:
    runtime_settings = settings or load_settings()
    loaded_fingerprint = sha256(b''.join((Path(__file__).parent/name).read_bytes()
        for name in ('main.py','db.py','pipeline.py','intelligence.py','reply_context.py','collector_health.py',
                     'hybrid_decision.py','laya_worker.py','config.py'))).hexdigest()[:16]
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
                decision_settings=runtime_settings.decision_settings,
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
        validation = database.validate_judgement(judgement)
        raw_decision = (judgement or {}).get('raw') or {}
        local_run = raw_decision.get('laya')
        local_identity = local_run.get('identity') if isinstance(local_run, dict) else None
        configured_mode = runtime_settings.decision_settings.mode if runtime_settings.decision_settings else 'deepseek_only'
        if validation['valid'] and raw_decision.get('decision_mode', 'deepseek_only') != configured_mode:
            validation = {**validation, 'valid': False, 'reason': 'DECISION_MODE_CHANGED'}
        if (validation['valid'] and configured_mode == 'deepseek_laya'
                and raw_decision.get('decision_config_identity') != runtime_settings.decision_settings.identity()):
            validation = {**validation, 'valid': False, 'reason': 'DECISION_CONFIG_CHANGED'}
        health_view = collector_health(collector_state)
        judgement_usable = bool(validation['valid'] and judgement['data_health'] == 'HEALTHY'
                                 and health_view['data_health'] == 'HEALTHY')
        judge_state = database.get_state("judge", {"status": "waiting"})
        pipeline_state = database.get_state("pipeline", {"status": "waiting"})
        last_full = database.last_full_reset()
        special = [
            event
            for event in database.list_reset_events(20)
            if event["event_type"] == "SPECIAL_RESET"
        ][:5]
        if judgement and judgement_usable:
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
            if judgement:
                code = validation['reason']
                state = 'data_stale' if validation['valid'] else 'stale' if code == 'EXPIRED' else 'invalid'
                reason = ('采集数据过期或本次判断基于陈旧数据；暂不能可靠判断。下方仅保留最后已知结果。'
                          if validation['valid'] else {
                              'EXPIRED': '上次判断已过期，等待新的判断。',
                              'INPUT_CHANGED': '输入或父帖上下文已经变化，旧结果失效，等待重判。',
                              'CYCLE_CHANGED': '完整 Reset 周期已变化，旧结果失效，等待重判。',
                              'CONTENT_RESTRICTED': '判断使用的内容已受限制，旧结果不能作为当前依据。',
                          }.get(code, f'已有判断，但校验失败：{code}。'))
            else:
                reason = {
                    "processing": "尚未生成判断，DeepSeek 正在处理。",
                    "failed": f"采集数据仍保留，但模型请求失败：{judge_state.get('last_error') or '未知错误'}",
                    "blocked": "DeepSeek 未配置，无法生成可靠判断。",
                }.get(state, "尚未生成判断。")
            payload = {
                "action_level": "UNKNOWN",
                "horizon_24h": "UNKNOWN",
                "horizon_48h": "UNKNOWN",
                "horizon_72h": "UNKNOWN",
                "data_health": judgement.get('data_health', 'UNKNOWN') if judgement else health_view['data_health'],
                "reason_summary": reason,
                "evidence_post_ids": [],
                "special_event_ids": [],
                "model": judgement.get("model") if judgement else None,
                "prompt_version": judgement.get("prompt_version") if judgement else "v2-reset-judge-1",
                "judged_at": judgement.get("created_at") if judgement else None,
                "valid_until": judgement.get("valid_until") if judgement else None,
                "estimated_start": None,
                "estimated_end": None,
                "estimate_basis": reason,
                "judgement_id": judgement.get("id") if judgement else None,
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
            "special_announcements": database.special_announcements(),
            "validation": validation,
            "current_data_health": health_view['data_health'],
            "judgement_data_health": judgement.get('data_health') if judgement else None,
            "display_mode": ('model_unknown' if judgement_usable and judgement['action_level']=='UNKNOWN' else
                             'current' if judgement_usable else 'last_known' if validation['valid'] else 'unavailable'),
            "last_known_result": {k: judgement.get(k) for k in ('id','action_level','horizon_24h','horizon_48h','horizon_72h','created_at','valid_until','reason_summary','data_health')} if judgement else None,
            "judge_runtime": judge_state,
            "decision": {**{key: raw_decision.get(key) for key in
                         ('decision_engine', 'decision_mode', 'question_schema', 'evidence_prompt',
                          'fallback_reason', 'forecast_candidate_id', 'decision_package_hash')},
                         'laya_identity': local_identity if isinstance(local_identity, dict) else None},
            "pipeline": pipeline_state,
        }

    @application.get("/api/v2/health")
    @application.get("/health")
    def health() -> dict[str, Any]:
        health_view = collector_health(collector_state)
        return {
            "status": "healthy",
            "service": "codex-reset-radar-v2",
            "version": APP_VERSION,
            "commit": runtime_commit(),
            "database": {"status": "ready", "counts": database.counts()},
            "collector": health_view['collector'],
            "data_health": health_view['data_health'],
            "runtime": {
                "github_mirror_enabled": False,
                "pages_dependency": False,
                "log_retention_days": runtime_settings.log_retention_days,
                "intelligence_enabled": pipeline is not None,
                "intelligence_model": runtime_settings.deepseek_model if pipeline is not None else None,
                "reply_context_version": "reply-context-v1",
                "reply_context_fingerprint": loaded_fingerprint,
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

    @application.post('/api/v2/judge/request')
    async def request_current_judge() -> dict:
        if pipeline is None:
            raise HTTPException(503, 'Model pipeline is not configured')
        pipeline.request_judge('manual_current_judge')
        return {'queued': True, 'coalesced': True}

    @application.post('/api/v2/posts/{tweet_id}/reprocess')
    async def reprocess_post(tweet_id: str) -> dict:
        post = database.get_post_by_tweet_id(tweet_id)
        if not post:
            raise HTTPException(404, 'Known post required')
        if pipeline is None:
            raise HTTPException(503, 'Model pipeline is not configured')
        queued = database.request_post_reprocess(post['id'], pipeline.identity(post))
        if queued:
            pipeline.request_judge('explicit_post_reprocess')
        return {'queued':queued, 'cache_policy':'reuse_identical_semantic_input'}

    @application.get("/api/v2/posts")
    def posts(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"items": database.list_posts(limit), "count": database.counts()["tibo_posts"]}

    @application.post('/api/v2/context/claim')
    def context_claim() -> dict:
        return {'job':database.contexts.claim()}

    @application.get('/api/v2/context/cache/{tweet_id}')
    def context_cache(tweet_id: str) -> dict:
        return {'node':database.contexts.node(tweet_id)}

    @application.post('/api/v2/context/retry/{tweet_id}')
    def context_retry(tweet_id: str) -> dict:
        post=database.get_post_by_tweet_id(tweet_id)
        if not post or not post['is_reply']:
            raise HTTPException(404,'Known reply required')
        database.contexts.ensure(tweet_id)
        with database.connect() as c:
            changed=c.execute("UPDATE processing_jobs SET status='PENDING',attempts=0,next_attempt_at=NULL,last_error=NULL WHERE job_type='REPLY_CONTEXT' AND entity_key=? AND status!='RUNNING'",(tweet_id,)).rowcount
        return {'queued':bool(changed)}

    @application.post('/api/v2/context/result')
    async def context_result(payload: dict) -> dict:
        # Compare semantic inputs, not receipt times: an identical cached reply
        # must not schedule another paid analysis or Judge call.
        with database.connect() as c:
            rows=c.execute("SELECT id FROM tibo_posts WHERE is_reply=1 AND posted_at>=datetime('now','-7 days') AND ingestion_mode!='historical'").fetchall()
        before={row['id']:database.contexts.input(database.get_post(row['id']))['input_hash'] for row in rows}
        try:
            accepted = database.contexts.complete(int(payload['id']),str(payload['lease']),payload.get('nodes',[]),payload.get('reason'))
        except (KeyError,TypeError,ValueError) as error:
            raise HTTPException(422,str(error)) from error
        if accepted and pipeline:
            # Shared ancestors can invalidate several replies, coalesced by semantic identity.
            changed=False
            for post_id, old_hash in before.items():
                post=database.get_post(post_id)
                if database.contexts.input(post)['input_hash']==old_hash:
                    continue
                changed=True
                identity=pipeline.identity(post)
                database.enqueue_post(post['id'],identity,retry_failed=False)
            if changed:
                pipeline.request_judge('reply_context_updated')
        runtime_log.write('collector','REPLY_CONTEXT_RESULT',metadata={'job_id':payload.get('id'),'accepted':accepted,'nodes':len(payload.get('nodes',[])),'reason':payload.get('reason')})
        return {'accepted':accepted}

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
    async def collector_posts(payload: CollectorBatch) -> dict[str, Any]:
        return ingest_batch(payload)

    @application.post("/api/ingest/tweets")
    async def legacy_collector_posts(payload: CollectorBatch) -> dict[str, Any]:
        return ingest_batch(payload)

    def receive_heartbeat(payload: CollectorHeartbeat) -> dict[str, Any]:
        before_health = collector_health(collector_state)['data_health']
        observed = payload.observed_at or datetime.now(UTC)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        stamp = observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
        previous = collector_state.get(payload.component, {})
        if observed > datetime.now(UTC) + timedelta(seconds=FUTURE_SKEW_SECONDS):
            return {'accepted': False, 'persisted': False, 'reason': 'CLOCK_SKEW'}
        if previous.get('last_seen_at') and stamp <= previous['last_seen_at']:
            return {'accepted': False, 'persisted': False, 'reason': 'OLD_HEARTBEAT'}
        collector_state[payload.component] = {
            "state": payload.state,
            "instance_id": payload.instance_id,
            "sequence": payload.sequence,
            "last_seen_at": stamp,
            "received_at": datetime.now(UTC).isoformat().replace('+00:00','Z'),
        }
        if pipeline is not None and before_health != collector_health(collector_state)['data_health']:
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
