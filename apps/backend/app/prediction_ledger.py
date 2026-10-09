from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .db import JudgementReferenceError
from .review_common import canonical_bytes, sha256_json, utc_text
from .prediction_contract import (
    ALL_PREDICTION_TARGETS, PREDICTION_API_VERSION, PREDICTION_CONTRACT_VERSION, PREDICTION_TARGETS, PredictionTargetsError,
    next_reset_baseline, safe_target_output, validate_predictions,
)


OUTPUT_AVAILABLE_SOURCE = "formal_read_post_commit_upper_bound"
ATTEMPT_TERMINAL_EVENTS = frozenset({
    "http_failure", "network_failure", "timeout", "cancelled", "parse_failure",
    "schema_failure", "reference_failure", "late_input_rejected", "success",
    "persistence_failure", "request_failure", "recovered_terminal_unknown",
})
STATUS_RUN_STATES = frozenset({
    "not_started", "pending", "succeeded", "timeout", "failed", "cancelled", "unknown_terminal",
})
STATUS_RESULT_STATES = frozenset({
    "not_attempted", "not_returned", "accepted", "unknown_valid", "rejected",
    "unavailable", "legacy_missing",
})
STATUS_HISTORY_STATES = frozenset({"backfilled", "not_backfilled", "unknown", "not_applicable"})
STATUS_IMPLEMENTATIONS = frozenset({"supported", "unsupported", "unknown"})
STATUS_SOURCES = frozenset({"ledger_v2", "legacy_undeclared", "unknown", "contract_error"})
STATUS_NORMAL_CALCULATIONS = frozenset({"calculated", "no_business_full_anchor", "unresolved", "expired"})
STATUS_LAST_KNOWN_STATES = frozenset({"valid", "expired", "cycle_changed", "version_changed", "invalid"})
TEXT_FIELDS = frozenset({
    "text", "original_text", "text_snapshot", "summary", "reason_summary",
    "context_text", "evidence_quote", "event_title", "coverage_limitations",
})
FORBIDDEN_LEDGER_KEYS = frozenset({
    "api_key", "authorization", "headers", "raw_response", "response_body",
    "access_token", "refresh_token", "client_secret", "password", "credential",
    "reasoning_content", "chain_of_thought", "messages", "system_prompt", "user_prompt",
})


def normalize_prediction_status_projection(line: dict[str, Any], *, target: str | None = None) -> dict[str, Any]:
    """Return the one safe, dimensioned status DTO used by Radar and history."""
    projection_present = isinstance(line, dict) and "status_projection" in line
    raw = line.get("status_projection") if isinstance(line, dict) else None
    if target is None and isinstance(line, dict):
        target = line.get("target") if isinstance(line.get("target"), str) else None
    if projection_present and not isinstance(raw, dict):
        return _contract_error_status_projection(line, target)
    if isinstance(raw, dict):
        capability = raw.get("capability")
        run = raw.get("run")
        result = raw.get("result")
        implementation = capability.get("implementation") if isinstance(capability, dict) else None
        source = capability.get("source") if isinstance(capability, dict) else None
        run_state = run.get("state") if isinstance(run, dict) else None
        result_state = result.get("state") if isinstance(result, dict) else None
        history_status = raw.get("history_status")
        normal = raw.get("normal")
        normal_status = normal.get("calculation_status") if isinstance(normal, dict) else None
        last_known = raw.get("last_known")
        reason_values = (
            result.get("reason_code") if isinstance(result, dict) else None,
            run.get("reason_code") if isinstance(run, dict) else None,
        )
        optional_run_fields_valid = isinstance(run, dict) and all(
            run.get(key) is None or isinstance(run.get(key), str)
            for key in ("run_id", "attempt_id", "finished_at")
        )
        optional_result_fields_valid = isinstance(result, dict) and (
            result.get("summary") is None or isinstance(result.get("summary"), str)
        )
        normal_fields_valid = (
            normal is None or isinstance(normal, dict)
            and (normal.get("helper_status") is None or isinstance(normal.get("helper_status"), str))
        )
        last_known_valid = last_known is None or _last_known_projection_is_well_formed(last_known)
        model_target = target != "NORMAL_WEEKLY"
        if (
            not isinstance(implementation, str) or implementation not in STATUS_IMPLEMENTATIONS
            or not isinstance(source, str) or source not in STATUS_SOURCES
            or not isinstance(run_state, str) or run_state not in STATUS_RUN_STATES
            or not isinstance(result_state, str) or result_state not in STATUS_RESULT_STATES
            or not isinstance(history_status, str) or history_status not in STATUS_HISTORY_STATES
            or not optional_run_fields_valid or not optional_result_fields_valid
            or any(value is not None and _safe_status_reason(value) is None for value in reason_values)
            or not normal_fields_valid or not last_known_valid
            or (target == "NORMAL_WEEKLY" and (not isinstance(normal, dict)
                or not isinstance(normal_status, str) or normal_status not in STATUS_NORMAL_CALCULATIONS))
            or (target != "NORMAL_WEEKLY" and normal is not None)
        ):
            return _contract_error_status_projection(line, target)
        else:
            run_id = run.get("run_id")
            attempt_id = run.get("attempt_id")
            contradictory = (
                source == "contract_error"
                or (source == "ledger_v2" and implementation != "supported")
                or (source == "unknown" and result_state in {"accepted", "unknown_valid"})
                or (result_state == "legacy_missing" and source != "legacy_undeclared")
                or (run_state == "not_started" and (run_id is not None or attempt_id is not None
                    or run.get("finished_at") is not None))
                or (run_state == "pending" and run.get("finished_at") is not None)
                or (model_target and source == "ledger_v2" and run_state == "not_started"
                    and result_state != "not_attempted")
                or (model_target and source == "ledger_v2" and result_state in {"accepted", "unknown_valid"}
                    and run_state != "succeeded")
                or (model_target and source == "ledger_v2" and run_state in {"pending", "timeout", "failed", "cancelled", "unknown_terminal"}
                    and result_state in {"accepted", "unknown_valid", "rejected"})
                or (model_target and source == "ledger_v2" and run_state == "succeeded"
                    and result_state in {"not_attempted", "not_returned"})
                or (source == "ledger_v2" and result_state == "unavailable")
                or (model_target and source == "ledger_v2" and result_state == "legacy_missing")
                or (source == "ledger_v2" and run_state in {"timeout", "failed", "cancelled", "unknown_terminal"}
                    and result_state == "not_attempted")
                or (source == "ledger_v2" and result_state == "not_returned"
                    and run_state not in {"pending", "timeout", "failed", "cancelled", "unknown_terminal"})
                or (source == "legacy_undeclared" and target == "BANKED" and result_state != "legacy_missing")
            )
            if contradictory:
                return _contract_error_status_projection(line, target)
            reason_code = _safe_status_reason(result.get("reason_code"))
            run_reason = _safe_status_reason(run.get("reason_code"))
            output = {
                "capability": {"implementation": implementation, "source": source},
                "run": {
                    "state": run_state,
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "finished_at": run.get("finished_at") if isinstance(run.get("finished_at"), str) else None,
                    "reason_code": run_reason,
                },
                "result": {
                    "state": result_state,
                    "reason_code": reason_code,
                    "summary": _status_summary(reason_code),
                },
                "history_status": history_status,
                "last_known": _safe_last_known(last_known),
            }
            if isinstance(normal, dict):
                helper_status = normal.get("helper_status")
                output["normal"] = {
                    "helper_status": helper_status[:80] if isinstance(helper_status, str) else None,
                    "calculation_status": normal_status,
                }
            if source == "contract_error":
                output["result"] = {
                    "state": "unavailable",
                    "reason_code": reason_code or "PREDICTION_STATUS_CONTRACT_ERROR",
                    "summary": "来源记录与预测契约不一致。",
                }
                output["last_known"] = None
            return output

    if not isinstance(line, dict):
        line = {}
    target = target or str(line.get("target") or "")
    state = str(line.get("state") or "").lower()
    status = str(line.get("status") or "").upper()
    reason = _safe_status_reason(line.get("validation_reason") or line.get("reason_code"))
    implementation_marker = str(line.get("implementation_state") or "").lower()
    legacy = (
        reason in {"LEGACY_TARGET_NOT_IMPLEMENTED", "TARGET_NOT_IMPLEMENTED"}
        or state == "not_implemented"
        or line.get("target_implemented") is False
        or implementation_marker == "not_implemented"
    )
    source = "legacy_undeclared" if legacy else "unknown"
    implementation = (
        "unsupported" if legacy or line.get("target_implemented") is False or implementation_marker == "not_implemented"
        else "supported" if line.get("target_implemented") is True or implementation_marker == "supported"
        else "unknown"
    )
    run_state = line.get("run_state")
    if run_state not in STATUS_RUN_STATES:
        run_state = state if state in STATUS_RUN_STATES else "succeeded" if status in {"KNOWN", "UNKNOWN"} and line.get("record_id") else "not_started"
    if legacy:
        result_state = "legacy_missing"
    elif status == "UNKNOWN" and line.get("valid") is True:
        result_state = "unknown_valid"
    elif status == "KNOWN" and line.get("valid") is True:
        result_state = "accepted"
    elif state in {"rejected", "invalid"} or reason in {"MISSING_TARGET", "UNKNOWN_REASON_MISSING", "ALL_PREDICTION_TARGETS_REJECTED"}:
        result_state = "rejected"
    elif state in {"timeout", "failed", "cancelled", "unknown_terminal", "not_returned"}:
        result_state = "not_returned"
    elif status in {"KNOWN", "UNKNOWN"}:
        result_state = "unavailable"
    else:
        result_state = "not_attempted"
    history_status = line.get("history_status")
    if history_status not in STATUS_HISTORY_STATES:
        if target == "NORMAL_WEEKLY":
            history_status = "backfilled" if line.get("forecast_id") or line.get("record_id") else "not_backfilled"
        elif line.get("question_version") or line.get("forecast_id") or line.get("record_id"):
            history_status = "backfilled"
        else:
            history_status = "unknown" if legacy else "not_backfilled"
    projection = {
        "capability": {"implementation": implementation, "source": source},
        "run": {
            "state": run_state,
            "run_id": line.get("run_id") if isinstance(line.get("run_id"), str) else None,
            "attempt_id": line.get("attempt_id") if isinstance(line.get("attempt_id"), str) else None,
            "finished_at": line.get("finished_at") if isinstance(line.get("finished_at"), str) else None,
            "reason_code": reason if run_state in {"timeout", "failed", "cancelled", "unknown_terminal"} else None,
        },
        "result": {"state": result_state, "reason_code": reason, "summary": _status_summary(reason)},
        "history_status": history_status,
        "last_known": _safe_last_known(line.get("last_known")),
    }
    if target == "NORMAL_WEEKLY":
        helper_status = line.get("helper_status") or line.get("baseline_status") or line.get("status") or line.get("state")
        helper_status = str(helper_status or "unknown").lower()
        if helper_status == "expired" or state == "expired" or reason == "EXPIRED":
            calculation_status = "expired"
        elif line.get("unresolved_reason") == "NO_BUSINESS_FULL_ANCHOR":
            calculation_status = "no_business_full_anchor"
        elif line.get("predicted_start") or line.get("predicted_end"):
            calculation_status = "calculated"
        else:
            calculation_status = "unresolved"
        projection["normal"] = {"helper_status": helper_status[:80], "calculation_status": calculation_status}
    return projection


