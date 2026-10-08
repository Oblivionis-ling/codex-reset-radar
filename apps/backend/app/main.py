from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .config import REPOSITORY_ROOT, Settings, load_settings
from .collector_health import collector_health, FUTURE_SKEW_SECONDS
from .db import Database, next_reset_baseline
from .deepseek import DeepSeekClient
from .intelligence import JsonModel
from .logging_runtime import RuntimeLog
from .pipeline import IntelligencePipeline
from .prediction_contract import (
    ALL_PREDICTION_TARGETS,
    PREDICTION_ALGORITHM_VERSION,
    PREDICTION_API_VERSION,
    PredictionTarget,
)
from .prediction_ledger import PredictionLedger
from .runtime_identity import capture_runtime_identity
from .schemas import CollectorBatch, CollectorHeartbeat, DiagnosticBatch, DiagnosticPayload, ResetEventCreate
from .version import APP_VERSION, runtime_commit


PREDICTION_HISTORY_LINE_FIELDS = frozenset({
    "target", "record_id", "ledger_seq", "is_synthetic",
    "record_kind", "forecast_id", "series_id", "revision", "question_revision",
    "question_version", "forecast_version", "forecast_revision", "output_revision", "target_output_id", "previous_id",
    "state", "status", "form", "resolved_prediction_form", "prediction_form",
    "predicted_start", "predicted_end", "source_timezone", "precision", "time_basis",
    "method", "scope", "basis", "expression", "relative_expression", "relative_anchor",
    "relative_anchor_at", "posted_anchor", "anchor_limitation", "anchor_time_basis",
    "unresolved_reason", "validation_reason", "valid", "current_or_last_known",
    "output_available_at", "output_available_at_source", "output_availability_kind",
    "updated_at", "updated_at_source", "recorded_at", "judged_at", "date_boundaries", "baseline_status",
    "valid_until", "validity", "validity_state", "health", "health_state", "health_reason",
    "reason", "eligibility_reason",
})
PREDICTION_HISTORY_ATTEMPT_FIELDS = frozenset({
    "target", "series_id", "attempt_number", "attempted_at", "started_at", "finished_at",
    "state", "status", "reason_code", "reason", "output_status",
})


