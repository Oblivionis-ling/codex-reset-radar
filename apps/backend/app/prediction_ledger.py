from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

from .db import JudgementReferenceError
from .review_common import canonical_bytes, sha256_json, utc_text


OUTPUT_AVAILABLE_SOURCE = "formal_read_post_commit_upper_bound"
ATTEMPT_TERMINAL_EVENTS = frozenset({
    "http_failure", "network_failure", "timeout", "cancelled", "parse_failure",
    "schema_failure", "reference_failure", "late_input_rejected", "success",
    "persistence_failure", "request_failure", "recovered_terminal_unknown",
})
TEXT_FIELDS = frozenset({
    "text", "original_text", "text_snapshot", "summary", "reason_summary",
    "context_text", "evidence_quote", "event_title", "coverage_limitations",
})
FORBIDDEN_LEDGER_KEYS = frozenset({
    "api_key", "authorization", "headers", "raw_response", "response_body",
    "access_token", "refresh_token", "client_secret", "password", "credential",
    "reasoning_content", "chain_of_thought", "messages", "system_prompt", "user_prompt",
})

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
    }),
    "run_started": frozenset({
        "is_synthetic", "stage", "trigger", "forecast", "runtime",
        "input_cutoff_at", "judgement_as_of", "input_artifact_refs",
        "input_snapshot_artifact_ref", "semantic_input_hash", "owner",
        "forecast_id", "revision", "prompt_artifact_ref", "schema_artifact_ref",
        "input_frame_artifact_ref", "selection_mode", "record_kind",
        "processing_operation", "processing_input_hash", "processing_identity",
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
            run_id = str(uuid.uuid4())
            run_payload = {
                "is_synthetic": is_synthetic if isinstance(is_synthetic, bool) else None,
                "stage": str(stage),
                "trigger": sorted({str(trigger)}) if isinstance(trigger, str) else sorted({str(item) for item in trigger}),
                "forecast": forecast,
                "forecast_id": forecast_id,
                "revision": forecast_revision,
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
        structured_output = self._structured_output(result)

        rejected_at: str | None = None
        reference_error: JudgementReferenceError | None = None
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            fresh = self.database.judgement_context(as_of=as_of)
            fresh["pending_inputs"] = (
                self.database.judge_pending_inputs(include_deferred=True)
                if selection_mode == "online" else []
            )
            self.database.refresh_input_snapshot(fresh)
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
        posts = normalized.get("posts")
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
            "default_reference_last_full_plus_7d", "corpus_version", "collected_at",
            "last_seen_at", "updated_at", "created_at", "observed_at", "scanned_at",
            "heartbeat_at", "as_of", "judgement_as_of", "input_cutoff_at",
            "_analysed_at", "_analyzed_at",
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
        method = forecast_spec.get("method") or "model_inference"
        facts_digest = sha256_json(semantic_facts)
        semantic_forecast = {
            "target": target,
            "scope": scope,
            "record_kind": record_kind,
            "method": method,
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