def _safe_status_reason(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.upper()[:120]
    return candidate if candidate and all(char.isalnum() or char in "_.-" for char in candidate) else None


def prediction_status_line_state(line: dict[str, Any], projection: dict[str, Any] | None = None) -> str:
    """Map a dimensioned projection or its boundary-compat view to one line state."""
    has_projection = isinstance(line, dict) and "status_projection" in line
    normalized = projection if projection is not None else normalize_prediction_status_projection(
        line if isinstance(line, dict) else {},
        target=line.get("target") if isinstance(line, dict) else None,
    )
    if normalized["capability"]["source"] == "contract_error":
        return "unavailable"
    target = line.get("target") if isinstance(line, dict) else None
    result_state = normalized["result"]["state"]
    run_state = normalized["run"]["state"]
    reason = _safe_status_reason(
        (line.get("validation_reason") or line.get("reason_code")) if isinstance(line, dict)
        else normalized["result"].get("reason_code")
    ) or normalized["result"].get("reason_code")

    if target == "NORMAL_WEEKLY":
        calculation = normalized.get("normal", {}).get("calculation_status")
        if reason in {"ANCHOR_CHANGED", "CYCLE_CHANGED", "INPUT_CHANGED", "INPUT_SNAPSHOT_CHANGED"}:
            return "stale"
        if calculation == "expired" or reason in {"EXPIRED", "PREDICTION_WINDOW_PASSED_NOT_CONFIRMED"}:
            return "expired"
        if calculation == "calculated":
            return "baseline"
        return "unavailable"

    if not has_projection:
        state = str(line.get("state") or "").lower()
        status = str(line.get("status") or "").upper()
        validity = line.get("validity")
        validity_state = str(
            validity.get("state") if isinstance(validity, dict)
            else validity or line.get("validity_state") or ""
        ).lower()
        raw_valid = line.get("valid") is True
        if run_state in {"pending", "timeout", "failed", "cancelled", "unknown_terminal"}:
            return run_state
        if normalized["result"]["state"] == "legacy_missing" or state == "not_implemented":
            return "not_implemented"
        if state in {"failed", "error", "rejected", "invalid", "stale", "data_stale", "expired", "pending", "partial", "not_backfilled", "waiting_for_verified_history"}:
            return state
        if validity_state in {"expired", "stale", "data_stale", "failed", "error", "rejected", "invalid"}:
            return validity_state
        if reason in {"EXPIRED", "PREDICTION_WINDOW_PASSED_NOT_CONFIRMED"}:
            return "expired"
        if line.get("current_or_last_known") == "last_known" or reason in {"INPUT_CHANGED", "CYCLE_CHANGED", "ANCHOR_CHANGED", "GENERATION_REPLACED"}:
            return "stale"
        if reason == "OUTPUT_AVAILABILITY_PENDING":
            return "pending"
        if reason and reason.startswith(("MODEL_", "REQUEST_", "FAILED", "ERROR")):
            return "failed"
        if reason in {"MISSING_TARGET", "ALL_PREDICTION_TARGETS_REJECTED", "UNKNOWN_REASON_MISSING"}:
            return "rejected"
        if reason == "PREDICTION_NOT_RECORDED" and status not in {"KNOWN", "UNKNOWN"}:
            return "not_implemented"
        if normalized["result"]["state"] == "not_returned":
            return "not_returned"
        if not raw_valid and (status in {"KNOWN", "UNKNOWN"} or state in {"known", "current", "ready", "available", "baseline"}):
            return "rejected" if reason and reason != "VALID" else "invalid"
        if status == "UNKNOWN" or state == "unknown":
            return "unknown" if raw_valid else "invalid"
        if status == "KNOWN" and raw_valid and line.get("current_or_last_known") == "current":
            return "current"
        if state in {"ready", "current", "available", "baseline"} and raw_valid:
            return state
        if normalized["result"]["state"] == "not_attempted":
            return "not_attempted"
        if reason and reason != "VALID":
            return "rejected"
        if not status and not state:
            return "not_implemented"
        return "invalid"

    if run_state in {"pending", "timeout", "failed", "cancelled", "unknown_terminal"}:
        return run_state
    if reason in {"EXPIRED", "PREDICTION_WINDOW_PASSED_NOT_CONFIRMED"}:
        return "expired"
    if reason in {"INPUT_CHANGED", "INPUT_SNAPSHOT_CHANGED", "CYCLE_CHANGED", "ANCHOR_CHANGED", "GENERATION_REPLACED"}:
        return "stale"
    if reason == "OUTPUT_AVAILABILITY_PENDING":
        return "pending"
    if result_state == "not_attempted":
        return "not_attempted"
    if result_state == "legacy_missing":
        return "not_implemented"
    if result_state == "not_returned":
        return "not_returned"
    if result_state == "unavailable":
        return "unavailable"
    if result_state == "rejected":
        return "rejected"
    if isinstance(line, dict) and line.get("current_or_last_known") == "historical":
        return "historical"
    if isinstance(line, dict) and line.get("valid") is not True:
        return "invalid"
    return "unknown" if result_state == "unknown_valid" else "current"


def _status_summary(reason_code: str | None) -> str | None:
    summaries = {
        "LEGACY_TARGET_NOT_IMPLEMENTED": "该旧记录未声明此独立目标。",
        "TARGET_NOT_IMPLEMENTED": "该旧记录未声明此独立目标。",
        "NO_BUSINESS_FULL_ANCHOR": "缺少可用的 Full 锚点，当前无法计算周额度参考。",
        "OUTPUT_AVAILABILITY_PENDING": "目标已记录，输出可用时间尚未得到只读观察证明。",
        "PREDICTION_STATUS_CONTRACT_ERROR": "来源记录与预测契约不一致。",
    }
    return summaries.get(reason_code)


def _safe_last_known(value: Any) -> dict[str, Any] | None:
    if value is None or not _last_known_projection_is_well_formed(value):
        return None
    result = {
        "state": value["state"],
        "forecast_id": value.get("forecast_id") if isinstance(value.get("forecast_id"), str) else None,
        "series_id": value.get("series_id") if isinstance(value.get("series_id"), str) else None,
        "revision": value.get("revision") if isinstance(value.get("revision"), int) and not isinstance(value.get("revision"), bool) else None,
        "origin_judgement_id": value.get("origin_judgement_id") if isinstance(value.get("origin_judgement_id"), int) and not isinstance(value.get("origin_judgement_id"), bool) else None,
        "valid_until": value.get("valid_until") if isinstance(value.get("valid_until"), str) else None,
        "cycle_id": value.get("cycle_id") if isinstance(value.get("cycle_id"), int) and not isinstance(value.get("cycle_id"), bool) else None,
        "reason_code": _safe_status_reason(value.get("reason_code")),
    }
    if value["state"] == "valid" and isinstance(value.get("forecast"), dict):
        result["forecast"] = safe_target_output(value["forecast"])
    return result


def _last_known_projection_is_well_formed(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("state"), str) or value["state"] not in STATUS_LAST_KNOWN_STATES:
        return False
    for key in ("forecast_id", "series_id", "valid_until"):
        if value.get(key) is not None and not isinstance(value.get(key), str):
            return False
    for key in ("revision", "origin_judgement_id", "cycle_id"):
        if value.get(key) is not None and (not isinstance(value.get(key), int) or isinstance(value.get(key), bool)):
            return False
    if value.get("reason_code") is not None and _safe_status_reason(value.get("reason_code")) is None:
        return False
    if value["state"] == "valid":
        return isinstance(value.get("forecast"), dict)
    return "forecast" not in value


def _contract_error_status_projection(line: Any, target: str | None) -> dict[str, Any]:
    result = {
        "capability": {
            "implementation": "unknown",
            "source": "contract_error",
        },
        "run": {
            "state": "unknown_terminal",
            "run_id": None,
            "attempt_id": None,
            "finished_at": None,
            "reason_code": "PREDICTION_STATUS_CONTRACT_ERROR",
        },
        "result": {
            "state": "unavailable",
            "reason_code": "PREDICTION_STATUS_CONTRACT_ERROR",
            "summary": "来源记录与预测契约不一致。",
        },
        "history_status": "unknown",
        "last_known": None,
    }
    if target == "NORMAL_WEEKLY":
        raw_normal = line.get("status_projection", {}).get("normal") if isinstance(line, dict) and isinstance(line.get("status_projection"), dict) else {}
        helper = raw_normal.get("helper_status") if isinstance(raw_normal, dict) else None
        result["normal"] = {
            "helper_status": helper[:80] if isinstance(helper, str) else None,
            "calculation_status": "unresolved",
        }
    return result

PREDICTION_LEDGER_KINDS = frozenset({
    "runtime_identity",
    "forecast_version",
    "run_started",
    "attempt_started",
    "attempt_event",
    "output_committed",
    "output_observed",
    "truth_revision",
    "normal_baseline",
    "recovery_observed",
})

FORECAST_RECORD_KINDS = frozenset({"online", "replay", "baseline", "announcement"})
ARTIFACT_KINDS = frozenset({
    "runtime_identity", "input_snapshot", "input_frame", "text_content",
    "public_prompt", "judge_schema", "request_descriptor", "truth_evidence",
    "processing_output",
})

# Payload field names are shared with the read-only review package builder.
RECORD_PAYLOAD_FIELDS = {
    "runtime_identity": frozenset({"runtime_artifact_ref", "runtime_id", "is_synthetic"}),
    "forecast_version": frozenset({
        "target", "scope", "record_kind", "method", "basis", "previous_id",
        "input_artifact_refs", "forecast", "semantic_hash", "forecast_id",
        "is_synthetic",
        "version_role", "target_refs",
    }),
    "run_started": frozenset({
        "is_synthetic", "stage", "trigger", "forecast", "runtime",
        "input_cutoff_at", "judgement_as_of", "input_artifact_refs",
        "input_snapshot_artifact_ref", "semantic_input_hash", "owner",
        "forecast_id", "revision", "prompt_artifact_ref", "schema_artifact_ref",
        "input_frame_artifact_ref", "selection_mode", "record_kind",
        "processing_operation", "processing_input_hash", "processing_identity",
        "target_refs", "prediction_contract_version",
    }),
    "attempt_started": frozenset({
        "request_artifact_ref", "request_hash", "stage", "retry_of",
        "attempt_started_at", "owner", "declared_model", "is_synthetic",
    }),
    "attempt_event": frozenset({
        "event_type", "http", "failure_terminal", "attempt_finished_at",
        "received_at", "duration_ms", "usage", "usage_source", "reason_code",
        "error_type", "request_hash", "operation", "result_version_hash",
        "output_artifact_ref", "artifact_refs", "source_status", "source_run_id",
        "source_attempt_id", "source_request_hash", "reason_summary",
        "output_id", "output_available_at", "publication_status",
        "structured_output", "input_version_delta",
        "observed_at", "clock_anomaly", "time_limitation",
        "declared_model", "reported_model", "reported_model_source",
        "reported_model_missing_reason", "is_synthetic",
    }),
    "output_committed": frozenset({
        "output_id", "structured_output", "schema", "judge_reference",
        "accepted_attempt_id", "validation", "forecast_id", "series_id",
        "revision", "output_available_at", "is_synthetic",
        "target_refs", "target_outputs", "prediction_validation", "prediction_contract_version",
    }),
    "output_observed": frozenset({
        "output_id", "observed_at", "source", "clock_anomaly", "time_limitation",
        "is_synthetic",
    }),
    "truth_revision": frozenset({
        "event_id", "true_fields", "source_event_id", "revision",
        "previous_revision", "evidence_refs", "reason", "source_event_snapshot_hash",
        "source_event_snapshot_ref", "association_status",
        "is_synthetic",
    }),
    "normal_baseline": frozenset({
        "target", "scope", "record_kind", "method", "basis", "previous_id",
        "input_artifact_refs", "forecast", "semantic_hash",
        "forecast_id", "series_id", "revision", "target_outputs", "target_refs",
        "is_synthetic", "output_id", "output_available_at", "anchor_event_id",
    }),
    "recovery_observed": frozenset({
        "observed_at", "owner_status", "terminal_status", "actual_finished_at",
    }),
}

PAYLOAD_ARTIFACT_REF_FIELDS = frozenset({
    "runtime_artifact_ref", "input_artifact_refs", "request_artifact_ref",
    "prompt_artifact_ref", "schema_artifact_ref", "input_frame_artifact_ref",
    "input_snapshot_artifact_ref", "judge_schema_artifact_ref",
    "public_prompt_artifact_ref", "evidence_artifact_refs", "evidence_refs",
    "output_artifact_ref", "source_event_snapshot_ref", "artifact_refs",
})


@dataclass(frozen=True)
class RunRef:
    run_id: str
    series_id: str
    input_artifact_id: str
    input_hash: str
    input_cutoff_at: str
    judgement_as_of: str | None
    input_artifact_refs: tuple[dict[str, str], ...]
    prompt_artifact_ref: dict[str, str] | None
    schema_artifact_ref: dict[str, str] | None
    input_frame_artifact_ref: dict[str, str]
    forecast_id: str
    revision: int
    semantic_hash: str
    is_synthetic: bool | None = None
    target_refs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessingRunRef:
    run_id: str
    stage: str
    input_hash: str
    input_artifact_refs: tuple[dict[str, str], ...]
    input_frame_artifact_ref: dict[str, str]
    prompt_artifact_ref: dict[str, str] | None
    schema_artifact_ref: dict[str, str] | None
    is_synthetic: bool | None = None


@dataclass(frozen=True)
class AttemptRef:
    attempt_id: str
    run_id: str
    request_artifact_id: str
    request_hash: str
    attempt_started_at: str
    owner_id: str


@dataclass(frozen=True)
class OutputRef:
    output_id: str
    judgement_id: int
    run_id: str
    attempt_id: str
    series_id: str
    forecast_id: str
    revision: int


class LateInputRejected(ValueError):
    """The request finished against a snapshot that is no longer admissible."""


_ACTIVE_TRACKER: ContextVar[Any | None] = ContextVar("prediction_ledger_tracker", default=None)


class AttemptTracker:
    """Per-request callback shared with the existing HTTP client, including retries."""

    def __init__(
        self, ledger: PredictionLedger, run_id: str, request_descriptor: dict[str, Any],
        owner: dict[str, Any], *, is_synthetic: bool | None = None,
    ):
        self.ledger = ledger
        self.run_id = run_id
        self.request_descriptor = request_descriptor
        self.owner = owner
        self.is_synthetic = is_synthetic if isinstance(is_synthetic, bool) else None
        self.attempts: list[AttemptRef] = []

    @property
    def latest_attempt_id(self) -> str | None:
        return self.attempts[-1].attempt_id if self.attempts else None

    def begin_attempt(self, retry_of: str | None = None) -> AttemptRef:
        ref = self.ledger.begin_send(
            self.run_id,
            self.request_descriptor,
            retry_of=retry_of if retry_of is not None else self.latest_attempt_id,
            owner=self.owner,
            is_synthetic=self.is_synthetic,
        )
        self.attempts.append(ref)
        return ref

    def prepare_request(self, request_body: dict[str, Any]) -> None:
        """Hash the exact outgoing body while retaining only safe metadata."""
        request_hash = sha256_json(request_body)
        self.request_descriptor = {
            **self.request_descriptor,
            "request_hash": request_hash,
            "model": request_body.get("model"),
            "declared_model": request_body.get("model") if isinstance(request_body.get("model"), str) else None,
            "temperature": request_body.get("temperature"),
            "response_format": copy.deepcopy(request_body.get("response_format")),
            "message_count": len(request_body.get("messages") or []),
        }

    def append_event(self, attempt_id: str, event_type: str, **payload: Any) -> str:
        return self.ledger.append_attempt_event(self.run_id, attempt_id, event_type, **payload)

    def record_processing_output(self, operation: str, output: dict[str, Any]) -> str:
        if self.latest_attempt_id is None:
            raise ValueError("processing output has no durable attempt")
        return self.ledger.record_processing_output(self, operation, output)


def current_attempt_tracker() -> AttemptTracker | None:
    return _ACTIVE_TRACKER.get()


@contextmanager
def active_attempt_tracker(tracker: AttemptTracker) -> Iterator[None]:
    token = _ACTIVE_TRACKER.set(tracker)
    try:
        yield
    finally:
        _ACTIVE_TRACKER.reset(token)


def _wall_clock_order_fields(*timestamps: str | None) -> dict[str, str]:
    """Annotate reversed wall times without changing or sorting their values."""
    present = [stamp for stamp in timestamps if stamp is not None]
    if len(present) != len(timestamps):
        return {"time_limitation": "wall_clock_order_evidence_incomplete"}
    try:
        normalized = [utc_text(stamp) for stamp in present]
    except (TypeError, ValueError):
        return {"time_limitation": "wall_clock_order_comparison_unavailable"}
    if any(right < left for left, right in zip(normalized, normalized[1:])):
        return {
            "clock_anomaly": "wall_clock_reversed",
            "time_limitation": "timestamps_retained_without_ordering",
        }
    return {}


class PredictionLedger:
    """Append-only prediction journal. Implemented over the existing Database."""

    def __init__(self, database, *, owner: dict[str, Any] | None = None):
        self.database = database
        self.owner = dict(owner or {})

    @contextmanager
    def _read_connection(self):
        connection = sqlite3.connect(Path(self.database.path).resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            with self.database.using_connection(connection):
                yield connection
        finally:
            connection.rollback()
            connection.close()

    def _restore_texts(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._restore_texts(child) for child in value]
        if not isinstance(value, dict):
            return value
        if "artifact_ref" in value and "source_ref" in value:
            return self._load_artifact(value["artifact_ref"]["artifact_id"])["text"]
        return {key: self._restore_texts(child) for key, child in value.items()}

    def _fresh_judge_context(self, connection, as_of, selection_mode):
        with self.database.using_connection(connection):
            fresh = self.database.judgement_context(as_of=as_of)
            fresh["pending_inputs"] = self.database.judge_pending_inputs(include_deferred=True) if selection_mode == "online" else []
            self.database.refresh_input_snapshot(fresh)
            return fresh

    def record_normal_baseline(self, last_full_reset, *, as_of=None, is_synthetic=False, record_kind="baseline"):
        """Pipeline-only producer. Dedup by immutable anchor facts, never by heartbeat."""
        baseline = next_reset_baseline(last_full_reset, as_of=as_of)
        if not last_full_reset or not (baseline["predicted_start"] or baseline["predicted_end"]):
            return None
        anchor = self._semantic_facts(copy.deepcopy(last_full_reset))
        semantic_hash = sha256_json({"anchor": anchor, "basis": "user_full_plus_7d", "record_kind": record_kind})
        series_id = "series-" + sha256_json({"target": "NORMAL_WEEKLY", "scope": anchor.get("scope", "unknown"), "record_kind": record_kind})[:32]
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT payload_json FROM prediction_ledger WHERE kind='normal_baseline' AND idempotency_key=?", ("normal_baseline:" + series_id + ":" + semantic_hash,)).fetchone()
            if existing:
                return json.loads(existing[0])
            previous = connection.execute("SELECT forecast_id,revision FROM prediction_ledger WHERE kind='normal_baseline' AND series_id=? ORDER BY seq DESC LIMIT 1", (series_id,)).fetchone()
            forecast_id = str(uuid.uuid4())
            ref = {"forecast_id": forecast_id, "series_id": series_id, "revision": int(previous["revision"]) + 1 if previous else 1,
                   "previous_id": previous["forecast_id"] if previous else None}
            anchor_ref = self._put_artifact(connection, "input_frame", {"normal_anchor": anchor, "is_synthetic": is_synthetic})
            payload = {**ref, "target": "NORMAL_WEEKLY", "scope": anchor.get("scope", "unknown"), "record_kind": record_kind,
                       "method": None, "basis": "user_full_plus_7d", "forecast": baseline, "semantic_hash": semantic_hash,
                       "input_artifact_refs": [anchor_ref], "is_synthetic": is_synthetic, "output_id": "normal-" + forecast_id,
                       "anchor_event_id": anchor.get("id"), "output_available_at": None,
                       "target_refs": {"NORMAL_WEEKLY": ref}, "target_outputs": {"NORMAL_WEEKLY": baseline}}
            self._append_record(connection, "normal_baseline", payload, series_id=series_id, forecast_id=forecast_id,
                                revision=ref["revision"], event_id=anchor.get("id"), idempotency_key="normal_baseline:" + series_id + ":" + semantic_hash)
        # A real post-commit read proves only an availability upper bound.
        try:
            with self._read_connection() as connection:
                row = connection.execute("SELECT recorded_at FROM prediction_ledger WHERE kind='normal_baseline' AND forecast_id=?", (forecast_id,)).fetchone()
                if row is None:
                    raise RuntimeError("Normal baseline publication missing")
            observed = utc_text()
            with self.database.connect() as connection:
                self._append_record(connection, "output_observed", {"output_id": payload["output_id"], "observed_at": observed,
                                    "source": OUTPUT_AVAILABLE_SOURCE, "is_synthetic": is_synthetic,
                                    **_wall_clock_order_fields(row["recorded_at"], observed)},
                                    series_id=series_id, forecast_id=forecast_id, revision=ref["revision"], occurred_at=observed)
        except Exception as error:
            # No recovery/GET backfill and no retry of a model to obtain an observation.
            try:
                with self.database.connect() as connection:
                    self._append_record(connection, "attempt_event", {"event_type": "output_observation_failed",
                        "output_id": payload["output_id"], "output_available_at": None, "publication_status": "committed_unobserved",
                        "reason_code": "NORMAL_OBSERVATION_FAILED", "error_type": type(error).__name__,
                        "is_synthetic": is_synthetic}, series_id=series_id, forecast_id=forecast_id, revision=ref["revision"])
            except Exception:
                # The null availability remains an explicit limitation when even
                # the independent fault marker cannot be persisted.
                pass
        return payload

    @staticmethod
    def _history_lines(record, *, target=None, series_id=None, run=None, observation=None):
        """Output-only safe DTOs. Question identity never supplies method or dates."""
        payload, run = record['payload'], run or {}
        modern = payload.get('prediction_contract_version') == PREDICTION_CONTRACT_VERSION
        normal = record['kind'] == 'normal_baseline'
        targets = ('NORMAL_WEEKLY',) if normal else PREDICTION_TARGETS if modern else ('EXTRA_FULL',)
        lines = []
        for name in targets:
            ref = (payload.get('target_refs') or {}).get(name) or {
                'forecast_id': record.get('forecast_id'), 'series_id': record.get('series_id'),
                'revision': record.get('revision'), 'previous_id': None,
            }
            if target is not None and name != target or series_id is not None and ref.get('series_id') != series_id:
                continue
            child = payload.get('forecast') or {} if normal else (payload.get('target_outputs') or {}).get(name) or {}
            accepted = normal or bool(child.get('validation', {}).get('valid'))
            reason = 'LEGACY_TARGET_NOT_IMPLEMENTED' if not (normal or modern) else 'VALID' if accepted else child.get('validation', {}).get('reason') or 'MISSING_TARGET'
            available = observation if accepted else None
            # A rejected child contributes its validation summary only; rejected
            # form/date/output identifiers are never projected as a forecast.
            fields = safe_target_output(child if accepted else {})
            for key in ('anchor_limitation', 'anchor_time_basis', 'basis', 'baseline_status', 'expiry_basis', 'time_form'):
                if isinstance(child.get(key), str):
                    fields[key] = child[key][:500]
            valid = bool(accepted and available and not available.get('clock_anomaly'))
            state = 'not_implemented' if not (normal or modern) else 'rejected' if not accepted else 'pending' if not available else 'invalid' if not valid else 'baseline' if normal else 'unknown' if child.get('status') == 'UNKNOWN' else 'known'
            structured = payload.get('structured_output') or {}
            line = {**fields, **ref, 'target': name, 'status': 'KNOWN' if normal else child.get('status'),
                'state': state, 'valid': valid, 'validation_reason': reason if not accepted else 'OUTPUT_AVAILABILITY_PENDING' if not available else 'CLOCK_ANOMALY' if not valid else 'VALID',
                'prediction_form': child.get('prediction_form') or fields.get('prediction_form') or 'unknown',
                'question_revision': ref.get('revision'), 'question_version': ref.get('forecast_id'),
                'output_revision': ref.get('revision') if normal else child.get('output_revision'),
                'target_output_id': payload.get('output_id') if normal else child.get('target_output_id'),
                'record_id': record['record_id'], 'ledger_seq': record['seq'], 'run_id': record.get('run_id'),
                'origin_judgement_id': record.get('judgement_id'), 'record_kind': payload.get('record_kind') or run.get('record_kind'),
                'is_synthetic': payload.get('is_synthetic'), 'current_or_last_known': 'historical',
                'output_available_at': available.get('observed_at') if available else None,
                'output_available_at_source': available.get('source') if available else None,
                'clock_anomaly': available.get('clock_anomaly') if available else None,
                'updated_at': record['recorded_at'], 'updated_at_source': 'ledger_recorded_at',
                'judged_at': structured.get('created_at'), 'valid_until': structured.get('valid_until'),
                'health_state': 'not_applicable' if normal else str(structured.get('data_health') or 'unknown').lower(),
                'reason': fields.get('reason') or reason}
            if normal:
                helper_status = str(child.get('baseline_status') or child.get('status') or state).lower()
                calculation_status = 'expired' if helper_status == 'expired' else 'calculated' if child.get('predicted_start') or child.get('predicted_end') else 'no_business_full_anchor' if child.get('unresolved_reason') == 'NO_BUSINESS_FULL_ANCHOR' else 'unresolved'
                source, implementation = 'ledger_v2', 'supported'
                normal_projection = {'helper_status': helper_status, 'calculation_status': calculation_status}
            else:
                source, implementation = ('ledger_v2', 'supported') if modern else ('legacy_undeclared', 'supported' if name == 'EXTRA_FULL' else 'unsupported')
                normal_projection = None
            result_state = 'accepted' if accepted else 'rejected'
            if accepted and child.get('status') == 'UNKNOWN':
                result_state = 'unknown_valid'
            line['status_projection'] = normalize_prediction_status_projection({
                'target': name,
                'status_projection': {
                    'capability': {'implementation': implementation, 'source': source},
                    'run': {'state': 'not_started' if normal else 'succeeded',
                            'run_id': None if normal else record.get('run_id'),
                            'attempt_id': None if normal else record.get('attempt_id') or payload.get('accepted_attempt_id'),
                            'finished_at': None, 'reason_code': None},
                    'result': {'state': result_state, 'reason_code': reason, 'summary': _status_summary(_safe_status_reason(reason))},
                    'history_status': 'backfilled',
                    'last_known': None,
                    **({'normal': normal_projection} if normal_projection is not None else {}),
                },
            }, target=name)
            lines.append(line)
        return lines

    def prediction_history(self, target=None, series_id=None, limit=100):
        if target is not None and target not in ALL_PREDICTION_TARGETS:
            raise ValueError("unsupported prediction target")
        limit = max(1, min(int(limit), 1000))
        def decode(rows):
            return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]
        with self._read_connection() as connection:
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prediction_ledger'").fetchone()
            if not exists:
                return {"version": PREDICTION_API_VERSION, "items": [], "forecasts": [], "attempts": [], "count": 0, "truncated": False, "limitation": "LEGACY_LEDGER_NOT_PRESENT"}
            params, clauses = [], []
            if target:
                clauses.append("(json_extract(payload_json,'$.target')=? OR json_type(payload_json,?) IS NOT NULL OR (?='EXTRA_FULL' AND kind IN ('output_committed','run_started') AND json_type(payload_json,'$.target_refs') IS NULL))")
                params.extend([target, '$.target_refs.' + target, target])
            if series_id:
                clauses.append("(series_id=? OR json_extract(payload_json,'$.target_refs.BANKED.series_id')=?)")
                params.extend([series_id, series_id])
            suffix = " AND " + " AND ".join(clauses) if clauses else ""
            output_where = "kind IN ('output_committed','normal_baseline')" + suffix
            count = connection.execute("SELECT COUNT(*) FROM prediction_ledger WHERE " + output_where, params).fetchone()[0]
            outputs = decode(reversed(connection.execute("SELECT * FROM prediction_ledger WHERE " + output_where + " ORDER BY seq DESC LIMIT ?", [*params, limit]).fetchall()))
            first = connection.execute("SELECT * FROM prediction_ledger WHERE " + output_where + " ORDER BY seq LIMIT 1", params).fetchone()
            last = connection.execute("SELECT * FROM prediction_ledger WHERE " + output_where + " ORDER BY seq DESC LIMIT 1", params).fetchone()
            boundary_outputs = decode([row for row in (first, last) if row is not None])
            forecasts = decode(reversed(connection.execute("SELECT * FROM prediction_ledger WHERE kind IN ('forecast_version','normal_baseline')" + suffix + " ORDER BY seq DESC LIMIT ?", [*params, limit]).fetchall()))
            run_rows = connection.execute("SELECT * FROM prediction_ledger WHERE kind='run_started' AND json_extract(payload_json,'$.stage')='radar_judge'" + suffix + " ORDER BY seq DESC LIMIT ?", [*params, limit]).fetchall()
            run_ids = sorted({row['run_id'] for row in run_rows} | {item['run_id'] for item in [*outputs, *boundary_outputs] if item['run_id']})
            attempts, attempt_count = [], 0
            if run_ids:
                placeholders = ','.join('?' for _ in run_ids)
                where = "run_id IN (" + placeholders + ") AND kind IN ('run_started','attempt_started','attempt_event','recovery_observed')"
                attempt_count = connection.execute("SELECT COUNT(*) FROM prediction_ledger WHERE " + where, run_ids).fetchone()[0]
                attempts = decode(reversed(connection.execute("SELECT * FROM prediction_ledger WHERE " + where + " ORDER BY seq DESC LIMIT ?", [*run_ids, min(4000, limit * 32)]).fetchall()))
            observations = []
            for output_id in sorted({item['payload']['output_id'] for item in [*outputs, *boundary_outputs]}):
                observed = connection.execute("SELECT * FROM prediction_ledger WHERE kind='output_observed' AND json_extract(payload_json,'$.output_id')=? ORDER BY seq LIMIT 1", (output_id,)).fetchone()
                if observed is not None:
                    observations.extend(decode([observed]))
            total_count = 0
            for name in (target,) if target else ALL_PREDICTION_TARGETS:
                if name == 'NORMAL_WEEKLY':
                    where, args = "kind='normal_baseline'", []
                    if series_id is not None:
                        where += ' AND series_id=?'
                        args.append(series_id)
                else:
                    path = '$.target_refs.' + name
                    where = "kind='output_committed' AND (json_type(payload_json,?) IS NOT NULL"
                    args = [path]
                    if name == 'EXTRA_FULL':
                        where += " OR json_type(payload_json,'$.target_refs') IS NULL"
                    where += ')'
                    if series_id is not None:
                        where += ' AND ' + ('series_id=?' if name == 'EXTRA_FULL' else 'json_extract(payload_json,?)=?')
                        args.extend([series_id] if name == 'EXTRA_FULL' else [path + '.series_id', series_id])
                total_count += connection.execute('SELECT count(*) FROM prediction_ledger WHERE ' + where, args).fetchone()[0]
        observation_by_output = {row['payload']['output_id']: row['payload'] for row in observations}
        runs = {row['run_id']: row['payload'] for row in [*decode(run_rows), *attempts] if row['kind'] == 'run_started'}
        def flat(record):
            return self._history_lines(record, target=target, series_id=series_id, run=runs.get(record['run_id']),
                                       observation=observation_by_output.get(record['payload']['output_id']))
        items = [item for record in outputs for item in flat(record)][-limit:]
        first_items = flat(boundary_outputs[0]) if boundary_outputs else []
        last_items = flat(boundary_outputs[-1]) if boundary_outputs else []
        outputs_by_run = {row['run_id']: row for row in outputs}
        attempt_groups = {}
        for row in attempts:
            if row['kind'] != 'run_started':
                attempt_groups.setdefault((row['run_id'], row['attempt_id'] or row['record_id']), []).append(row)
        safe_attempts = []
        for (run_id, attempt_id), events in attempt_groups.items():
            run = runs.get(run_id) or {}
            start = next((row['payload'] for row in events if row['kind'] == 'attempt_started'), {})
            terminal = next((row['payload'] for row in reversed(events) if row['kind'] == 'recovery_observed'
                             or row['payload'].get('event_type') in ATTEMPT_TERMINAL_EVENTS), {})
            refs = run.get('target_refs') or {'EXTRA_FULL': {'series_id': events[0]['series_id']}}
            for name, ref in refs.items():
                if target and name != target or series_id and ref.get('series_id') != series_id:
                    continue
                output = (outputs_by_run.get(run_id) or {}).get('payload') or {}
                child = (output.get('target_outputs') or {}).get(name) or {}
                safe_attempts.append({'target': name, 'series_id': ref.get('series_id'), 'run_id': run_id,
                    'attempt_id': attempt_id, 'attempt_number': None,
                    'started_at': start.get('attempt_started_at'), 'attempted_at': start.get('attempt_started_at'),
                    'finished_at': terminal.get('attempt_finished_at'),
                    'state': terminal.get('event_type') or 'recovery_observed' if terminal else 'pending',
                    'reason_code': terminal.get('reason_code'), 'reason': terminal.get('reason_summary'),
                    'output_status': child.get('status') if child.get('validation', {}).get('valid') else 'rejected' if child else None})
        safe_forecasts = [{key: row['payload'].get(key) for key in ('target', 'scope', 'method', 'version_role', 'facts_digest', 'semantic_hash')}
                          | {key: row.get(key) for key in ('forecast_id', 'series_id', 'revision')} for row in forecasts]
        return {"version": PREDICTION_API_VERSION, "item_schema": "prediction-history-line-v1",
                "attempts_schema": "prediction-attempt-v1", "capabilities": {"history_lines": True},
                "items": items, "forecasts": safe_forecasts, "attempts": safe_attempts,
                "count": total_count, "total_count": total_count, "source_output_count": count,
                "truncated": total_count > len(items), "attempt_count": len(safe_attempts),
                "attempts_truncated": attempt_count > len(attempts), "first_record_id": first['record_id'] if first else None,
                "last_record_id": last['record_id'] if last else None,
                "first_item": first_items[0] if first_items else None, "last_item": last_items[-1] if last_items else None,
                "first_items": first_items, "last_items": last_items,
                "order_basis": "append_sequence_not_proven_temporal_or_pre_event_order"}

    def prediction_lines(self, judgement, *, as_of=None):
        """Pure RO projection, including legacy/null and post-commit pending windows."""
        now = utc_text(as_of)
        with self._read_connection() as connection:
            has_ledger = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prediction_ledger'").fetchone() is not None
            rows = []
            latest_run_row = None
            latest_run_records = []
            last_known_rows = {}
            if has_ledger:
                latest_run_row = connection.execute(
                    "SELECT * FROM prediction_ledger WHERE kind='run_started' AND json_extract(payload_json,'$.stage')='radar_judge' ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                if latest_run_row:
                    rows.append(latest_run_row)
                    latest_run_records = connection.execute(
                        "SELECT * FROM prediction_ledger WHERE run_id=? AND kind IN ('attempt_started','attempt_event','recovery_observed') ORDER BY seq DESC LIMIT 128",
                        (latest_run_row['run_id'],),
                    ).fetchall()
                    rows.extend(latest_run_records)
                current_row = connection.execute("SELECT * FROM prediction_ledger WHERE kind='output_committed' AND judgement_id=? ORDER BY seq DESC LIMIT 1", (judgement.get('id') if judgement else None,)).fetchone()
                if current_row:
                    rows.append(current_row)
                    current_refs = json.loads(current_row['payload_json']).get('target_refs') or {}
                    for target in PREDICTION_TARGETS:
                        ref = current_refs.get(target)
                        if not ref:
                            continue
                        series_predicate = "json_extract(payload_json,'$.target_refs.BANKED.series_id')" if target == 'BANKED' else 'series_id'
                        fallback = connection.execute("SELECT * FROM prediction_ledger WHERE kind='output_committed' AND " + series_predicate + "=? AND seq<? AND json_extract(payload_json,?)=1 ORDER BY seq DESC LIMIT 1", (ref['series_id'], current_row['seq'], '$.target_outputs.' + target + '.validation.valid')).fetchone()
                        if fallback:
                            rows.append(fallback)
                if latest_run_row:
                    latest_run_payload = json.loads(latest_run_row['payload_json'])
                    latest_refs = latest_run_payload.get('target_refs') or {}
                    for target in PREDICTION_TARGETS:
                        ref = latest_refs.get(target)
                        if not isinstance(ref, dict) or not isinstance(ref.get('series_id'), str):
                            continue
                        series_predicate = "json_extract(payload_json,'$.target_refs." + target + ".series_id')=?"
                        parameters = [ref['series_id']]
                        if target == 'EXTRA_FULL':
                            series_predicate = "(json_extract(payload_json,'$.target_refs.EXTRA_FULL.series_id')=? OR (json_type(payload_json,'$.target_refs') IS NULL AND series_id=?))"
                            parameters.append(ref['series_id'])
                        last_known_rows[target] = connection.execute(
                            "SELECT * FROM prediction_ledger WHERE kind='output_committed' AND " + series_predicate
                            + " AND seq<? AND json_extract(payload_json,?)=1 ORDER BY seq DESC LIMIT 1",
                            [*parameters, latest_run_row['seq'], '$.target_outputs.' + target + '.validation.valid'],
                        ).fetchone()
                        if last_known_rows[target]:
                            rows.append(last_known_rows[target])
                    current_run_output = connection.execute(
                        "SELECT * FROM prediction_ledger WHERE kind='output_committed' AND run_id=? ORDER BY seq DESC LIMIT 1",
                        (latest_run_row['run_id'],),
                    ).fetchone()
                    if current_run_output:
                        rows.append(current_run_output)
                normal_row = connection.execute("SELECT * FROM prediction_ledger WHERE kind='normal_baseline' AND json_extract(payload_json,'$.record_kind')='baseline' ORDER BY seq DESC LIMIT 1").fetchone()
                if normal_row:
                    rows.append(normal_row)
                run_ids = sorted({row['run_id'] for row in rows if row['run_id']})
                output_ids = sorted({json.loads(row['payload_json']).get('output_id') for row in rows
                                     if row['kind'] in {'output_committed', 'normal_baseline'}
                                     and json.loads(row['payload_json']).get('output_id')})
                if run_ids:
                    rows.extend(connection.execute("SELECT * FROM prediction_ledger WHERE kind='run_started' AND run_id IN (" + ','.join('?' for _ in run_ids) + ") ORDER BY seq LIMIT ?", [*run_ids, len(run_ids)]).fetchall())
                for output_id in output_ids:
                    observation = connection.execute("SELECT * FROM prediction_ledger WHERE kind='output_observed' AND json_extract(payload_json,'$.output_id')=? ORDER BY seq LIMIT 1", (output_id,)).fetchone()
                    if observation:
                        rows.append(observation)
            rows.sort(key=lambda row: row['seq'])
            records = [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]
            observations = {item["payload"]["output_id"]: item["payload"] for item in records if item["kind"] == "output_observed" and item["payload"].get("observed_at") and item["payload"]["observed_at"] <= now}
            runs = {item["run_id"]: item["payload"] for item in records if item["kind"] == "run_started"}
            outputs = [item for item in records if item["kind"] == "output_committed"]
            lines = {}
            for target in PREDICTION_TARGETS:
                current = next((item for item in reversed(outputs) if judgement and item["judgement_id"] == judgement.get("id")), None)
                child = (current["payload"].get("target_outputs") or {}).get(target) if current else None
                last_failure = None
                if not child or not child.get("validation", {}).get("valid"):
                    last_failure = child.get("validation", {}).get("reason") if child else "LEGACY_TARGET_NOT_IMPLEMENTED"
                    # Only earlier publications can be a last-known fallback.
                    prior = [item for item in outputs if current and item["seq"] < current["seq"]]
                    current = next((item for item in reversed(prior) if (item["payload"].get("target_outputs") or {}).get(target, {}).get("validation", {}).get("valid")), None)
                    child = (current["payload"].get("target_outputs") or {}).get(target) if current else child
                ref = (current["payload"].get("target_refs") or {}).get(target, {}) if current else {}
                observation = observations.get(current["payload"]["output_id"]) if current and child and child.get("validation", {}).get("valid") else None
                origin = self.database.get_judgement(current["judgement_id"]) if current else None
                common = self.database.validate_judgement(origin, at=as_of) if origin else {"valid": False, "reason": last_failure or "PREDICTION_NOT_RECORDED"}
                run = runs.get(current["run_id"], {}) if current else {}
                validation_reason = last_failure or (child or {}).get("validation", {}).get("reason") or common["reason"]
                valid = bool(child and child.get("validation", {}).get("valid") and common["valid"] and observation and not last_failure and not observation.get("clock_anomaly"))
                if child and child.get("lifecycle") in {"cancelled", "completed"}:
                    valid, validation_reason = False, "PLAN_" + child["lifecycle"].upper()
                elif not common["valid"]:
                    validation_reason = common["reason"]
                elif not observation:
                    validation_reason = "OUTPUT_AVAILABILITY_PENDING"
                elif observation.get('clock_anomaly'):
                    validation_reason = 'CLOCK_ANOMALY'
                upper = None
                if child:
                    form = child.get('resolved_prediction_form') or child.get('prediction_form')
                    upper = child.get('predicted_start') if form == 'point' else child.get('predicted_end') if form in {'range', 'date', 'end_only'} else None
                if valid and child.get("status") == "KNOWN" and upper and upper < now:
                    valid, validation_reason = False, "PREDICTION_WINDOW_PASSED_NOT_CONFIRMED"
                defaults = {key: None for key in ('forecast_id','series_id','revision','previous_id','method','scope','predicted_start','predicted_end','prediction_form','source_timezone','precision','time_basis','expression','relative_anchor_at','unresolved_reason')}
                lines[target] = {**defaults, **(child or {}), **ref, "target": target, "status": (child or {}).get("status"),
                    "origin_judgement_id": current["judgement_id"] if current else None,
                    "run_id": current["run_id"] if current else None,
                    "attempt_id": current["attempt_id"] if current else None,
                    "input_snapshot": run.get("input_snapshot_artifact_ref"), "runtime": run.get("runtime"),
                    "prompt_artifact_ref": run.get("prompt_artifact_ref"), "schema_artifact_ref": run.get("schema_artifact_ref"),
                    "record_kind": run.get("record_kind"), "is_synthetic": run.get("is_synthetic"),
                    "output_available_at": observation.get("observed_at") if observation else None,
                    "output_available_at_source": observation.get("source") if observation else None,
                    "clock_anomaly": observation.get("clock_anomaly") if observation else None,
                    "time_limitation": observation.get("time_limitation") if observation else None,
                    "state": "not_implemented" if last_failure == 'LEGACY_TARGET_NOT_IMPLEMENTED' else None,
                    "updated_at": current['recorded_at'] if current else None, "updated_at_source": 'ledger_recorded_at' if current else None,
                    "judged_at": origin.get('created_at') if origin else None, "valid_until": origin.get('valid_until') if origin else None,
                    "question_revision": ref.get('revision'), "question_version": ref.get('forecast_id'),
                    "valid": valid, "validation_reason": validation_reason,
                    "current_or_last_known": "current" if valid else "last_known" if child and child.get('validation', {}).get('valid') else "unavailable"}
            normal = next((item for item in reversed(records) if item["kind"] == "normal_baseline" and item["payload"].get("record_kind") == "baseline"), None)
            if normal:
                payload = normal["payload"]
                baseline = dict(payload["forecast"])
                observation = observations.get(payload["output_id"])
                current_anchor = self.database.judgement_context(as_of=as_of, include_previous=False).get('last_full_reset')
                anchor_row = connection.execute("SELECT payload_json FROM prediction_artifacts WHERE id=?", (payload['input_artifact_refs'][0]['artifact_id'],)).fetchone()
                recorded_anchor = json.loads(anchor_row[0]).get('normal_anchor') if anchor_row else None
                # Expiry is a derivative of the same immutable anchor, not a
                # second +7 implementation or a new heartbeat version.
                expired = next_reset_baseline(recorded_anchor, as_of=as_of)["status"] == "expired"
                anchor_changed = not current_anchor or self._semantic_facts(current_anchor) != recorded_anchor
                unknown_upper = baseline.get('expiry_basis') == 'upper_bound_unknown'
                valid = not expired and not anchor_changed and not unknown_upper and bool(observation) and not observation.get('clock_anomaly')
                reason = 'ANCHOR_CHANGED' if anchor_changed else 'EXPIRED' if expired else 'ANCHOR_UPPER_BOUND_UNKNOWN' if unknown_upper else 'OUTPUT_AVAILABILITY_PENDING' if not observation else 'CLOCK_ANOMALY' if observation.get('clock_anomaly') else 'VALID'
                lines["NORMAL_WEEKLY"] = {**baseline, **payload["target_refs"]["NORMAL_WEEKLY"],
                    "target": "NORMAL_WEEKLY", "status": "KNOWN", "baseline_status": "expired" if expired else "baseline",
                    "scope": payload.get("scope"), "input_snapshot": payload.get("input_artifact_refs"),
                    "origin_judgement_id": None, "runtime": None, "prompt_artifact_ref": None,
                    "output_available_at": observation.get("observed_at") if observation else None,
                    "output_available_at_source": observation.get("source") if observation else None,
                    "updated_at": normal['recorded_at'], "updated_at_source": 'ledger_recorded_at',
                    "valid_until": baseline.get('predicted_end') or baseline.get('predicted_start') if baseline.get('expiry_basis') != 'upper_bound_unknown' else None,
                    "question_revision": payload['revision'], "question_version": payload['forecast_id'],
                    "is_synthetic": payload.get("is_synthetic"), "valid": valid,
                    "validation_reason": reason, "current_or_last_known": "current" if valid else "last_known"}
            else:
                baseline = next_reset_baseline(self.database.last_full_reset(as_of=as_of), as_of=as_of)
                lines["NORMAL_WEEKLY"] = {**baseline, "forecast_id": None, "series_id": None, "revision": None,
                    "previous_id": None, "origin_judgement_id": None, "output_available_at": None,
                    "updated_at": None, "updated_at_source": None, "valid_until": None,
                    "output_available_at_source": None, "valid": False, "validation_reason": "NORMAL_VERSION_NOT_RECORDED",
                    "current_or_last_known": "unavailable"}
        latest_run = next((item for item in reversed(records)
                           if latest_run_row and item['record_id'] == latest_run_row['record_id']), None)
        latest_run_payload = latest_run['payload'] if latest_run else {}
        latest_run_id = latest_run.get('run_id') if latest_run else None
        latest_run_attempts = [item for item in records if latest_run_id and item['run_id'] == latest_run_id
                               and item['kind'] == 'attempt_started']
        latest_attempt = latest_run_attempts[-1] if latest_run_attempts else None
        latest_attempt_id = latest_attempt.get('attempt_id') if latest_attempt else None
        terminal_events = [item for item in records if latest_run_id and item['run_id'] == latest_run_id
                           and item['kind'] in {'attempt_event', 'recovery_observed'}
                           and (item.get('attempt_id') == latest_attempt_id if latest_attempt_id else item.get('attempt_id') is None)
                           and (item['kind'] == 'recovery_observed'
                                or item['payload'].get('event_type') in ATTEMPT_TERMINAL_EVENTS)]
        latest_terminal = terminal_events[-1] if terminal_events else None
        terminal_type = latest_terminal['payload'].get('event_type') if latest_terminal else None
        if latest_terminal and latest_terminal['kind'] == 'recovery_observed':
            run_state = 'unknown_terminal'
        elif terminal_type == 'success':
            run_state = 'succeeded'
        elif terminal_type == 'timeout':
            run_state = 'timeout'
        elif terminal_type == 'cancelled':
            run_state = 'cancelled'
        elif latest_terminal and terminal_type == 'recovered_terminal_unknown':
            run_state = 'unknown_terminal'
        elif latest_terminal:
            run_state = 'failed'
        else:
            run_state = 'pending' if latest_run else 'not_started'
        terminal_payload = latest_terminal['payload'] if latest_terminal else {}
        run_finished_at = (terminal_payload.get('attempt_finished_at') or terminal_payload.get('actual_finished_at')
                           or terminal_payload.get('observed_at'))
        run_reason_code = _safe_status_reason(terminal_payload.get('reason_code'))
        latest_run_output = next((item for item in reversed(outputs)
                                  if latest_run_id and item['run_id'] == latest_run_id), None)
        latest_run_output_payload = latest_run_output['payload'] if latest_run_output else {}
        latest_refs = latest_run_payload.get('target_refs') or latest_run_output_payload.get('target_refs') or {}
        modern_run = latest_run_payload.get('prediction_contract_version') == PREDICTION_CONTRACT_VERSION
        modern_output = any(item['payload'].get('prediction_contract_version') == PREDICTION_CONTRACT_VERSION
                            for item in outputs)
        modern_capability = modern_run or modern_output or (has_ledger and not latest_run and not outputs)

        def make_last_known(target: str) -> dict[str, Any] | None:
            candidate = last_known_rows.get(target)
            if candidate is None:
                return None
            candidate = {**dict(candidate), 'payload': json.loads(candidate['payload_json'])}
            payload = candidate['payload']
            child = (payload.get('target_outputs') or {}).get(target)
            if not isinstance(child, dict) or not isinstance(child.get('validation'), dict) or child['validation'].get('valid') is not True:
                return {"state": "invalid", "reason_code": "SOURCE_VALIDATION_FAILED"}
            ref = (payload.get('target_refs') or {}).get(target) or {
                'forecast_id': candidate.get('forecast_id'), 'series_id': candidate.get('series_id'),
                'revision': candidate.get('revision'),
            }
            current_ref = latest_refs.get(target) if isinstance(latest_refs, dict) else None
            if isinstance(current_ref, dict) and current_ref.get('forecast_id') != ref.get('forecast_id'):
                state, reason_code = 'version_changed', 'QUESTION_VERSION_CHANGED'
            else:
                origin = self.database.get_judgement(candidate.get('judgement_id')) if candidate.get('judgement_id') else None
                verdict = self.database.validate_judgement(origin, at=as_of) if origin else {"valid": False, "reason": "NO_JUDGEMENT"}
                reason_code = verdict.get('reason')
                observation = observations.get(payload.get('output_id'))
                if not verdict.get('valid'):
                    if reason_code == 'EXPIRED':
                        state = 'expired'
                    elif reason_code == 'CYCLE_CHANGED':
                        state = 'cycle_changed'
                    else:
                        state = 'invalid'
                elif not observation:
                    state, reason_code = 'invalid', 'OUTPUT_AVAILABILITY_PENDING'
                elif observation.get('clock_anomaly'):
                    state, reason_code = 'invalid', 'CLOCK_ANOMALY'
                elif child.get('lifecycle') in {'cancelled', 'completed'}:
                    state, reason_code = 'invalid', 'PLAN_' + child['lifecycle'].upper()
                else:
                    form = child.get('resolved_prediction_form') or child.get('prediction_form')
                    upper = child.get('predicted_start') if form == 'point' else child.get('predicted_end') if form in {'range', 'date', 'end_only'} else None
                    now_text = utc_text(as_of)
                    if child.get('status') == 'KNOWN' and isinstance(upper, str) and upper < now_text:
                        state, reason_code = 'expired', 'PREDICTION_WINDOW_PASSED_NOT_CONFIRMED'
                    else:
                        state, reason_code = 'valid', 'VALID'
            origin = self.database.get_judgement(candidate.get('judgement_id')) if candidate.get('judgement_id') else None
            last_known = {
                "state": state,
                "forecast_id": ref.get('forecast_id'),
                "series_id": ref.get('series_id') or candidate.get('series_id'),
                "revision": ref.get('revision') if isinstance(ref.get('revision'), int) else candidate.get('revision'),
                "origin_judgement_id": candidate.get('judgement_id'),
                "valid_until": origin.get('valid_until') if origin else None,
                "cycle_id": origin.get('cycle_id') if origin else None,
                "reason_code": _safe_status_reason(reason_code),
            }
            if state == 'valid':
                last_known['forecast'] = safe_target_output(child)
            return last_known

        for target in PREDICTION_TARGETS:
            line = lines[target]
            target_ref = latest_refs.get(target) if isinstance(latest_refs, dict) else None
            current_child = (latest_run_output_payload.get('target_outputs') or {}).get(target) if latest_run_output else None
            if latest_run:
                has_declared_modern = modern_run or latest_run_output_payload.get('prediction_contract_version') == PREDICTION_CONTRACT_VERSION
                if has_declared_modern and not isinstance(target_ref, dict):
                    source, implementation = 'contract_error', 'unknown'
                    result_state, reason_code = 'unavailable', 'PREDICTION_STATUS_CONTRACT_ERROR'
                elif has_declared_modern:
                    source, implementation = 'ledger_v2', 'supported'
                    if current_child is None and latest_run_output and run_state == 'succeeded':
                        source, implementation = 'contract_error', 'unknown'
                        result_state, reason_code = 'unavailable', 'PREDICTION_STATUS_CONTRACT_ERROR'
                    elif isinstance(current_child, dict):
                        child_validation = current_child.get('validation')
                        if not isinstance(child_validation, dict) or not isinstance(child_validation.get('valid'), bool):
                            source, implementation = 'contract_error', 'unknown'
                            result_state, reason_code = 'unavailable', 'PREDICTION_STATUS_CONTRACT_ERROR'
                        elif child_validation['valid']:
                            result_state = 'unknown_valid' if current_child.get('status') == 'UNKNOWN' else 'accepted'
                            reason_code = 'VALID'
                        else:
                            result_state = 'rejected'
                            reason_code = child_validation.get('reason') or 'TARGET_REJECTED'
                    else:
                        result_state, reason_code = 'not_returned', run_reason_code
                else:
                    source = 'legacy_undeclared'
                    implementation = 'supported' if target == 'EXTRA_FULL' else 'unsupported'
                    result_state = 'legacy_missing' if target == 'BANKED' else 'not_returned'
                    reason_code = 'LEGACY_TARGET_NOT_IMPLEMENTED' if target == 'BANKED' else run_reason_code
                result_reason = _safe_status_reason(reason_code)
                history_status = 'backfilled' if last_known_rows.get(target) or isinstance(current_child, dict) else 'not_backfilled'
                last_known = make_last_known(target)
                line.update({
                    'forecast_id': target_ref.get('forecast_id') if isinstance(target_ref, dict) else None,
                    'series_id': target_ref.get('series_id') if isinstance(target_ref, dict) else None,
                    'revision': target_ref.get('revision') if isinstance(target_ref, dict) else None,
                    'previous_id': target_ref.get('previous_id') if isinstance(target_ref, dict) else None,
                    'question_revision': target_ref.get('revision') if isinstance(target_ref, dict) else None,
                    'question_version': target_ref.get('forecast_id') if isinstance(target_ref, dict) else None,
                    'run_id': latest_run_id,
                    'attempt_id': latest_attempt_id,
                    'valid': False,
                    'current_or_last_known': 'last_known' if last_known else 'unavailable',
                    'last_known': last_known,
                })
                if isinstance(current_child, dict) and current_child.get('validation', {}).get('valid') is True and latest_run_output:
                    # A successful current run owns these fields; do not copy a prior child over it.
                    latest_output_row = latest_run_output
                    current_origin = self.database.get_judgement(latest_output_row.get('judgement_id')) if latest_output_row.get('judgement_id') else None
                    current_verdict = self.database.validate_judgement(current_origin, at=as_of) if current_origin else {'valid': False, 'reason': 'NO_JUDGEMENT'}
                    current_observation = observations.get(latest_run_output_payload.get('output_id'))
                    output_valid = bool(current_child.get('validation', {}).get('valid') and current_verdict.get('valid')
                                         and current_observation and not current_observation.get('clock_anomaly'))
                    if current_child.get('lifecycle') in {'cancelled', 'completed'}:
                        output_valid = False
                    child_form = current_child.get('resolved_prediction_form') or current_child.get('prediction_form')
                    child_upper = current_child.get('predicted_start') if child_form == 'point' else current_child.get('predicted_end') if child_form in {'range', 'date', 'end_only'} else None
                    if output_valid and current_child.get('status') == 'KNOWN' and isinstance(child_upper, str) and child_upper < now:
                        output_valid = False
                    line.update(safe_target_output(current_child))
                    line.update(target_ref or {})
                    line.update({
                        'target': target, 'status': current_child.get('status'),
                        'target_output_id': current_child.get('target_output_id'),
                        'output_revision': current_child.get('output_revision'),
                        'origin_judgement_id': latest_output_row.get('judgement_id'),
                        'run_id': latest_run_id, 'attempt_id': latest_output_row.get('attempt_id'),
                        'state': 'current' if output_valid and current_child.get('status') == 'KNOWN' else 'unknown' if output_valid else 'expired' if current_verdict.get('reason') in {'EXPIRED'} or isinstance(child_upper, str) and child_upper < now else 'invalid',
                        'valid': output_valid,
                        'validation_reason': 'VALID' if output_valid else current_verdict.get('reason') if not current_verdict.get('valid') else 'OUTPUT_AVAILABILITY_PENDING' if not current_observation else 'CLOCK_ANOMALY' if current_observation.get('clock_anomaly') else 'PREDICTION_WINDOW_PASSED_NOT_CONFIRMED',
                        'current_or_last_known': 'current' if output_valid else 'unavailable',
                        'output_available_at': current_observation.get('observed_at') if current_observation else None,
                        'output_available_at_source': current_observation.get('source') if current_observation else None,
                        'updated_at': latest_output_row.get('recorded_at'),
                        'updated_at_source': 'ledger_recorded_at',
                        'judged_at': current_origin.get('created_at') if current_origin else None,
                        'valid_until': current_origin.get('valid_until') if current_origin else None,
                    })
                else:
                    # The current failed/pending/rejected attempt is its own source.
                    # Old forecast fields survive only under status_projection.last_known.
                    for key in ('forecast_id', 'revision', 'previous_id', 'method', 'scope', 'predicted_start', 'predicted_end', 'prediction_form',
                                'source_timezone', 'precision', 'time_basis', 'expression', 'relative_anchor_at',
                                'relative_offset_seconds', 'reason', 'unresolved_reason', 'evidence_post_ids',
                                'evidence_refs', 'lifecycle', 'date_boundaries', 'timezone_status',
                                'resolved_prediction_form', 'resolution_basis', 'validation', 'rejected_output',
                                'target_output_id', 'output_revision', 'output_available_at',
                                'output_available_at_source', 'clock_anomaly', 'time_limitation', 'origin_judgement_id',
                                'updated_at', 'judged_at', 'valid_until', 'record_id', 'ledger_seq', 'health_state'):
                        line[key] = None
                    line.pop('rejected_output', None)
                    line.update({
                        'input_snapshot': latest_run_payload.get('input_snapshot_artifact_ref'),
                        'runtime': latest_run_payload.get('runtime'),
                        'prompt_artifact_ref': latest_run_payload.get('prompt_artifact_ref'),
                        'schema_artifact_ref': latest_run_payload.get('schema_artifact_ref'),
                        'record_kind': latest_run_payload.get('record_kind'),
                        'is_synthetic': latest_run_payload.get('is_synthetic'),
                    })
                    line['status'] = None
                    line['state'] = run_state if result_state == 'not_returned' else 'rejected' if result_state == 'rejected' else 'unavailable'
                    line['validation_reason'] = result_reason or ('PREDICTION_STATUS_CONTRACT_ERROR' if source == 'contract_error' else None)
                    line['reason'] = _status_summary(line['validation_reason']) or line['validation_reason']
                    line['valid'] = False
                    line['current_or_last_known'] = 'last_known' if last_known else 'unavailable'
                line['status_projection'] = normalize_prediction_status_projection({
                    'target': target,
                    'status_projection': {
                        'capability': {'implementation': implementation, 'source': source},
                        'run': {'state': run_state, 'run_id': latest_run_id, 'attempt_id': latest_attempt_id,
                                'finished_at': run_finished_at, 'reason_code': run_reason_code},
                        'result': {'state': result_state, 'reason_code': result_reason, 'summary': _status_summary(result_reason)},
                        'history_status': history_status,
                        'last_known': last_known,
                    },
                }, target=target)
            else:
                # Boundary compatibility for pre-ledger and legacy rows is handled
                # by the same normalizer as the API and history DTOs.
                if has_ledger and not outputs:
                    line.update({
                        'status': None, 'state': 'not_attempted', 'valid': False,
                        'validation_reason': 'PREDICTION_NOT_ATTEMPTED',
                        'current_or_last_known': 'unavailable', 'last_known': None,
                    })
                    line['status_projection'] = normalize_prediction_status_projection({
                        'target': target,
                        'status_projection': {
                            'capability': {'implementation': 'supported', 'source': 'ledger_v2'},
                            'run': {'state': 'not_started', 'run_id': None, 'attempt_id': None,
                                    'finished_at': None, 'reason_code': None},
                            'result': {'state': 'not_attempted', 'reason_code': None, 'summary': None},
                            'history_status': 'not_backfilled', 'last_known': None,
                        },
                    }, target=target)
                elif not has_ledger and target == 'BANKED':
                    line.update({
                        'state': None, 'valid': False, 'validation_reason': 'LEGACY_TARGET_UNDECLARED',
                        'current_or_last_known': 'unavailable', 'last_known': None,
                    })
                    line['status_projection'] = normalize_prediction_status_projection({
                        'target': target,
                        'status_projection': {
                            'capability': {'implementation': 'unsupported', 'source': 'legacy_undeclared'},
                            'run': {'state': 'not_started', 'run_id': None, 'attempt_id': None,
                                    'finished_at': None, 'reason_code': None},
                            'result': {'state': 'legacy_missing', 'reason_code': 'LEGACY_TARGET_UNDECLARED', 'summary': None},
                            'history_status': 'unknown', 'last_known': None,
                        },
                    }, target=target)
                else:
                    line['last_known'] = None
                    line['status_projection'] = normalize_prediction_status_projection(line, target=target)

        normal_line = lines['NORMAL_WEEKLY']
        helper_status = normal_line.get('baseline_status') or normal_line.get('status') or normal_line.get('state')
        helper_status = str(helper_status or 'unknown').lower()
        if helper_status == 'expired' or normal_line.get('validation_reason') == 'EXPIRED':
            normal_calculation = 'expired'
        elif normal_line.get('unresolved_reason') == 'NO_BUSINESS_FULL_ANCHOR':
            normal_calculation = 'no_business_full_anchor'
        elif normal_line.get('predicted_start') or normal_line.get('predicted_end'):
            normal_calculation = 'calculated'
        else:
            normal_calculation = 'unresolved'
        normal_history_status = 'backfilled' if normal is not None else 'not_backfilled' if normal_calculation == 'calculated' else 'not_applicable'
        normal_source = 'ledger_v2' if normal is not None else 'legacy_undeclared'
        normal_result_state = 'accepted' if normal_calculation in {'calculated', 'expired'} else 'unavailable'
        normal_reason = 'EXPIRED' if normal_calculation == 'expired' else 'NO_BUSINESS_FULL_ANCHOR' if normal_calculation == 'no_business_full_anchor' else 'UNRESOLVED' if normal_calculation == 'unresolved' else 'VALID'
        normal_line['status_projection'] = normalize_prediction_status_projection({
            'target': 'NORMAL_WEEKLY',
            'status_projection': {
                'capability': {'implementation': 'supported', 'source': normal_source},
                'run': {'state': 'not_started', 'run_id': None, 'attempt_id': None, 'finished_at': None, 'reason_code': None},
                'result': {'state': normal_result_state, 'reason_code': normal_reason, 'summary': _status_summary(normal_reason)},
                'history_status': normal_history_status,
                'last_known': None,
                'normal': {'helper_status': helper_status, 'calculation_status': normal_calculation},
            },
        }, target='NORMAL_WEEKLY')
        modern_output = modern_capability
        return {"version": PREDICTION_API_VERSION, "capabilities": {"model_targets": list(PREDICTION_TARGETS) if modern_output else [],
                "history_lines": has_ledger,
                "normal_history": normal is not None, "output_availability": "observed_upper_bound_or_null", "writes_on_read": False},
                "lines": {target: lines[target] for target in ALL_PREDICTION_TARGETS}}

    @staticmethod
    def _payload_json(value: Any) -> str:
        return canonical_bytes(value).decode("utf-8").rstrip("\n")

    @staticmethod
    def _validate_payload(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in FORBIDDEN_LEDGER_KEYS:
                    raise ValueError(f"forbidden ledger payload key: {key}")
                PredictionLedger._validate_payload(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                PredictionLedger._validate_payload(item)

    def _put_artifact(
        self,
        connection: sqlite3.Connection,
        kind: str,
        payload: dict[str, Any],
    ) -> dict[str, str]:
        if kind not in ARTIFACT_KINDS:
            raise ValueError(f"unsupported prediction artifact kind: {kind}")
        self._validate_payload(payload)
        content_hash = sha256_json(payload)
        existing = connection.execute(
            "SELECT id FROM prediction_artifacts WHERE kind=? AND content_hash=?",
            (kind, content_hash),
        ).fetchone()
        if existing:
            artifact_id = str(existing["id"])
        else:
            artifact_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO prediction_artifacts(id,kind,content_hash,payload_json,recorded_at) VALUES(?,?,?,?,?)",
                (artifact_id, kind, content_hash, self._payload_json(payload), utc_text()),
            )
        return {"artifact_id": artifact_id, "kind": kind, "content_hash": content_hash}

    def _append_record(
        self,
        connection: sqlite3.Connection,
        kind: str,
        payload: dict[str, Any],
        *,
        series_id: str | None = None,
        forecast_id: str | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
        revision: int | None = None,
        judgement_id: int | None = None,
        event_id: int | None = None,
        occurred_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        if kind not in PREDICTION_LEDGER_KINDS:
            raise ValueError(f"unsupported prediction ledger kind: {kind}")
        self._validate_payload(payload)
        if idempotency_key:
            existing = connection.execute(
                "SELECT record_id FROM prediction_ledger WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return str(existing["record_id"])
        record_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO prediction_ledger(
            record_id,kind,series_id,forecast_id,run_id,attempt_id,revision,judgement_id,event_id,
            occurred_at,recorded_at,idempotency_key,payload_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (record_id, kind, series_id, forecast_id, run_id, attempt_id, revision,
             judgement_id, event_id, utc_text(occurred_at) if occurred_at else None,
             utc_text(), idempotency_key, self._payload_json(payload)),
        )
        return record_id

    def _post_identity(self, tweet_id: str) -> tuple[int | None, str | None]:
        post = self.database.get_post_by_tweet_id(str(tweet_id))
        if not post:
            return None, None
        policy = self.database.content_policy(int(post["id"]))
        policy_version = policy.get("policy_version") if policy else "unreviewed-default"
        return int(post["id"]), str(policy_version)

    def _externalize_texts(self, value: Any) -> tuple[Any, list[dict[str, str]]]:
        references: dict[str, dict[str, str]] = {}
        post_cache: dict[str, tuple[int | None, str | None]] = {}

        def walk(item: Any, path: tuple[str, ...], metadata: dict[str, Any]) -> Any:
            if isinstance(item, list):
                return [walk(child, path + (str(index),), metadata) for index, child in enumerate(item)]
            if not isinstance(item, dict):
                return item
            current = dict(metadata)
            for key in ("post_id", "tweet_id", "author", "author_handle", "parent_id", "parent_tweet_id",
                        "relation_source", "relation_to_target", "role", "input_hash", "content_hash",
                        "source_version", "policy_version", "depth"):
                if item.get(key) is not None:
                    current[key] = item[key]
            if "tweet_id" in current:
                tweet_id = str(current["tweet_id"])
                if tweet_id not in post_cache:
                    post_cache[tweet_id] = self._post_identity(tweet_id)
                found_post_id, found_policy_version = post_cache[tweet_id]
                if current.get("post_id") is None:
                    current["post_id"] = found_post_id
                if current.get("policy_version") is None:
                    current["policy_version"] = found_policy_version
            rendered: dict[str, Any] = {}
            for key, child in item.items():
                next_path = path + (str(key),)
                if isinstance(child, str) and key in TEXT_FIELDS:
                    body_payload = {"text": child}
                    body_ref = self._put_artifact_in_context("text_content", body_payload)
                    references[body_ref["artifact_id"]] = body_ref
                    tweet_id = current.get("tweet_id")
                    path_text = ".".join(next_path)
                    if "reply_context" in next_path:
                        role = "parent_or_ancestor_context"
                        relation = "ancestor" if current.get("depth", 1) > 1 else "direct_parent_or_context"
                    elif "evidence_sources" in next_path:
                        role, relation = "evidence_source_post", "event_or_judge_evidence"
                    elif "historical_cases" in next_path:
                        role, relation = "historical_case", "case_context"
                    elif "reset_events" in next_path:
                        role, relation = "event_summary", "event_evidence"
                    elif "posts" in next_path and "analysis" in next_path:
                        role, relation = "target_post_analysis", "analysis_of_target"
                    elif "posts" in next_path:
                        role, relation = "target_post", "judge_target"
                    else:
                        role, relation = "input_text", "input_context"
                    evidence_ref = {
                        "post_id": current.get("post_id"),
                        "tweet_id": str(tweet_id) if tweet_id is not None else None,
                        "author": current.get("author") or current.get("author_handle"),
                        "role": current.get("role") or role,
                        "relation_to_target": current.get("relation_to_target") or relation,
                        "parent_tweet_id": current.get("parent_tweet_id") or current.get("parent_id"),
                        "relation_source": current.get("relation_source"),
                        "source_version": current.get("source_version") or current.get("input_hash") or current.get("content_hash"),
                        "policy_version": current.get("policy_version"),
                        "source_path": path_text,
                    }
                    rendered[key] = {
                        "artifact_ref": body_ref,
                        "content_hash": body_ref["content_hash"],
                        "source_ref": evidence_ref,
                    }
                else:
                    rendered[key] = walk(child, next_path, current)
            return rendered

        externalized = walk(value, (), {})
        return externalized, list(references.values())

    def _put_artifact_in_context(self, kind: str, payload: dict[str, Any]) -> dict[str, str]:
        # Context-aware traversal is called before begin_run's ledger transaction.
        with self.database.connect() as connection:
            return self._put_artifact(connection, kind, payload)

    def record_runtime_identity(
        self,
        identity: dict[str, Any],
        *,
        is_synthetic: bool | None = None,
    ) -> str:
        runtime_id = str(identity["runtime_id"])
        synthetic_marker = is_synthetic if isinstance(is_synthetic, bool) else None
        identity_fields = dict(identity)
        # The explicit argument is authoritative; an embedded value is not provenance.
        identity_fields.pop("is_synthetic", None)
        artifact_payload = {**identity_fields, "is_synthetic": synthetic_marker}
        self._validate_payload(artifact_payload)
        idempotency_key = f"runtime_identity:{runtime_id}"
        with self.database.connect() as connection:
            # Serialize same-ID registrations so a conflicting label cannot race past
            # the append-only identity check below.
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT kind,payload_json FROM prediction_ledger WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                existing_payload = json.loads(existing["payload_json"])
                artifact_ref = existing_payload.get("runtime_artifact_ref")
                artifact_id = artifact_ref.get("artifact_id") if isinstance(artifact_ref, dict) else None
                stored = connection.execute(
                    "SELECT payload_json FROM prediction_artifacts WHERE id=? AND kind='runtime_identity'",
                    (artifact_id,),
                ).fetchone() if artifact_id else None
                stored_payload = json.loads(stored["payload_json"]) if stored is not None else None
                stored_marker = stored_payload.get("is_synthetic") if isinstance(stored_payload, dict) else None
                event_marker = existing_payload.get("is_synthetic")
                stored_identity = dict(stored_payload) if isinstance(stored_payload, dict) else {}
                stored_identity.pop("is_synthetic", None)
                normalized_identity = json.loads(self._payload_json(identity_fields))
                if (
                    existing["kind"] != "runtime_identity"
                    or existing_payload.get("runtime_id") != runtime_id
                    or stored_payload is None
                    or (stored_marker is not None and not isinstance(stored_marker, bool))
                    or (event_marker is not None and not isinstance(event_marker, bool))
                    or stored_marker != synthetic_marker
                    or event_marker != synthetic_marker
                    or stored_identity != normalized_identity
                ):
                    raise ValueError("runtime identity conflict: runtime_id already has a different identity or provenance")
                self.owner = dict(identity.get("owner") or {})
                return runtime_id

            artifact_ref = self._put_artifact(connection, "runtime_identity", artifact_payload)
            self._append_record(
                connection, "runtime_identity",
                {
                    "runtime_id": runtime_id,
                    "runtime_artifact_ref": artifact_ref,
                    "is_synthetic": synthetic_marker,
                },
                run_id=None, idempotency_key=idempotency_key,
            )
        self.owner = dict(identity.get("owner") or {})
        return runtime_id

    def begin_run(
        self,
        frozen_input: dict[str, Any],
        stage: str,
        runtime_id: str,
        trigger: str | list[str] | tuple[str, ...],
        record_kind: str,
        is_synthetic: bool = False,
    ) -> RunRef:
        if record_kind not in FORECAST_RECORD_KINDS:
            raise ValueError(f"unsupported forecast record_kind: {record_kind}")
        if not isinstance(frozen_input, dict):
            raise TypeError("frozen_input must be an object")
        forecast = dict(frozen_input.get("forecast") or {})
        forecast.setdefault("target", "EXTRA_FULL")
        forecast.setdefault("scope", {"value": "unknown", "certainty": "not_established_by_ledger"})
        forecast.setdefault("question", "next_full_reset_start")
        forecast.setdefault("method", "model_inference")
        contract_version = frozen_input.get("prediction_contract_version")
        modern = contract_version == PREDICTION_CONTRACT_VERSION
        if modern:
            forecast["version_role"] = "question_version"
            forecast["method"] = None
        forecast["record_kind"] = record_kind
        forecast["is_synthetic"] = is_synthetic if isinstance(is_synthetic, bool) else None
        input_cutoff_at = utc_text(frozen_input.get("input_cutoff_at"))
        judgement_as_of = frozen_input.get("judgement_as_of")
        if judgement_as_of is not None:
            judgement_as_of = utc_text(judgement_as_of)
        selection_mode = str(frozen_input.get("selection_mode") or ("replay" if record_kind == "replay" else "online"))
        if selection_mode not in {"online", "replay"}:
            raise ValueError("selection_mode must be online or replay")
        input_snapshot = copy.deepcopy(frozen_input.get("input_snapshot") or {})
        semantic_hash = sha256_json(input_snapshot)
        prompt_material = frozen_input.get("public_prompt")
        schema_material = frozen_input.get("judge_schema")
        model_context = copy.deepcopy(frozen_input.get("context") or {})
        dynamic_context = {
            "judged_at": model_context.pop("judged_at", judgement_as_of),
            "data_health": model_context.pop("data_health", frozen_input.get("data_health")),
            "pending_inputs": model_context.pop("pending_inputs", frozen_input.get("pending_inputs", [])),
        }
        policy_versions = copy.deepcopy(frozen_input.get("policy_versions") or {})
        base_frame = {
            "forecast": forecast,
            "input_snapshot": input_snapshot,
            "context": model_context,
            "evidence_sources": copy.deepcopy(frozen_input.get("evidence_sources") or []),
            "policy_versions": policy_versions,
        }
        semantic_material = copy.deepcopy(frozen_input.get("semantic_facts") or model_context)
        semantic_material = self._normalize_analysis_version_hashes(semantic_material)
        semantic_facts = self._semantic_facts(semantic_material)
        cycle = model_context.get("current_cycle") if isinstance(model_context, dict) else None
        forecast["cycle_id"] = (cycle or {}).get("id") if isinstance(cycle, dict) else forecast.get("cycle_id")
        forecast.setdefault("basis", frozen_input.get("basis") or "frozen_judge_input")
        externalized_frame, body_refs = self._externalize_texts(base_frame)
        owner = dict(self.owner)
        if owner.get("runtime_id") is None:
            owner["runtime_id"] = runtime_id

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prompt_ref = self._put_artifact(connection, "public_prompt", prompt_material) if isinstance(prompt_material, dict) else None
            schema_ref = self._put_artifact(connection, "judge_schema", schema_material) if isinstance(schema_material, dict) else None
            frame_payload = dict(externalized_frame)
            frame_ref = self._put_artifact(connection, "input_frame", frame_payload)
            input_ref = self._put_artifact(connection, "input_snapshot", {
                "semantic_input_hash": semantic_hash,
                "input_snapshot": input_snapshot,
                "input_frame_artifact_ref": frame_ref,
                "request_context_dynamic": dynamic_context,
                "input_cutoff_at": input_cutoff_at,
                "judgement_as_of": judgement_as_of,
                "selection_mode": selection_mode,
                "pending_inputs": copy.deepcopy(frozen_input.get("pending_inputs") or []),
                "evidence_artifact_refs": body_refs,
                "public_prompt_artifact_ref": prompt_ref,
                "judge_schema_artifact_ref": schema_ref,
            })
            artifact_refs = [input_ref, frame_ref, *body_refs]
            if prompt_ref:
                artifact_refs.append(prompt_ref)
            if schema_ref:
                artifact_refs.append(schema_ref)
            by_id = {ref["artifact_id"]: ref for ref in artifact_refs}
            series_hash = sha256_json({
                "target": forecast["target"], "scope": forecast["scope"], "question": forecast["question"],
                "record_kind": record_kind,
            })
            series_id = f"series-{series_hash[:32]}"
            forecast_refs = [frame_ref, *body_refs]
            forecast_version_payload, forecast_id, forecast_revision = self._forecast_version(
                connection,
                forecast,
                series_id=series_id,
                semantic_facts=semantic_facts,
                policy_versions=policy_versions,
                input_artifact_refs=forecast_refs,
            )
            target_refs = {"EXTRA_FULL": {
                "forecast_id": forecast_id, "series_id": series_id, "revision": forecast_revision,
                "previous_id": forecast_version_payload.get("previous_id"),
            }}
            if modern:
                banked = {**forecast, "target": "BANKED", "question": "next_banked_grant_start"}
                banked_series = "series-" + sha256_json({
                    "target": "BANKED", "scope": banked["scope"], "question": banked["question"], "record_kind": record_kind,
                })[:32]
                banked_payload, banked_id, banked_revision = self._forecast_version(
                    connection, banked, series_id=banked_series, semantic_facts=semantic_facts,
                    policy_versions=policy_versions, input_artifact_refs=forecast_refs,
                )
                target_refs["BANKED"] = {"forecast_id": banked_id, "series_id": banked_series,
                                         "revision": banked_revision, "previous_id": banked_payload.get("previous_id")}
            run_id = str(uuid.uuid4())
            run_payload = {
                "is_synthetic": is_synthetic if isinstance(is_synthetic, bool) else None,
                "stage": str(stage),
                "trigger": sorted({str(trigger)}) if isinstance(trigger, str) else sorted({str(item) for item in trigger}),
                "forecast": forecast,
                "forecast_id": forecast_id,
                "revision": forecast_revision,
                "target_refs": target_refs, "prediction_contract_version": contract_version,
                "runtime": {"runtime_id": runtime_id},
                "input_cutoff_at": input_cutoff_at,
                "judgement_as_of": judgement_as_of,
                "selection_mode": selection_mode,
                "record_kind": record_kind,
                "input_artifact_refs": list(by_id.values()),
                "input_snapshot_artifact_ref": input_ref,
                "input_frame_artifact_ref": frame_ref,
                "prompt_artifact_ref": prompt_ref,
                "schema_artifact_ref": schema_ref,
                "semantic_input_hash": semantic_hash,
                "owner": owner,
            }
            self._append_record(
                connection, "run_started", run_payload,
                series_id=series_id, forecast_id=forecast_id, revision=forecast_revision,
                run_id=run_id, occurred_at=utc_text(),
            )
        return RunRef(
            run_id=run_id,
            series_id=series_id,
            input_artifact_id=input_ref["artifact_id"],
            input_hash=semantic_hash,
            input_cutoff_at=input_cutoff_at,
            judgement_as_of=judgement_as_of,
            input_artifact_refs=tuple(by_id.values()),
            prompt_artifact_ref=prompt_ref,
            schema_artifact_ref=schema_ref,
            input_frame_artifact_ref=frame_ref,
            forecast_id=forecast_id,
            revision=forecast_revision,
            semantic_hash=str(forecast_version_payload["semantic_hash"]),
            is_synthetic=is_synthetic if isinstance(is_synthetic, bool) else None,
            target_refs=target_refs,
        )

    def begin_processing_run(
        self,
        frozen_input: dict[str, Any],
        stage: str,
        runtime_id: str,
        trigger: str | list[str] | tuple[str, ...],
        is_synthetic: bool | None = False,
        *,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProcessingRunRef:
        """Start an immutable analysis/translation lineage without inventing a forecast."""
        if not isinstance(frozen_input, dict):
            raise TypeError("frozen_input must be an object")
        operation = str(stage)
        input_material = copy.deepcopy(frozen_input.get("input") or {})
        processing_identity = copy.deepcopy(frozen_input.get("processing_identity") or {})
        input_hash = str(frozen_input.get("input_hash") or sha256_json(input_material))
        prompt_material = frozen_input.get("public_prompt")
        schema_material = frozen_input.get("schema")
        frame_value = {
            "processing_operation": operation,
            "processing_identity": processing_identity,
            "input": input_material,
        }
        externalized_frame, body_refs = self._externalize_texts(frame_value)
        owner = dict(self.owner)
        owner.setdefault("runtime_id", runtime_id)
        actual_run_id = run_id or str(uuid.uuid4())
        cutoff = utc_text()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prompt_ref = self._put_artifact(connection, "public_prompt", prompt_material) if isinstance(prompt_material, dict) else None
            schema_ref = self._put_artifact(connection, "judge_schema", schema_material) if isinstance(schema_material, dict) else None
            frame_ref = self._put_artifact(connection, "input_frame", {
                **externalized_frame,
                "public_prompt_artifact_ref": prompt_ref,
                "schema_artifact_ref": schema_ref,
            })
            input_ref = self._put_artifact(connection, "input_snapshot", {
                "processing_input_hash": input_hash,
                "input_frame_artifact_ref": frame_ref,
                "evidence_artifact_refs": body_refs,
                "public_prompt_artifact_ref": prompt_ref,
                "schema_artifact_ref": schema_ref,
            })
            refs = [input_ref, frame_ref, *body_refs]
            if prompt_ref:
                refs.append(prompt_ref)
            if schema_ref:
                refs.append(schema_ref)
            unique_refs = {ref["artifact_id"]: ref for ref in refs}
            payload = {
                "is_synthetic": is_synthetic if isinstance(is_synthetic, bool) else None,
                "stage": operation,
                "trigger": sorted({str(trigger)}) if isinstance(trigger, str) else sorted({str(item) for item in trigger}),
                "forecast": None,
                "forecast_id": None,
                "revision": None,
                "record_kind": "processing",
                "processing_operation": operation,
                "processing_input_hash": input_hash,
                "processing_identity": processing_identity,
                "runtime": {"runtime_id": runtime_id},
                "input_cutoff_at": cutoff,
                "input_artifact_refs": list(unique_refs.values()),
                "input_snapshot_artifact_ref": input_ref,
                "input_frame_artifact_ref": frame_ref,
                "prompt_artifact_ref": prompt_ref,
                "schema_artifact_ref": schema_ref,
                "semantic_input_hash": input_hash,
                "owner": owner,
            }
            self._append_record(
                connection, "run_started", payload,
                run_id=actual_run_id, occurred_at=cutoff,
                idempotency_key=idempotency_key,
            )
        return ProcessingRunRef(
            actual_run_id, operation, input_hash, tuple(unique_refs.values()),
            frame_ref, prompt_ref, schema_ref,
            is_synthetic if isinstance(is_synthetic, bool) else None,
        )

    def record_processing_output(self, tracker: AttemptTracker, operation: str, output: dict[str, Any]) -> str:
        self._validate_payload(output)
        result_hash = sha256_json({"operation": operation, "output": output})
        attempt_id = tracker.latest_attempt_id
        if attempt_id is None:
            raise ValueError("processing output has no durable attempt")
        with self.database.connect() as connection:
            artifact_ref = self._put_artifact(connection, "processing_output", {
                "operation": operation,
                "result_version_hash": result_hash,
                "output": output,
            })
        tracker.append_event(
            attempt_id, "processing_output_recorded",
            operation=operation,
            result_version_hash=result_hash,
            output_artifact_ref=artifact_ref,
            artifact_refs=[artifact_ref],
        )
        return tracker.append_event(
            attempt_id, "success",
            failure_terminal=True,
            operation=operation,
            result_version_hash=result_hash,
            output_artifact_ref=artifact_ref,
            artifact_refs=[artifact_ref],
        )

    def record_cache_reused(
        self,
        *,
        stage: str,
        input_hash: str,
        output: dict[str, Any],
        runtime_id: str,
        processing_identity: dict[str, Any],
        input_material: dict[str, Any],
        public_prompt: dict[str, Any] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> str:
        result_hash = sha256_json({"operation": stage, "output": output})
        source = self._find_processing_source(stage, input_hash, processing_identity, result_hash)
        cache_key = f"cache_reused:{stage}:{input_hash}:{result_hash}"
        if source is not None:
            return self.append_run_event(
                source["run_id"], "cache_reused",
                operation=stage,
                result_version_hash=result_hash,
                output_artifact_ref=source["output_artifact_ref"],
                artifact_refs=[source["output_artifact_ref"]],
                source_status="KNOWN",
                source_run_id=source["run_id"],
                source_attempt_id=source["attempt_id"],
                source_request_hash=source["request_hash"],
                idempotency_key=cache_key,
            )

        cache_run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, cache_key))
        frozen = {
            "input": input_material,
            "input_hash": input_hash,
            "processing_identity": processing_identity,
            "public_prompt": public_prompt,
            "schema": schema,
        }
        cache_run = self.begin_processing_run(
            frozen, stage, runtime_id, "cache_reuse", is_synthetic=None,
            run_id=cache_run_id, idempotency_key=f"{cache_key}:run",
        )
        with self.database.connect() as connection:
            artifact_ref = self._put_artifact(connection, "processing_output", {
                "operation": stage,
                "result_version_hash": result_hash,
                "output": output,
            })
        return self.append_run_event(
            cache_run.run_id, "cache_reused",
            operation=stage,
            result_version_hash=result_hash,
            output_artifact_ref=artifact_ref,
            artifact_refs=[artifact_ref],
            source_status="UNKNOWN",
            source_run_id=None,
            source_attempt_id=None,
            source_request_hash=None,
            reason_summary="Legacy cached result has no recoverable request lineage.",
            idempotency_key=cache_key,
        )

    def _find_processing_source(
        self,
        stage: str,
        input_hash: str,
        processing_identity: dict[str, Any],
        result_hash: str,
    ) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT run_id,attempt_id,payload_json FROM prediction_ledger
                WHERE kind='attempt_event' AND json_extract(payload_json,'$.event_type')='success'
                AND json_extract(payload_json,'$.result_version_hash')=? ORDER BY seq DESC""",
                (result_hash,),
            ).fetchall()
        for row in rows:
            if not row["run_id"] or not row["attempt_id"]:
                continue
            run = self._run_row(str(row["run_id"]))
            payload = run["payload"]
            if (payload.get("processing_operation") != stage
                    or payload.get("processing_input_hash") != input_hash
                    or payload.get("processing_identity") != processing_identity):
                continue
            event = json.loads(row["payload_json"])
            attempt = self._attempt_start_payload(str(row["run_id"]), str(row["attempt_id"]))
            artifact_ref = event.get("output_artifact_ref")
            if isinstance(artifact_ref, dict):
                return {
                    "run_id": str(row["run_id"]),
                    "attempt_id": str(row["attempt_id"]),
                    "request_hash": attempt.get("request_hash"),
                    "output_artifact_ref": artifact_ref,
                }
        return None

    def begin_send(
        self,
        run_id: str,
        request_descriptor: dict[str, Any],
        retry_of: str | None = None,
        *,
        owner: dict[str, Any] | None = None,
        is_synthetic: bool | None = None,
    ) -> AttemptRef:
        self._validate_payload(request_descriptor)
        if "messages" in request_descriptor or "system" in request_descriptor or "user" in request_descriptor:
            raise ValueError("request descriptor must contain artifact references, not repeated prompt/body text")
        actual_request_hash = str(request_descriptor.get("request_hash") or sha256_json(request_descriptor))
        descriptor = dict(request_descriptor)
        descriptor["request_hash"] = actual_request_hash
        attempt_id = str(uuid.uuid4())
        started_at = utc_text()
        attempt_owner = dict(owner or self.owner)
        if attempt_owner.get("runtime_id") is None:
            run = self._run_row(run_id)
            attempt_owner["runtime_id"] = (run["payload"].get("runtime") or {}).get("runtime_id")
        with self.database.connect() as connection:
            run = connection.execute(
                "SELECT series_id,forecast_id,revision,payload_json FROM prediction_ledger WHERE kind='run_started' AND run_id=? ORDER BY seq LIMIT 1",
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError(f"unknown prediction run: {run_id}")
            request_ref = self._put_artifact(connection, "request_descriptor", descriptor)
            run_payload = json.loads(run["payload_json"])
            synthetic_marker = is_synthetic if isinstance(is_synthetic, bool) else run_payload.get("is_synthetic")
            declared_model = descriptor.get("declared_model")
            if not isinstance(declared_model, str):
                declared_model = descriptor.get("model") if isinstance(descriptor.get("model"), str) else None
            payload = {
                "request_artifact_ref": request_ref,
                "request_hash": actual_request_hash,
                "stage": str(descriptor.get("stage") or "radar_judge"),
                "retry_of": retry_of,
                "attempt_started_at": started_at,
                "owner": attempt_owner,
                "declared_model": declared_model,
                "is_synthetic": synthetic_marker if isinstance(synthetic_marker, bool) else None,
            }
            self._append_record(
                connection, "attempt_started", payload,
                series_id=run["series_id"], forecast_id=run["forecast_id"],
                revision=run["revision"], run_id=run_id, attempt_id=attempt_id,
                occurred_at=started_at,
            )
        return AttemptRef(
            attempt_id=attempt_id, run_id=run_id, request_artifact_id=request_ref["artifact_id"],
            request_hash=actual_request_hash, attempt_started_at=started_at,
            owner_id=str(attempt_owner.get("runtime_id") or "unknown"),
        )

    def append_attempt_event(self, run_id: str, attempt_id: str, event_type: str, **payload: Any) -> str:
        idempotency_key = payload.pop("idempotency_key", None)
        event = {"event_type": str(event_type), **payload}
        occurred_at = event.get("attempt_finished_at") or event.get("received_at") or event.get("observed_at")
        with self.database.connect() as connection:
            start = connection.execute(
                "SELECT series_id,forecast_id,revision,payload_json FROM prediction_ledger WHERE kind='attempt_started' AND run_id=? AND attempt_id=? ORDER BY seq LIMIT 1",
                (run_id, attempt_id),
            ).fetchone()
            if start is None:
                raise ValueError(f"unknown prediction attempt: {attempt_id}")
            start_payload = json.loads(start["payload_json"])
            event.setdefault("is_synthetic", start_payload.get("is_synthetic"))
            if "declared_model" not in event and start_payload.get("declared_model") is not None:
                event["declared_model"] = start_payload["declared_model"]
            if occurred_at:
                started_at = json.loads(start["payload_json"]).get("attempt_started_at")
                event.update(_wall_clock_order_fields(started_at, str(occurred_at)))
            self._validate_payload(event)
            return self._append_record(
                connection, "attempt_event", event, series_id=start["series_id"],
                forecast_id=start["forecast_id"], revision=start["revision"],
                run_id=run_id, attempt_id=attempt_id, occurred_at=occurred_at,
                idempotency_key=idempotency_key,
            )

    def append_run_event(
        self, run_id: str, event_type: str, *, idempotency_key: str | None = None, **payload: Any,
    ) -> str:
        """Record a preflight/request failure when no HTTP attempt was started."""
        event = {"event_type": str(event_type), **payload}
        self._validate_payload(event)
        occurred_at = event.get("attempt_finished_at") or event.get("received_at") or event.get("observed_at")
        with self.database.connect() as connection:
            run = connection.execute(
                "SELECT series_id,forecast_id,revision,payload_json FROM prediction_ledger WHERE kind='run_started' AND run_id=? ORDER BY seq LIMIT 1",
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError(f"unknown prediction run: {run_id}")
            run_payload = json.loads(run["payload_json"])
            event.setdefault("is_synthetic", run_payload.get("is_synthetic"))
            return self._append_record(
                connection, "attempt_event", event, series_id=run["series_id"],
                forecast_id=run["forecast_id"], revision=run["revision"], run_id=run_id,
                occurred_at=occurred_at, idempotency_key=idempotency_key,
            )

    def attempt_is_terminal(self, run_id: str, attempt_id: str) -> bool:
        placeholders = ",".join("?" for _ in ATTEMPT_TERMINAL_EVENTS)
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT 1 FROM prediction_ledger WHERE kind='attempt_event' AND run_id=? AND attempt_id=?
                AND json_extract(payload_json,'$.event_type') IN (""" + placeholders + ") LIMIT 1",
                (run_id, attempt_id, *sorted(ATTEMPT_TERMINAL_EVENTS)),
            ).fetchone() is not None

    def commit_judge(self, run_id: str, accepted_attempt_id: str, result: dict[str, Any]) -> OutputRef:
        run = self._run_row(run_id)
        run_payload = run["payload"]
        frozen_input = self._load_artifact(run_payload["input_snapshot_artifact_ref"]["artifact_id"])
        input_snapshot = frozen_input.get("input_snapshot") or {}
        selection_mode = run_payload.get("selection_mode") or (
            "replay" if run_payload.get("record_kind") == "replay" else "online"
        )
        as_of = run_payload.get("judgement_as_of") if selection_mode == "replay" else None
        attempt_start = self._attempt_start_payload(run_id, accepted_attempt_id)
        if run_payload.get("prediction_contract_version") == PREDICTION_CONTRACT_VERSION:
            frame = self._restore_texts(self._load_artifact(run_payload["input_frame_artifact_ref"]["artifact_id"]))
            target_outputs, target_validation = validate_predictions(result.get("predictions"), frame.get("context") or {})
            result = copy.deepcopy(result)
            result.update({"predictions": target_outputs, "prediction_validation": target_validation,
                           "prediction_contract_version": PREDICTION_CONTRACT_VERSION})
            result.setdefault("raw", {}).update({"predictions": target_outputs, "prediction_validation": target_validation,
                                                "prediction_contract_version": PREDICTION_CONTRACT_VERSION})
            if target_validation["status"] == "rejected":
                structured = self._structured_output(result)
                self.append_attempt_event(run_id, accepted_attempt_id, "schema_failure", failure_terminal=True,
                    reason_code="ALL_PREDICTION_TARGETS_REJECTED", structured_output=structured,
                    attempt_finished_at=utc_text(), output_available_at=None, publication_status="rejected")
                raise PredictionTargetsError(structured)
        structured_output = self._structured_output(result)

        rejected_at: str | None = None
        reference_error: JudgementReferenceError | None = None
        with self.database.connect() as connection, self.database.using_connection(connection):
            connection.execute("BEGIN IMMEDIATE")
            fresh = self._fresh_judge_context(connection, as_of, selection_mode)
            fresh_snapshot = self.database.input_snapshot(fresh)
            input_version_delta = self._input_version_delta(
                input_snapshot, fresh_snapshot,
                frozen_input.get("pending_inputs") or [], fresh.get("pending_inputs") or [],
            )
            pending_changed = sha256_json(fresh["pending_inputs"]) != sha256_json(frozen_input.get("pending_inputs") or [])
            if fresh_snapshot != input_snapshot or pending_changed:
                rejected_at = utc_text()
                self._append_record(
                    connection, "attempt_event",
                    {"event_type": "late_input_rejected", "failure_terminal": True,
                     "reason_code": "INPUT_SNAPSHOT_CHANGED", "attempt_finished_at": rejected_at,
                     "reason_summary": "Frozen Judge input versions changed before publication.",
                     "structured_output": structured_output,
                     "input_version_delta": input_version_delta,
                     "output_available_at": None, "publication_status": "rejected",
                     "is_synthetic": attempt_start.get("is_synthetic"),
                     **_wall_clock_order_fields(attempt_start.get("attempt_started_at"), rejected_at)},
                    series_id=run["series_id"], run_id=run_id, attempt_id=accepted_attempt_id,
                    forecast_id=run_payload.get("forecast_id"), revision=run_payload.get("revision"),
                    occurred_at=rejected_at,
                )
                # Commit the durable rejection marker before raising outside the
                # transaction; otherwise the context manager rolls it back.
                connection.commit()
            else:
                forecast_id = str(run_payload["forecast_id"])
                revision = int(run_payload["revision"])
                try:
                    judgement_id = self.database._insert_judgement(
                        connection, result, ledger_attempt_id=accepted_attempt_id,
                    )
                except JudgementReferenceError as error:
                    failed_at = utc_text()
                    failure_payload = {
                        "event_type": "reference_failure",
                        "failure_terminal": True,
                        "reason_code": error.reason_code,
                        "reason_summary": "Judge evidence reference was unresolved or ineligible.",
                        "error_type": type(error).__name__,
                        "attempt_finished_at": failed_at,
                        "output_available_at": None,
                        "publication_status": "rejected",
                        "structured_output": structured_output,
                        "is_synthetic": attempt_start.get("is_synthetic"),
                        **_wall_clock_order_fields(attempt_start.get("attempt_started_at"), failed_at),
                    }
                    self._append_record(
                        connection, "attempt_event", failure_payload,
                        series_id=run["series_id"], forecast_id=forecast_id, run_id=run_id,
                        attempt_id=accepted_attempt_id, revision=revision, occurred_at=failed_at,
                    )
                    # Keep the rejection durable while preserving ValueError compatibility.
                    connection.commit()
                    reference_error = error
                else:
                    finished_at = utc_text()
                    success_payload = {
                        "event_type": "success", "failure_terminal": True,
                        "attempt_finished_at": finished_at, "output_id": str(judgement_id),
                        "is_synthetic": run_payload.get("is_synthetic"),
                        **_wall_clock_order_fields(attempt_start.get("attempt_started_at"), finished_at),
                    }
                    self._append_record(
                        connection, "attempt_event", success_payload,
                        series_id=run["series_id"], forecast_id=forecast_id, run_id=run_id,
                        attempt_id=accepted_attempt_id, revision=revision, judgement_id=judgement_id,
                        occurred_at=finished_at,
                    )
                    output_payload = {
                        "output_id": str(judgement_id),
                        "structured_output": structured_output,
                        "schema": {"prompt_version": result.get("prompt_version"),
                                   "schema_artifact_ref": run_payload.get("schema_artifact_ref")},
                        "judge_reference": {"table": "radar_judgements", "id": judgement_id},
                        "accepted_attempt_id": accepted_attempt_id,
                        "validation": {"status": "accepted", "evidence_post_ids": structured_output.get("evidence_post_ids", [])},
                        "forecast_id": forecast_id,
                        "series_id": run["series_id"],
                        "revision": revision,
                        "output_available_at": None,
                        "is_synthetic": run_payload.get("is_synthetic"),
                    }
                    if run_payload.get("prediction_contract_version") == PREDICTION_CONTRACT_VERSION:
                        target_outputs = copy.deepcopy(result["predictions"])
                        for target, value in target_outputs.items():
                            prior_count = connection.execute(
                                "SELECT COUNT(*) FROM prediction_ledger WHERE kind='output_committed' AND json_extract(payload_json,?)=?",
                                ('$.target_refs.' + target + '.series_id', run_payload["target_refs"][target]["series_id"]),
                            ).fetchone()[0]
                            value.update({"target_output_id": str(judgement_id) + ":" + target, "output_revision": prior_count + 1})
                        output_payload.update({"target_refs": run_payload["target_refs"], "target_outputs": target_outputs,
                                               "prediction_contract_version": PREDICTION_CONTRACT_VERSION,
                                               "prediction_validation": result["prediction_validation"]})
                        output_payload["validation"]["status"] = result["prediction_validation"]["status"]
                    self._append_record(
                        connection, "output_committed", output_payload,
                        series_id=run["series_id"], forecast_id=forecast_id, run_id=run_id,
                        attempt_id=accepted_attempt_id, revision=revision, judgement_id=judgement_id,
                    )
        if rejected_at is not None:
            raise LateInputRejected("Judge input changed while request was in flight")
        if reference_error is not None:
            raise reference_error
        return OutputRef(
            output_id=str(judgement_id), judgement_id=judgement_id, run_id=run_id,
            attempt_id=accepted_attempt_id, series_id=run["series_id"],
            forecast_id=forecast_id, revision=revision,
        )

    def observe_output(self, output_ref: OutputRef) -> dict[str, Any]:
        phase = "formal_getter"
        try:
            observed_judgement = self.database.get_judgement(output_ref.judgement_id)
            if observed_judgement is None or str(observed_judgement.get("id")) != output_ref.output_id:
                raise LookupError("committed Judge output was not readable through the formal getter")
            observed_at = utc_text()
            phase = "availability_record"
            payload = {
                "output_id": output_ref.output_id,
                "observed_at": observed_at,
                "source": OUTPUT_AVAILABLE_SOURCE,
                "is_synthetic": self._run_row(output_ref.run_id)["payload"].get("is_synthetic"),
            }
            with self.database.connect() as connection:
                started_row = connection.execute(
                    "SELECT payload_json FROM prediction_ledger WHERE kind='attempt_started' AND run_id=? AND attempt_id=? ORDER BY seq LIMIT 1",
                    (output_ref.run_id, output_ref.attempt_id),
                ).fetchone()
                success_row = connection.execute(
                    "SELECT payload_json FROM prediction_ledger WHERE kind='attempt_event' AND run_id=? AND attempt_id=? AND json_extract(payload_json,'$.event_type')='success' ORDER BY seq DESC LIMIT 1",
                    (output_ref.run_id, output_ref.attempt_id),
                ).fetchone()
                started_at = json.loads(started_row["payload_json"]).get("attempt_started_at") if started_row else None
                finished_at = json.loads(success_row["payload_json"]).get("attempt_finished_at") if success_row else None
                payload.update(_wall_clock_order_fields(started_at, finished_at, observed_at))
                record_id = self._append_record(
                    connection, "output_observed", payload,
                    series_id=output_ref.series_id, forecast_id=output_ref.forecast_id,
                    run_id=output_ref.run_id, attempt_id=output_ref.attempt_id,
                    revision=output_ref.revision, judgement_id=output_ref.judgement_id,
                    occurred_at=observed_at,
                    idempotency_key=f"output_observed:{output_ref.output_id}",
                )
            return {"record_id": record_id, **payload}
        except Exception as error:
            if isinstance(error, LookupError):
                reason_code = "FORMAL_GETTER_MISS"
            elif phase == "formal_getter":
                reason_code = "FORMAL_GETTER_FAILURE"
            else:
                reason_code = "OBSERVATION_PERSISTENCE_FAILURE"
            self._record_observation_failure(output_ref, reason_code, type(error).__name__)
            raise

    def _record_observation_failure(
        self, output_ref: OutputRef, reason_code: str, error_type: str | None = None,
    ) -> None:
        try:
            observed_at = utc_text()
            clock_fields: dict[str, str] = {}
            try:
                with self.database.connect() as connection:
                    started_row = connection.execute(
                        "SELECT payload_json FROM prediction_ledger WHERE kind='attempt_started' AND run_id=? AND attempt_id=? ORDER BY seq LIMIT 1",
                        (output_ref.run_id, output_ref.attempt_id),
                    ).fetchone()
                    success_row = connection.execute(
                        "SELECT payload_json FROM prediction_ledger WHERE kind='attempt_event' AND run_id=? AND attempt_id=? AND json_extract(payload_json,'$.event_type')='success' ORDER BY seq DESC LIMIT 1",
                        (output_ref.run_id, output_ref.attempt_id),
                    ).fetchone()
                    started_at = json.loads(started_row["payload_json"]).get("attempt_started_at") if started_row else None
                    finished_at = json.loads(success_row["payload_json"]).get("attempt_finished_at") if success_row else None
                clock_fields = _wall_clock_order_fields(started_at, finished_at, observed_at)
            except Exception:
                clock_fields = {"time_limitation": "attempt_time_evidence_unavailable"}
            self.append_attempt_event(
                output_ref.run_id, output_ref.attempt_id, "output_observation_failed",
                output_id=output_ref.output_id,
                reason_code=reason_code,
                reason_summary="Post-commit availability observation failed; availability remains unknown.",
                error_type=error_type,
                observed_at=observed_at,
                **clock_fields,
                output_available_at=None,
                publication_status="committed_unobserved",
                idempotency_key=f"output_observation_failed:{output_ref.output_id}",
            )
        except Exception:
            # Observation is best-effort after the atomic publication. A failed
            # audit write must not trigger a model retry or alter availability.
            return

    def append_truth(
        self,
        event_id: int,
        expected_revision: int,
        facts: dict[str, Any],
        evidence_refs: list[dict[str, Any]],
        reason: str,
        **kwargs: Any,
    ) -> str:
        allowed = {
            "actual_start", "actual_start_end", "actual_time_basis", "actual_precision",
            "truth_status", "adjudication_version", "actual_event_type", "special_type",
            "scope", "execution_stage", "actual_evidence_ids", "association_status",
        }
        unknown = sorted(set(facts) - allowed)
        if unknown:
            raise ValueError(f"unsupported truth fact fields: {', '.join(unknown)}")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM reset_events WHERE id=?", (event_id,)).fetchone():
                raise ValueError(f"unknown reset event: {event_id}")
            previous = connection.execute(
                "SELECT MAX(revision) FROM prediction_ledger WHERE kind='truth_revision' AND event_id=?",
                (event_id,),
            ).fetchone()[0]
            previous_revision = int(previous) if previous is not None else 0
            if int(expected_revision) != previous_revision:
                raise ValueError(f"truth revision conflict: expected {expected_revision}, current {previous_revision}")
            revision = previous_revision + 1
            input_refs = []
            for evidence in evidence_refs:
                if not isinstance(evidence, dict):
                    raise TypeError("truth evidence refs must be objects")
                if "artifact_id" in evidence:
                    input_refs.append(dict(evidence))
                else:
                    input_refs.append(self._put_artifact(connection, "truth_evidence", evidence))
            payload = {
                "event_id": int(event_id),
                "true_fields": dict(facts),
                "source_event_id": int(kwargs.get("source_event_id", event_id)),
                "revision": revision,
                "previous_revision": previous_revision or None,
                "evidence_refs": input_refs,
                "reason": str(reason),
                "truth_status": facts.get("truth_status"),
                "adjudication_version": facts.get("adjudication_version"),
                "recorded_at": utc_text(),
                "is_synthetic": kwargs.get("is_synthetic", False) if isinstance(kwargs.get("is_synthetic", False), bool) else None,
            }
            return self._append_record(
                connection, "truth_revision", payload, event_id=int(event_id), revision=revision,
                idempotency_key=f"truth_revision:{event_id}:{revision}",
            )

    def append_reset_event_snapshot(
        self,
        connection: sqlite3.Connection,
        event_id: int,
        source_event: dict[str, Any],
        *,
        reason: str,
        is_synthetic: bool | None = False,
    ) -> str:
        """Append a source-state snapshot inside the reset-event's existing transaction."""
        evidence_ids = sorted({str(value) for value in source_event.get("evidence_post_ids") or []})
        snapshot = {
            "event_id": int(event_id),
            "event_key": source_event.get("event_key"),
            "event_type": source_event.get("event_type"),
            "special_type": source_event.get("special_type"),
            "occurred_at": source_event.get("occurred_at"),
            "occurred_at_end": source_event.get("occurred_at_end"),
            "time_basis": source_event.get("time_basis"),
            "scope": source_event.get("scope"),
            "execution_stage": source_event.get("execution_stage"),
            "source_post_id": source_event.get("source_post_id"),
            "title": source_event.get("title"),
            "summary": source_event.get("summary"),
            "provenance": copy.deepcopy(source_event.get("provenance") or {}),
            "evidence_post_ids": evidence_ids,
            "created_at": source_event.get("created_at"),
            "updated_at": source_event.get("updated_at"),
        }
        semantic_snapshot = {key: value for key, value in snapshot.items() if key not in {"created_at", "updated_at"}}
        snapshot_hash = sha256_json(semantic_snapshot)
        previous_snapshot = connection.execute(
            """SELECT record_id,payload_json FROM prediction_ledger
            WHERE kind='truth_revision' AND event_id=? ORDER BY revision DESC,seq DESC LIMIT 1""",
            (int(event_id),),
        ).fetchone()
        if previous_snapshot is not None:
            previous_payload = json.loads(previous_snapshot["payload_json"])
            if previous_payload.get("source_event_snapshot_hash") == snapshot_hash:
                return str(previous_snapshot["record_id"])
        evidence_refs: list[dict[str, Any]] = []
        event_ref = self._put_artifact(connection, "truth_evidence", {
            "source_event_snapshot": snapshot,
            "source_event_snapshot_hash": snapshot_hash,
            "snapshot_status": "source_state_not_independently_adjudicated",
        })
        evidence_refs.append({"artifact_ref": event_ref, "role": "reset_event_source_snapshot"})
        for tweet_id in evidence_ids:
            post = connection.execute(
                "SELECT id,tweet_id,original_text,text,text_hash,reply_to_tweet_id FROM tibo_posts WHERE tweet_id=?",
                (tweet_id,),
            ).fetchone()
            if post is None:
                evidence_refs.append({"tweet_id": tweet_id, "role": "event_evidence", "snapshot_status": "source_not_local"})
                continue
            author = None
            context_node = connection.execute(
                "SELECT body_json FROM reply_context_nodes WHERE tweet_id=?",
                (tweet_id,),
            ).fetchone()
            if context_node is not None:
                try:
                    author = json.loads(context_node["body_json"]).get("author")
                except (TypeError, ValueError, json.JSONDecodeError):
                    author = None
            if not author:
                source_author = connection.execute(
                    """SELECT author_handle FROM post_source_evidence
                    WHERE post_id=? AND content_hash=? AND author_handle IS NOT NULL
                    ORDER BY captured_at DESC,id DESC LIMIT 1""",
                    (post["id"], post["text_hash"]),
                ).fetchone()
                author = source_author["author_handle"] if source_author else None
            if not author:
                archived_input = connection.execute(
                    """SELECT input_json FROM reply_context_inputs WHERE post_id=?
                    ORDER BY created_at DESC,rowid DESC LIMIT 1""",
                    (post["id"],),
                ).fetchone()
                if archived_input is not None:
                    try:
                        archived_body = json.loads(archived_input["input_json"])
                    except (TypeError, ValueError, json.JSONDecodeError):
                        archived_body = {}
                    if archived_body.get("text_hash") == post["text_hash"]:
                        author = archived_body.get("author_handle")
            exact_policy = connection.execute(
                "SELECT policy_version,event_promotion_allowed FROM post_content_policies WHERE post_id=? AND content_hash=?",
                (post["id"], post["text_hash"]),
            ).fetchone()
            has_policy = connection.execute(
                "SELECT 1 FROM post_content_policies WHERE post_id=? LIMIT 1", (post["id"],),
            ).fetchone() is not None
            allowed = bool(exact_policy["event_promotion_allowed"]) if exact_policy else not has_policy
            item: dict[str, Any] = {
                "post_id": int(post["id"]),
                "tweet_id": str(post["tweet_id"]),
                "author": author,
                "parent_tweet_id": post["reply_to_tweet_id"],
                "source_version": str(post["text_hash"] or ""),
                "policy_version": exact_policy["policy_version"] if exact_policy else (
                    "content-policy-v1" if has_policy else "unreviewed-default"
                ),
                "role": "event_evidence_post",
                "snapshot_status": "frozen" if allowed else "policy_restricted",
            }
            body = str(post["original_text"] or post["text"] or "")
            if allowed and body:
                item["body_artifact_ref"] = self._put_artifact(connection, "text_content", {"text": body})
            evidence_ref = self._put_artifact(connection, "truth_evidence", item)
            evidence_refs.append({"artifact_ref": evidence_ref, "role": "event_evidence_post"})

        previous = connection.execute(
            "SELECT MAX(revision) FROM prediction_ledger WHERE kind='truth_revision' AND event_id=?",
            (int(event_id),),
        ).fetchone()[0]
        previous_revision = int(previous) if previous is not None else 0
        revision = previous_revision + 1
        time_basis = source_event.get("time_basis")
        facts = {
            "actual_event_type": source_event.get("event_type"),
            "special_type": source_event.get("special_type"),
            "scope": source_event.get("scope"),
            "execution_stage": source_event.get("execution_stage"),
            "actual_start": source_event.get("occurred_at"),
            "actual_start_end": source_event.get("occurred_at_end"),
            "actual_time_basis": time_basis,
            "actual_precision": None,
            "truth_status": "SOURCE_EVENT_UNADJUDICATED",
            "adjudication_version": None,
            "actual_evidence_ids": evidence_ids,
            "association_status": "source_event_identity_unadjudicated",
        }
        payload = {
            "event_id": int(event_id),
            "true_fields": facts,
            "source_event_id": int(event_id),
            "revision": revision,
            "previous_revision": previous_revision or None,
            "evidence_refs": evidence_refs,
            "reason": str(reason),
            "truth_status": "SOURCE_EVENT_UNADJUDICATED",
            "adjudication_version": None,
            "source_event_snapshot_hash": snapshot_hash,
            "source_event_snapshot_ref": event_ref,
            "association_status": "source_event_identity_unadjudicated",
            "is_synthetic": is_synthetic if isinstance(is_synthetic, bool) else None,
        }
        return self._append_record(
            connection, "truth_revision", payload,
            event_id=int(event_id), revision=revision,
            idempotency_key=f"truth_event_snapshot:{event_id}:{revision}:{snapshot_hash}",
        )

    def _run_row(self, run_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM prediction_ledger WHERE kind='run_started' AND run_id=? ORDER BY seq LIMIT 1",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"unknown prediction run: {run_id}")
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def _attempt_start_payload(self, run_id: str, attempt_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM prediction_ledger WHERE kind='attempt_started' AND run_id=? AND attempt_id=? ORDER BY seq LIMIT 1",
                (run_id, attempt_id),
            ).fetchone()
        if row is None:
            raise ValueError(f"unknown prediction attempt: {attempt_id}")
        return json.loads(row["payload_json"])

    def _load_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT payload_json FROM prediction_artifacts WHERE id=?", (artifact_id,)).fetchone()
        if row is None:
            raise ValueError(f"missing prediction artifact: {artifact_id}")
        return json.loads(row["payload_json"])

    @staticmethod
    def _structured_output(result: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "action_level", "horizon_24h", "horizon_48h", "horizon_72h",
            "estimated_start", "estimated_end", "estimate_basis", "reason_summary",
            "estimated_start_expression", "estimated_end_expression",
            "estimated_start_time_metadata", "estimated_end_time_metadata",
            "evidence_post_ids", "data_health", "model", "prompt_version", "created_at",
            "predictions", "prediction_validation", "prediction_contract_version", "valid_until",
        )
        return {key: copy.deepcopy(result.get(key)) for key in fields}

    @staticmethod
    def _input_version_delta(
        old_snapshot: dict[str, Any],
        new_snapshot: dict[str, Any],
        old_pending: list[dict[str, Any]],
        new_pending: list[dict[str, Any]],
    ) -> list[dict[str, str | None]]:
        """Return changed version identifiers only; do not copy input material into the event."""
        deltas: list[dict[str, str | None]] = []

        def version_hash(value: Any) -> str | None:
            if value is None:
                return None
            if (isinstance(value, str) and len(value) == 64
                    and all(character in "0123456789abcdef" for character in value)):
                return value
            return sha256_json(value)

        def compare_maps(label: str, old_value: Any, new_value: Any) -> None:
            old_map = old_value if isinstance(old_value, dict) else {}
            new_map = new_value if isinstance(new_value, dict) else {}
            for entity in sorted({str(key) for key in old_map} | {str(key) for key in new_map}):
                old_hash = version_hash(old_map.get(entity))
                new_hash = version_hash(new_map.get(entity))
                if old_hash != new_hash:
                    deltas.append({"class": label, "entity": entity,
                                   "old_hash": old_hash, "new_hash": new_hash})

        for key, label in (
            ("input_versions", "input_version"),
            ("post_analysis_versions", "post_analysis_version"),
            ("reset_event_versions", "reset_event_version"),
            ("historical_case_versions", "historical_case_version"),
            ("policy_versions", "content_policy_version"),
        ):
            compare_maps(label, old_snapshot.get(key), new_snapshot.get(key))

        for key, label in (("current_cycle_version", "current_cycle"), ("corpus_version", "corpus")):
            old_hash, new_hash = version_hash(old_snapshot.get(key)), version_hash(new_snapshot.get(key))
            if old_hash != new_hash:
                deltas.append({"class": label, "entity": key,
                               "old_hash": old_hash, "new_hash": new_hash})

        def pending_map(values: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            result: dict[str, dict[str, Any]] = {}
            for item in values:
                if not isinstance(item, dict):
                    continue
                identity = item.get("id")
                if identity is None:
                    identity = item.get("post_id") or item.get("tweet_id")
                if identity is None:
                    identity = f"pending-{sha256_json(item)[:16]}"
                result[str(identity)] = item
            return result

        compare_maps("pending_input", pending_map(old_pending), pending_map(new_pending))
        return deltas

    @staticmethod
    def _normalize_analysis_version_hashes(value: Any) -> Any:
        """Rehash analysis facts without allowing local processing timestamps to split forecasts."""
        if isinstance(value, list):
            return [PredictionLedger._normalize_analysis_version_hashes(item) for item in value]
        if not isinstance(value, dict):
            return value
        normalized = {
            str(key): PredictionLedger._normalize_analysis_version_hashes(child)
            for key, child in value.items()
        }
        snapshot = normalized.get("input_snapshot")
        posts = [*(normalized.get("posts") or []), *(normalized.get("event_source_posts") or [])]
        if isinstance(snapshot, dict) and isinstance(posts, list) and "post_analysis_versions" in snapshot:
            analysis_versions: dict[str, str] = {}
            for post in posts:
                if not isinstance(post, dict) or post.get("tweet_id") is None:
                    continue
                analysis = post.get("analysis")
                if isinstance(analysis, dict):
                    analysis_versions[str(post["tweet_id"])] = sha256_json(
                        PredictionLedger._semantic_facts(analysis)
                    )
            snapshot = dict(snapshot)
            snapshot["post_analysis_versions"] = analysis_versions
            normalized["input_snapshot"] = snapshot
            if "input_snapshot_id" in normalized:
                normalized["input_snapshot_id"] = sha256_json(snapshot)
        return normalized

    @staticmethod
    def _semantic_facts(value: Any) -> Any:
        excluded = {
            "judged_at", "data_health", "pending_inputs", "previous_judgement",
            "default_reference_last_full_plus_7d", "normal_reference", "corpus_version", "collected_at",
            "last_seen_at", "updated_at", "created_at", "observed_at", "scanned_at",
            "heartbeat_at", "as_of", "judgement_as_of", "input_cutoff_at",
            "_analysed_at", "_analyzed_at",
            "prediction_contract_version",
        }
        if isinstance(value, dict):
            return {str(key): PredictionLedger._semantic_facts(child)
                    for key, child in value.items() if str(key) not in excluded}
        if isinstance(value, list):
            return [PredictionLedger._semantic_facts(item) for item in value]
        if isinstance(value, tuple):
            return [PredictionLedger._semantic_facts(item) for item in value]
        return value

    def _forecast_version(
        self,
        connection: sqlite3.Connection,
        forecast_spec: dict[str, Any],
        *,
        series_id: str,
        semantic_facts: dict[str, Any],
        policy_versions: dict[str, Any],
        input_artifact_refs: list[dict[str, str]],
    ) -> tuple[dict[str, Any], str, int]:
        target = str(forecast_spec["target"])
        scope = forecast_spec["scope"]
        record_kind = str(forecast_spec.get("record_kind") or "online")
        method = None if forecast_spec.get("version_role") == "question_version" else forecast_spec.get("method") or "model_inference"
        facts_digest = sha256_json(semantic_facts)
        semantic_forecast = {
            "target": target,
            "scope": scope,
            "record_kind": record_kind,
            "method": method,
            "version_role": forecast_spec.get("version_role"),
            "basis": forecast_spec.get("basis") or "frozen_judge_input",
            "forecast": {"question": forecast_spec.get("question"),
                         "cycle_id": forecast_spec.get("cycle_id")},
            "facts_digest": facts_digest,
            "policy_versions": policy_versions,
        }
        semantic_hash = sha256_json(semantic_forecast)
        idempotency = f"forecast_version:{series_id}:{semantic_hash}"
        existing = connection.execute(
            "SELECT forecast_id,revision,payload_json FROM prediction_ledger WHERE kind='forecast_version' AND idempotency_key=?",
            (idempotency,),
        ).fetchone()
        if existing:
            old_payload = json.loads(existing["payload_json"])
            return old_payload, str(existing["forecast_id"]), int(existing["revision"])
        latest = connection.execute(
            "SELECT revision,forecast_id FROM prediction_ledger WHERE kind='forecast_version' AND series_id=? ORDER BY revision DESC,seq DESC LIMIT 1",
            (series_id,),
        ).fetchone()
        revision = int(latest["revision"]) + 1 if latest else 1
        forecast_id = str(uuid.uuid4())
        payload = {
            **semantic_forecast,
            "previous_id": str(latest["forecast_id"]) if latest else None,
            "input_artifact_refs": input_artifact_refs,
            "facts_digest": facts_digest,
            "semantic_hash": semantic_hash,
            "forecast_id": forecast_id,
            "is_synthetic": forecast_spec.get("is_synthetic") if isinstance(forecast_spec.get("is_synthetic"), bool) else None,
        }
        self._append_record(
            connection, "forecast_version", payload,
            series_id=series_id, forecast_id=forecast_id, revision=revision,
            idempotency_key=idempotency,
        )
        return payload, forecast_id, revision

    def recover_incomplete(self, *, current_runtime_id: str | None = None) -> list[str]:
        from .runtime_identity import owner_status

        with self.database.connect() as connection:
            starts = connection.execute(
                "SELECT seq,run_id,attempt_id,payload_json FROM prediction_ledger WHERE kind='attempt_started' ORDER BY seq"
            ).fetchall()
            completed = {
                str(row[0]) for row in connection.execute(
                    "SELECT DISTINCT attempt_id FROM prediction_ledger WHERE attempt_id IS NOT NULL AND "
                    "((kind='attempt_event' AND json_extract(payload_json,'$.event_type') IN (%s)) OR kind='recovery_observed')"
                    % ",".join("?" for _ in ATTEMPT_TERMINAL_EVENTS), tuple(ATTEMPT_TERMINAL_EVENTS)
                ).fetchall()
            }
        observed = []
        for start in starts:
            attempt_id = str(start["attempt_id"])
            if attempt_id in completed:
                continue
            payload = json.loads(start["payload_json"])
            owner = payload.get("owner") or {}
            alive = owner_status(owner, current_runtime_id=current_runtime_id)
            if alive is not False:
                continue
            observed_at = utc_text()
            with self.database.connect() as connection:
                record_id = self._append_record(
                    connection, "recovery_observed",
                    {"observed_at": observed_at, "owner_status": "inactive",
                     "terminal_status": "UNKNOWN", "actual_finished_at": None,
                     "source": "startup_owner_probe"},
                    run_id=str(start["run_id"]), attempt_id=attempt_id,
                    occurred_at=None, idempotency_key=f"recovery_observed:{attempt_id}",
                )
            observed.append(record_id)
        return observed