def create_app(
    settings: Settings | None = None,
    intelligence_client: JsonModel | None = None,
    *,
    is_synthetic: bool = False,
) -> FastAPI:
    if not isinstance(is_synthetic, bool):
        raise TypeError("is_synthetic must be an explicit boolean")
    runtime_settings = settings or load_settings()
    loaded_fingerprint = sha256(b''.join((Path(__file__).parent/name).read_bytes()
        for name in ('main.py','db.py','pipeline.py','intelligence.py','reply_context.py','collector_health.py'))).hexdigest()[:16]
    database = Database(runtime_settings.database_path)
    prediction_ledger = PredictionLedger(database)
    runtime_log = RuntimeLog(
        runtime_settings.log_dir,
        runtime_settings.log_retention_days,
        runtime_settings.log_max_bytes,
    )
    collector_state: dict[str, dict[str, Any]] = {}
    pipeline: IntelligencePipeline | None = None
    safe_history_capability: bool | None = None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal pipeline
        database.initialize()
        application.state.database = database
        application.state.prediction_ledger = prediction_ledger
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
            runtime_identity = capture_runtime_identity(runtime_settings, model_client)
            pipeline = IntelligencePipeline(
                database=database,
                client=model_client,
                runtime_log=runtime_log,
                collector_state=collector_state,
                repository_root=REPOSITORY_ROOT,
                judge_interval_seconds=runtime_settings.judge_interval_seconds,
                prediction_ledger=prediction_ledger,
                runtime_identity=runtime_identity,
                is_synthetic=is_synthetic,
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

    def prediction_projection(
        judgement: dict[str, Any] | None,
        validation: dict[str, Any],
        health_view: dict[str, Any],
        judgement_usable: bool,
    ) -> dict[str, Any]:
        current_data_health = str(health_view.get("data_health") or "UNKNOWN")
        generation_data_health = judgement.get("data_health") if judgement else None
        generation_health_reason = (judgement.get("data_health_reason") or judgement.get("health_reason")) if judgement else None
        validation_valid = validation.get("valid") is True
        validation_reason = str(validation.get("reason") or "UNKNOWN")
        ledger_history = getattr(prediction_ledger, "prediction_history", None)

        def history_getter_is_safe() -> bool:
            nonlocal safe_history_capability
            if safe_history_capability is not None:
                return safe_history_capability
            if not callable(ledger_history):
                safe_history_capability = False
                return False
            try:
                probe = ledger_history(target="EXTRA_FULL", series_id=None, limit=1)
            except Exception:
                safe_history_capability = False
                return False
            raw_caps = probe.get("capabilities") if isinstance(probe, dict) and isinstance(probe.get("capabilities"), dict) else {}
            safe_history_capability = (
                isinstance(probe, dict)
                and (probe.get("item_schema") == "prediction-history-line-v1" or raw_caps.get("history_lines") is True)
            )
            return safe_history_capability

        global_health = {
            "validation_valid": validation_valid,
            "validation_reason": validation_reason,
            "validation": {"valid": validation_valid, "reason": validation_reason},
            "current_data_health": current_data_health,
            "current_collector_health": health_view.get("collector", {}),
            "generation_data_health": generation_data_health,
            "generation_health_reason": generation_health_reason,
            "judgement_usable": judgement_usable,
        }
        project = getattr(prediction_ledger, "prediction_lines", None)
        if callable(project):
            result = project(judgement, as_of=datetime.now(UTC))
            if isinstance(result, dict):
                raw_health = result.get("health")
                ledger_health = dict(raw_health) if isinstance(raw_health, dict) else {}
                raw_caps = result.get("capabilities")
                # Older/partial Ledger adapters may omit this optional object.
                # Treat it as empty and infer only the safe capabilities below.
                raw_caps = raw_caps if isinstance(raw_caps, dict) else {}
                capabilities = dict(raw_caps)
                raw_lines = result.get("lines")
                raw_lines = raw_lines if isinstance(raw_lines, dict) else {}
                lines: dict[str, dict[str, Any]] = {}
                for target in ALL_PREDICTION_TARGETS:
                    raw_line = raw_lines.get(target)
                    if isinstance(raw_line, dict):
                        line = dict(raw_line)
                    else:
                        reason = "账本当前没有实现此目标的预测投影。"
                        if target == "NORMAL_WEEKLY":
                            reason = "NOT_BACKFILLED：Normal 参考尚无可读取的版本记录。"
                        line = {
                            "target": target,
                            "record_kind": "baseline" if target == "NORMAL_WEEKLY" else "prediction",
                            "state": "not_backfilled" if target == "NORMAL_WEEKLY" else "not_implemented",
                            "validation_reason": "NORMAL_VERSION_NOT_RECORDED" if target == "NORMAL_WEEKLY" else "LEGACY_TARGET_NOT_IMPLEMENTED",
                            "form": "unknown",
                            "predicted_start": None,
                            "predicted_end": None,
                            "reason": reason,
                            "validity": {"state": "unknown", "reason": reason},
                            "health": {"state": "unknown", "reason": reason},
                        }
                    line["target"] = target
                    baseline = target == "NORMAL_WEEKLY"
                    raw_state = str(line.get("state") or "").lower()
                    raw_status = str(line.get("status") or "").upper()
                    reason_code = str(line.get("validation_reason") or line.get("reason_code") or "")
                    raw_valid = line.get("valid") is True
                    lineage_state = str(line.get("current_or_last_known") or "").lower()
                    baseline_state = str(line.get("baseline_status") or "").lower()
                    validity = line.get("validity")
                    raw_validity_state = str(
                        validity.get("state") if isinstance(validity, dict)
                        else validity or line.get("validity_state") or ""
                    ).lower()
                    explicitly_unimplemented = (
                        raw_state == "not_implemented"
                        or line.get("target_implemented") is False
                        or str(line.get("implementation_state") or "").lower() == "not_implemented"
                        or reason_code in {"LEGACY_TARGET_NOT_IMPLEMENTED", "TARGET_NOT_IMPLEMENTED"}
                    )

                    # Invalidity and lineage take precedence over a model's UNKNOWN
                    # output. UNKNOWN is preserved only when its own output is valid.
                    if baseline and reason_code in {"NORMAL_VERSION_NOT_RECORDED", "NOT_BACKFILLED"}:
                        state = "not_backfilled"
                        line["reason"] = line.get("reason") or "NOT_BACKFILLED：Normal 参考尚未回填为有版本的账本记录。"
                    elif explicitly_unimplemented:
                        state = "not_implemented"
                    elif raw_state in {"failed", "error", "rejected", "invalid", "stale", "data_stale", "expired", "pending", "partial", "not_backfilled", "waiting_for_verified_history"}:
                        state = raw_state
                    elif baseline and baseline_state == "expired":
                        state = "expired"
                    elif raw_validity_state in {"expired", "stale", "data_stale", "failed", "error", "rejected", "invalid"}:
                        state = raw_validity_state
                    elif reason_code in {"EXPIRED", "PREDICTION_WINDOW_PASSED_NOT_CONFIRMED"}:
                        state = "expired"
                    elif lineage_state == "last_known" or reason_code in {"INPUT_CHANGED", "CYCLE_CHANGED", "ANCHOR_CHANGED", "GENERATION_REPLACED"}:
                        state = "stale"
                    elif reason_code == "OUTPUT_AVAILABILITY_PENDING":
                        state = "pending"
                    elif reason_code.startswith(("MODEL_", "REQUEST_", "FAILED", "ERROR")):
                        state = "failed"
                    elif reason_code in {"MISSING_TARGET", "ALL_PREDICTION_TARGETS_REJECTED", "UNKNOWN_REASON_MISSING"}:
                        state = "rejected"
                    elif reason_code == "PREDICTION_NOT_RECORDED" and raw_status not in {"KNOWN", "UNKNOWN"}:
                        # No legacy line is not a model-produced UNKNOWN. New runs
                        # must report MISSING_TARGET (or another explicit failure).
                        state = "not_implemented"
                    elif raw_valid is False and (raw_status in {"KNOWN", "UNKNOWN"} or raw_state in {"known", "current", "ready", "available", "baseline"}):
                        state = "rejected" if reason_code and reason_code != "VALID" else "invalid"
                    elif baseline and baseline_state in {"baseline", "current"} and raw_valid:
                        state = "baseline"
                    elif baseline and baseline_state == "waiting_for_verified_history":
                        state = "waiting_for_verified_history"
                    elif raw_status == "UNKNOWN" or raw_state == "unknown":
                        state = "unknown" if raw_valid else "invalid"
                    elif raw_status == "KNOWN" and raw_valid and lineage_state == "current":
                        state = "baseline" if baseline else "current"
                    elif raw_state == "baseline" and baseline and raw_valid:
                        state = "baseline"
                    elif raw_state in {"ready", "current", "available"} and raw_valid:
                        state = raw_state
                    elif reason_code and reason_code != "VALID":
                        state = "rejected"
                    elif not raw_status and not raw_state:
                        state = "not_implemented"
                    else:
                        state = "invalid"
                    line["state"] = state
                    validity = line.get("validity")
                    validity_state = str(validity.get("state") if isinstance(validity, dict) else validity or line.get("validity_state") or ("valid" if raw_valid else state)).lower()
                    if not isinstance(validity, dict):
                        line["validity"] = {"state": validity_state, "reason": reason_code or None, "valid_until": line.get("valid_until")}
                    source_health = line.get("health")
                    source_health_state = str(
                        source_health.get("state") if isinstance(source_health, dict)
                        else source_health or line.get("health_state") or ("not_applicable" if baseline else generation_data_health or "unknown")
                    ).lower()
                    if not isinstance(source_health, dict):
                        line["health"] = {
                            "state": source_health_state,
                            "reason": None if source_health_state in {"healthy", "not_applicable"}
                            else line.get("health_reason") or generation_health_reason or reason_code or None,
                        }
                    line["reason"] = line.get("reason") or line.get("unresolved_reason") or reason_code or None
                    line["output_availability_kind"] = line.get("output_availability_kind") or line.get("output_available_at_source")
                    line["form"] = (
                        line.get("resolved_prediction_form")
                        or line.get("form")
                        or line.get("prediction_form")
                        or "unknown"
                    )
                    line["relative_expression"] = line.get("relative_expression") or line.get("expression")
                    line["relative_anchor"] = line.get("relative_anchor") or line.get("relative_anchor_at") or line.get("posted_anchor")
                    line["question_revision"] = line.get("question_revision") or line.get("forecast_revision") or line.get("revision")
                    line["question_version"] = line.get("question_version") or line.get("forecast_version")
                    updated_at = line.get("updated_at") or line.get("recorded_at") or line.get("judged_at")
                    updated_at_source = "ledger_recorded_at" if line.get("updated_at") or line.get("recorded_at") else "judgement_time" if line.get("judged_at") else None
                    if not updated_at and judgement and line.get("origin_judgement_id") == judgement.get("id"):
                        updated_at = judgement.get("created_at")
                        updated_at_source = "judgement_time" if updated_at else None
                    if not updated_at and line.get("output_available_at"):
                        updated_at = line.get("output_available_at")
                        updated_at_source = "output_available_at_observation"
                    line["updated_at"] = updated_at
                    line["updated_at_source"] = updated_at_source
                    line_state_ok = state in {"ready", "current", "available", "baseline"}
                    validity_ok = validity_state in {"valid", "ready", "current", "not_applicable"} and line.get("valid") is not False
                    line_health_ok = source_health_state in {"healthy", "ready", "current", "not_applicable"}
                    global_ok = current_data_health == "HEALTHY"
                    if not baseline:
                        global_ok = (
                            global_ok
                            and validation_valid
                            and generation_data_health == "HEALTHY"
                            and judgement_usable
                        )
                    eligible = global_ok and line_state_ok and validity_ok and line_health_ok
                    line["current_advice_eligible"] = eligible
                    line["global_health"] = global_health
                    if not eligible:
                        if state in {"ready", "current", "available", "baseline"}:
                            if current_data_health != "HEALTHY":
                                line["state"] = "failed" if current_data_health in {"FAILED", "ERROR"} else "stale"
                                line["eligibility_reason"] = "当前采集健康未通过；该记录仅作历史参考，不作为当前建议。"
                            elif not baseline and generation_data_health not in {"HEALTHY", None}:
                                line["state"] = "failed" if str(generation_data_health).upper() in {"FAILED", "ERROR"} else "stale"
                                line["eligibility_reason"] = f"生成时数据健康为 {generation_data_health}；不作为当前建议。"
                            elif not baseline and not validation_valid:
                                line["state"] = "stale" if validation_reason == "EXPIRED" else "invalid"
                                line["eligibility_reason"] = f"全局校验未通过（{validation_reason}）；不作为当前建议。"
                            elif not validity_ok:
                                line["state"] = "stale" if validity_state in {"stale", "expired", "data_stale"} else "invalid"
                                line["eligibility_reason"] = f"目标有效性为 {validity_state}；不作为当前建议。"
                            elif not line_health_ok:
                                line["state"] = "failed" if source_health_state in {"failed", "error"} else "unknown"
                                line["eligibility_reason"] = f"目标生成健康为 {source_health_state}；不作为当前建议。"
                            else:
                                line["state"] = "unknown"
                                line["eligibility_reason"] = "目标状态未明确为可用；不作为当前建议。"
                        else:
                            line.setdefault("eligibility_reason", line.get("reason") or f"目标状态为 {state}；不作为当前建议。")
                    lines[target] = line

                    capability_key = {
                        "NORMAL_WEEKLY": "normal_weekly",
                        "EXTRA_FULL": "extra_full",
                        "BANKED": "banked",
                    }[target]
                    raw_model_targets = capabilities.get("model_targets")
                    if target == "NORMAL_WEEKLY":
                        advertised = capabilities.get(capability_key, target in raw_lines)
                    elif isinstance(raw_model_targets, (list, tuple, set)):
                        advertised = target in raw_model_targets
                    else:
                        advertised = capabilities.get(capability_key, capabilities.get(target, target in raw_lines))
                    capabilities[capability_key] = advertised is True
                history_dto_supported = (
                    capabilities.get("history_lines") is True
                    or capabilities.get("history") is True
                    or result.get("item_schema") == "prediction-history-line-v1"
                )
                if not history_dto_supported:
                    history_dto_supported = history_getter_is_safe()
                capabilities["normal_history"] = raw_caps.get("normal_history") is True
                capabilities["ledger_history_readable"] = callable(ledger_history)
                capabilities["history"] = history_dto_supported
                model_states = [lines[target]["state"] for target in ("EXTRA_FULL", "BANKED")]
                if any(state == "failed" for state in model_states):
                    projection_state = "failed"
                elif all(state in {"current", "ready", "available"} for state in model_states):
                    projection_state = "ready"
                elif any(state in {"current", "ready", "available"} for state in model_states):
                    projection_state = "partial"
                elif any(state in {"rejected", "invalid"} for state in model_states):
                    projection_state = "rejected"
                elif any(state in {"stale", "data_stale", "expired"} for state in model_states):
                    projection_state = "stale"
                elif all(state == "not_implemented" for state in model_states):
                    projection_state = "not_implemented"
                else:
                    projection_state = "unknown"
                projection_health = {
                    **ledger_health,
                    **global_health,
                    "ledger": ledger_health,
                }
                return {
                    **result,
                    "version": PREDICTION_API_VERSION,
                    "algorithm_version": PREDICTION_ALGORITHM_VERSION,
                    "state": projection_state,
                    "capabilities": capabilities,
                    "health": projection_health,
                    "lines": lines,
                }

        # Do not synthesize dates when this API is paired with an older Ledger.
        reason = "当前账本构建尚未提供三线预测投影能力。"
        return {
            "version": PREDICTION_API_VERSION,
            "algorithm_version": PREDICTION_ALGORITHM_VERSION,
            "state": "not_implemented",
            "capabilities": {
                "normal_weekly": False,
                "extra_full": False,
                "banked": False,
                "history": False,
                "normal_history": False,
                "ledger_history_readable": callable(ledger_history),
            },
            "health": global_health,
            "lines": {
                target: {
                    "target": target,
                    "record_kind": "baseline" if target == "NORMAL_WEEKLY" else "prediction",
                    "state": "not_implemented",
                    "form": "unknown",
                    "predicted_start": None,
                    "predicted_end": None,
                    "relative_expression": None,
                    "source_timezone": None,
                    "precision": None,
                    "time_basis": None,
                    "method": None,
                    "basis": None,
                    "expression": None,
                    "relative_anchor_at": None,
                    "unresolved_reason": reason,
                    "date_boundaries": None,
                    "output_available_at": None,
                    "output_availability_kind": None,
                    "reason": reason,
                    "updated_at": None,
                    "validity": {"state": "unknown", "valid_until": None},
                    "health": {"state": "unknown", "reason": reason},
                    "series_id": None,
                    "revision": None,
                }
                for target in ALL_PREDICTION_TARGETS
            },
        }

    def radar_payload() -> dict[str, Any]:
        judgement = database.latest_judgement()
        validation = database.validate_judgement(judgement)
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
            "prediction": prediction_projection(judgement, validation, health_view, judgement_usable),
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
                "reply_context_version": "reply-context-v2",
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

    @application.get("/api/v2/predictions/history")
    def prediction_history(
        target: PredictionTarget | None = Query(default=None),
        series_id: str | None = Query(default=None, min_length=1, max_length=200),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        target_value = getattr(target, "value", target)
        if target_value is not None and target_value not in ALL_PREDICTION_TARGETS:
            raise HTTPException(status_code=422, detail="Unsupported prediction target")
        read_history = getattr(prediction_ledger, "prediction_history", None)
        if not callable(read_history):
            return {
                "version": PREDICTION_API_VERSION,
                "state": "not_implemented",
                "target": target_value,
                "series_id": series_id,
                "items": [],
                "total_count": 0,
                "total_count_known": False,
                "truncated": False,
                "reason": "当前账本构建尚未提供预测历史读取能力。",
            }
        result = read_history(target=target_value, series_id=series_id, limit=limit)
        if isinstance(result, list):
            result = {"items": result}
        if isinstance(result, dict):
            items = result.get("items")
            if not isinstance(items, list):
                return {
                    "version": PREDICTION_API_VERSION,
                    "state": "invalid",
                    "target": target_value,
                    "series_id": series_id,
                    "items": [],
                    "attempts": [],
                    "total_count": 0,
                    "total_count_known": False,
                    "truncated": False,
                    "reason": "账本历史结果缺少有效的 items 列表。",
                }

            def is_flat_line(item: Any) -> bool:
                return (
                    isinstance(item, dict)
                    and "payload" not in item
                    and "payload_json" not in item
                    and item.get("target") in ALL_PREDICTION_TARGETS
                    and isinstance(item.get("series_id"), str)
                    and bool(item.get("series_id"))
                    and any(key in item for key in ("state", "status"))
                    and any(key in item for key in ("form", "resolved_prediction_form", "prediction_form", "predicted_start", "expression"))
                    and (target_value is None or item.get("target") == target_value)
                    and (series_id is None or item.get("series_id") == series_id)
                )

            def normalize_history_line(item: dict[str, Any]) -> dict[str, Any]:
                line = {key: value for key, value in item.items() if key in PREDICTION_HISTORY_LINE_FIELDS}
                status_value = str(line.get("status") or "").upper()
                state_value = str(line.get("state") or "").lower()
                reason_code = str(line.get("validation_reason") or "")
                raw_valid = line.get("valid") is True
                lineage = str(line.get("current_or_last_known") or "").lower()
                validity = line.get("validity")
                validity_state = str(
                    validity.get("state") if isinstance(validity, dict)
                    else validity or line.get("validity_state") or ""
                ).lower()
                if line["target"] == "NORMAL_WEEKLY" and reason_code in {"NORMAL_VERSION_NOT_RECORDED", "NOT_BACKFILLED"}:
                    state = "not_backfilled"
                elif state_value == "not_implemented" or reason_code in {"LEGACY_TARGET_NOT_IMPLEMENTED", "TARGET_NOT_IMPLEMENTED"}:
                    state = "not_implemented"
                elif state_value in {"failed", "error", "rejected", "invalid", "stale", "data_stale", "expired", "pending", "partial", "not_backfilled", "waiting_for_verified_history"}:
                    state = state_value
                elif validity_state in {"expired", "stale", "data_stale", "failed", "error", "rejected", "invalid"}:
                    state = validity_state
                elif reason_code in {"EXPIRED", "PREDICTION_WINDOW_PASSED_NOT_CONFIRMED"}:
                    state = "expired"
                elif lineage == "last_known" or reason_code in {"INPUT_CHANGED", "CYCLE_CHANGED", "ANCHOR_CHANGED", "GENERATION_REPLACED"}:
                    state = "stale"
                elif reason_code == "OUTPUT_AVAILABILITY_PENDING":
                    state = "pending"
                elif reason_code.startswith(("MODEL_", "REQUEST_", "FAILED", "ERROR")):
                    state = "failed"
                elif reason_code in {"MISSING_TARGET", "ALL_PREDICTION_TARGETS_REJECTED", "UNKNOWN_REASON_MISSING"}:
                    state = "rejected"
                elif reason_code == "PREDICTION_NOT_RECORDED" and status_value not in {"KNOWN", "UNKNOWN"}:
                    state = "not_implemented"
                elif not raw_valid and status_value in {"KNOWN", "UNKNOWN"}:
                    state = "rejected" if reason_code and reason_code != "VALID" else "invalid"
                elif state_value == "known" and raw_valid:
                    state = "historical"
                elif line["target"] == "NORMAL_WEEKLY" and str(line.get("baseline_status") or "").lower() in {"baseline", "current"} and raw_valid:
                    state = "baseline"
                elif status_value == "UNKNOWN" or state_value == "unknown":
                    state = "unknown" if raw_valid else "invalid"
                elif status_value == "KNOWN" and raw_valid and lineage == "current":
                    state = "current"
                elif state_value in {"ready", "current", "available", "baseline"} and raw_valid:
                    state = state_value
                elif reason_code and reason_code != "VALID":
                    state = "rejected"
                else:
                    state = "not_implemented" if not status_value and not state_value else "invalid"
                line["state"] = state
                line["form"] = line.get("resolved_prediction_form") or line.get("form") or line.get("prediction_form") or "unknown"
                line["relative_expression"] = line.get("relative_expression") or line.get("expression")
                line["relative_anchor"] = line.get("relative_anchor") or line.get("relative_anchor_at") or line.get("posted_anchor")
                line["question_revision"] = line.get("question_revision") or line.get("forecast_revision") or line.get("revision")
                line["question_version"] = line.get("question_version") or line.get("forecast_version")
                line["output_availability_kind"] = line.get("output_availability_kind") or line.get("output_available_at_source")
                line["updated_at"] = line.get("updated_at") or line.get("recorded_at") or line.get("judged_at") or line.get("output_available_at")
                line["updated_at_source"] = item.get("updated_at_source") or (
                    "ledger_recorded_at" if item.get("updated_at") or item.get("recorded_at")
                    else "judgement_time" if item.get("judged_at")
                    else "output_available_at_observation" if item.get("output_available_at")
                    else None
                )
                line["reason"] = line.get("reason") or reason_code or line.get("unresolved_reason")
                if not isinstance(validity, dict):
                    line["validity_state"] = validity_state or ("valid" if raw_valid else state)
                health = line.get("health")
                if not isinstance(health, dict):
                    line["health_state"] = str(health or line.get("health_state") or "unknown").lower()
                return line

            lines_are_flat = all(is_flat_line(item) for item in items)
            raw_capabilities = result.get("capabilities") if isinstance(result.get("capabilities"), dict) else {}
            schema_declared = (
                result.get("item_schema") == "prediction-history-line-v1"
                or raw_capabilities.get("history_lines") is True
                or raw_capabilities.get("history") is True
            )
            history_supported = (bool(items) and lines_are_flat) or schema_declared
            if items and not lines_are_flat:
                # Never decode, expose, or count raw ledger payloads at the API boundary.
                return {
                    "version": PREDICTION_API_VERSION,
                    "state": "not_implemented",
                    "target": target_value,
                    "series_id": series_id,
                    "item_schema": None,
                    "items": [],
                    "attempts": [],
                    "attempts_available": False,
                    "total_count": 0,
                    "total_count_known": False,
                    "truncated": False,
                    "reason": "历史 getter 尚未返回匹配目标与系列的扁平预测 DTO；原始账本记录不会由 API 层解码展示。",
                }

            safe_items = [normalize_history_line(item) for item in items] if history_supported else []
            raw_attempts = result.get("attempts")
            attempts_are_flat = isinstance(raw_attempts, list) and all(
                isinstance(item, dict)
                and "payload" not in item
                and "payload_json" not in item
                and item.get("target") in ALL_PREDICTION_TARGETS
                and (target_value is None or item.get("target") == target_value)
                and isinstance(item.get("series_id"), str)
                and (series_id is None or item.get("series_id") == series_id)
                and any(key in item for key in ("state", "status", "reason_code", "reason"))
                for item in raw_attempts
            )
            safe_attempts = [
                {key: value for key, value in item.items() if key in PREDICTION_HISTORY_ATTEMPT_FIELDS}
                for item in raw_attempts
            ] if attempts_are_flat else []
            reported_total = result.get("total_count", result.get("total", result.get("count")))
            total_known = isinstance(reported_total, int) and not isinstance(reported_total, bool)
            total_count = reported_total if total_known else len(safe_items)
            truncated = (
                result.get("truncated") is True
                or result.get("has_more") is True
                or total_count > len(safe_items)
                or (not total_known and len(safe_items) >= limit)
            )
            state = result.get("state")
            if not isinstance(state, str):
                state = "ready" if history_supported else "not_implemented"
            if not history_supported and state.lower() in {"ready", "current", "available"}:
                state = "not_implemented"
            def boundary_items(plural_key: str, singular_key: str) -> list[dict[str, Any]]:
                raw_boundary = result.get(plural_key)
                if isinstance(raw_boundary, list):
                    candidates = raw_boundary
                else:
                    single = result.get(singular_key)
                    candidates = [single] if isinstance(single, dict) else []
                if not history_supported:
                    return []
                return [normalize_history_line(item) for item in candidates if is_flat_line(item)]

            return {
                "version": PREDICTION_API_VERSION,
                "state": state,
                "target": target_value,
                "series_id": series_id,
                "item_schema": "prediction-history-line-v1" if history_supported else None,
                "items": safe_items,
                "first_items": boundary_items("first_items", "first_item"),
                "last_items": boundary_items("last_items", "last_item"),
                "attempts": safe_attempts,
                "attempts_available": bool(safe_attempts) or result.get("attempts_schema") == "prediction-attempt-v1",
                "attempts_truncated": result.get("attempts_truncated") is True,
                "total_count": total_count,
                "total_count_known": total_known,
                "truncated": truncated,
                "reason": result.get("reason") or result.get("limitation") or (None if history_supported else "当前只有 legacy 原始账本读取能力，尚无安全的扁平历史 DTO。"),
                "order_basis": result.get("order_basis"),
            }
        return {
            "version": PREDICTION_API_VERSION,
            "state": "invalid",
            "target": target_value,
            "series_id": series_id,
            "items": [],
            "total_count": 0,
            "total_count_known": False,
            "truncated": False,
            "reason": "账本历史接口返回了无法识别的结果。",
        }

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
