from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping

from .review_common import sha256_json, utc_text
from .review_privacy import PrivacyContext, sanitize_dto


REVIEW_SCHEMA_VERSION = "crr-review-v1"
DEFAULT_MAX_RECORDS = 20_000
MAX_SOURCE_ROWS = 200_000
MAX_JSON_CHARS = 2_000_000

_LEDGER_COLUMNS = (
    "seq", "record_id", "kind", "series_id", "forecast_id", "run_id", "attempt_id", "revision",
    "judgement_id", "event_id", "occurred_at", "recorded_at", "idempotency_key", "payload_json",
)
_ARTIFACT_COLUMNS = ("id", "kind", "content_hash", "payload_json", "recorded_at")
_LEGACY_JUDGEMENT_COLUMNS = (
    "id", "created_at", "action_level", "horizon_24h", "horizon_48h", "horizon_72h", "data_health",
    "reason_summary", "evidence_post_ids", "special_event_ids", "model", "prompt_version", "estimated_start",
    "estimated_end", "estimate_basis", "valid_until", "cycle_id", "status", "failure_reason", "context_hash",
    "raw_json", "corpus_version", "historical_case_ids",
)
_LEGACY_EVENT_COLUMNS = (
    "id", "event_type", "special_type", "occurred_at", "occurred_at_end", "time_basis", "scope",
    "execution_stage", "evidence_post_ids", "title", "summary", "provenance", "created_at", "updated_at",
)

_FORECAST_FIELDS = {
    "record_id", "forecast_id", "series_id", "revision", "previous_id", "target", "scope", "record_kind",
    "method", "basis", "origin_judgement_id", "candidate_id", "event_id", "predicted_start", "predicted_end",
    "prediction_form", "source_timezone", "precision", "time_basis", "judgement_as_of", "input_cutoff_at",
    "content_policy_version", "evidence_versions", "input_versions", "input_snapshot_id", "program_commit",
    "algorithm_version", "model_version", "prompt_version", "config_version", "runtime_id", "runtime_alias",
    "status", "reason_summary", "trigger", "change_reason", "is_synthetic", "recorded_at", "occurred_at",
    "output_available_at", "source_kind", "selection_basis", "version_history_complete", "precision_reason",
    "source_anchor_at", "source_anchor_time_basis", "anchor_precision", "dependency_reason", "is_dependency",
}
_OUTPUT_FIELDS = {
    "record_id", "output_id", "forecast_id", "series_id", "attempt_id", "run_id", "output_kind", "status",
    "validation_status", "output_available_at", "observed_at", "availability_source", "observation_record_id",
    "availability_observations", "response_received_at", "structured_output", "reason_summary", "prompt_version",
    "is_synthetic", "recorded_at", "occurred_at", "reason_code", "judgement_as_of", "declared_model",
    "time_gap_reason", "is_dependency", "selection_basis", "forecast_ref", "attempt_ref", "evidence_refs",
    "operation", "processing_output", "artifact_recorded_at", "source_content_status",
}
_OUTPUT_STRUCTURED_FIELDS = {
    "action_level", "horizon_24h", "horizon_48h", "horizon_72h", "estimated_start", "estimated_end",
    "estimate_basis", "data_health", "judgement_as_of", "status", "evidence_post_ids",
    "estimated_start_expression", "estimated_end_expression",
    "estimated_start_time_metadata", "estimated_end_time_metadata",
}
_ATTEMPT_FIELDS = {
    "record_id", "attempt_id", "forecast_id", "series_id", "run_id", "status", "stage", "event_type",
    "occurred_at", "recorded_at", "attempt_started_at", "attempt_finished_at", "response_received_at",
    "output_available_at", "reason_code", "reason_summary", "trigger", "duration_ms", "is_synthetic",
    "failure_terminal", "usage", "usage_source", "source_status", "source_attempt_ref",
    "clock_anomaly", "time_limitation", "publication_status",
    "reported_model", "reported_model_source", "reported_model_missing_reason",
    "declared_model", "structured_output", "input_version_delta",
}
_TRUTH_FIELDS = {
    "record_id", "event_id", "forecast_id", "series_id", "event_type", "actual_event_type", "special_type", "scope", "actual_start",
    "actual_start_end", "actual_time_basis", "actual_precision", "truth_revision", "previous_revision",
    "truth_status", "adjudication_version", "recorded_at", "occurred_at", "reason_summary", "evidence_versions",
    "candidate_ids", "association_reason", "is_synthetic", "evidence_refs", "source_snapshot",
}
_EVIDENCE_FIELDS = {
    "id", "evidence_id", "tweet_id", "author", "author_role", "parent_tweet_id", "parent_author",
    "parent_author_role", "text", "original_text", "translation", "summary", "url", "posted_at", "observed_at",
    "content_hash", "content_version", "source_version", "policy_version", "relation", "relation_source",
    "relation_to_target", "role", "source_refs", "depth", "is_parent", "is_synthetic",
    "time_precision", "source_timezone", "source_time_raw", "omission_reason", "historical_policy_status",
    "placeholder", "redacted", "redaction_categories", "snapshot_status", "source_snapshot", "body_ref",
}
_SNAPSHOT_FIELDS = {
    "id", "input_snapshot_id", "snapshot_id", "judgement_id", "source_record_id", "source_kind", "judgement_as_of",
    "input_cutoff_at", "input_versions", "input_snapshot", "snapshot_hash", "content_policy_version", "is_synthetic",
    "omission_reason", "evidence_refs", "input_frame", "request_descriptor", "placeholder", "redacted", "redaction_categories",
}
_RUNTIME_FIELDS = {
    "id", "runtime_id", "runtime_alias", "program_commit", "algorithm_version", "model_version", "prompt_version",
    "config_version", "runtime_scope", "identity_status", "captured_at", "is_synthetic", "omission_reason",
    "disk_head", "app_version", "algorithm_fingerprint", "config_fingerprint", "prompt_fingerprint",
    "runtime_fingerprint", "loaded_code_fingerprints", "is_dependency", "dependency_reason",
}
_REFERENCE_KEYS = {
    "runtime_artifact_ref", "runtime_identity_artifact_ref", "input_snapshot_artifact_ref",
    "input_frame_artifact_ref", "request_artifact_ref", "prompt_artifact_ref", "schema_artifact_ref",
    "public_prompt_artifact_ref", "judge_schema_artifact_ref", "input_artifact_refs",
    "evidence_artifact_refs", "evidence_refs", "artifact_refs", "artifact_ref",
    "output_artifact_ref", "body_artifact_ref", "source_event_snapshot_ref",
    "input_snapshot_artifact_id", "runtime_identity_artifact_id", "evidence_artifact_ids",
    "public_evidence_artifact_ids",
}
_ARTIFACT_KIND_TARGET = {
    "public_evidence": "public_evidence",
    "evidence": "public_evidence",
    "tweet_evidence": "public_evidence",
    "post_evidence": "public_evidence",
    "reply_context_node": "public_evidence",
    "text_content": "public_evidence",
    "truth_evidence": "public_evidence",
    "input_snapshot": "input_snapshots",
    "input_frame": "input_snapshots",
    "judgement_input_snapshot": "input_snapshots",
    "runtime_identity": "runtime_identities",
    "request_descriptor": "input_snapshots",
    "public_prompt": "input_snapshots",
    "judge_schema": "input_snapshots",
    "processing_output": "outputs",
}
_SYNTHETIC_ARTIFACT_TARGETS = frozenset({"input_snapshots", "public_evidence", "runtime_identities"})


class ReviewReadError(ValueError):
    pass


class ReviewRangeTooLarge(ReviewReadError):
    pass


def _utc(value: object, label: str) -> tuple[datetime, str]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        try:
            parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw)
        except ValueError as error:
            raise ReviewReadError(f"invalid_{label}_timestamp") from error
    else:
        raise ReviewReadError(f"invalid_{label}_timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReviewReadError(f"{label}_timestamp_requires_timezone")
    canonical = parsed.astimezone(UTC)
    try:
        from .review_common import utc_text  # type: ignore[import-not-found]

        text = utc_text(canonical)
        if not isinstance(text, str):
            raise TypeError
        return canonical, text
    except ImportError:
        return canonical, canonical.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except TypeError:
        # The common helper is still being integrated; keep the reader callable
        # while using its canonical formatter as soon as its signature lands.
        return canonical, canonical.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _maybe_utc(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return _utc(value, "source")[0]
    except ReviewReadError:
        return None


def _json_object(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str) or len(value) > MAX_JSON_CHARS:
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError, RecursionError):
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    found = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not found:
        return set()
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _read_rows(connection: sqlite3.Connection, table: str, columns: Iterable[str], *, order: str = "") -> list[dict[str, Any]]:
    available = _columns(connection, table)
    selected = [name for name in columns if name in available]
    if not selected:
        return []
    # Table/column names come exclusively from module constants, never user input.
    query = f'SELECT {", ".join(selected)} FROM "{table}"'
    if order:
        query += f" ORDER BY {order}"
    cursor = connection.execute(query)
    names = [item[0] for item in cursor.description or ()]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _load_legacy(connection: sqlite3.Connection, freeze_dt: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    judgements: list[dict[str, Any]] = []
    judgement_columns = _columns(connection, "radar_judgements")
    if judgement_columns and int(connection.execute("SELECT COUNT(*) FROM radar_judgements").fetchone()[0]) > MAX_SOURCE_ROWS:
        raise ReviewRangeTooLarge(f"legacy_judgement_scan_exceeds_{MAX_SOURCE_ROWS}; narrow the time window")
    selected = [name for name in _LEGACY_JUDGEMENT_COLUMNS if name in judgement_columns]
    legacy_rows: list[dict[str, Any]] = []
    if selected:
        query = f'SELECT {", ".join(selected)} FROM radar_judgements'
        # Rows written by the new ledger are represented by its output records;
        # do not re-import those rows as legacy outputs.
        if "ledger_attempt_id" in judgement_columns:
            query += " WHERE ledger_attempt_id IS NULL"
        query += " ORDER BY id"
        cursor = connection.execute(query)
        names = [column[0] for column in cursor.description or ()]
        legacy_rows = [dict(zip(names, raw_row)) for raw_row in cursor.fetchall()]
    for row in legacy_rows:
        created = _maybe_utc(row.get("created_at"))
        if created is None or created > freeze_dt:
            continue
        raw = _json_object(row.get("raw_json")) or {}
        input_versions = raw.get("input_versions")
        if not isinstance(input_versions, Mapping):
            input_versions = {}
        safe_versions = {
            str(tweet_id): str(version).lower()
            for tweet_id, version in input_versions.items()
            if re.fullmatch(r"\d{1,25}", str(tweet_id)) and re.fullmatch(r"[0-9a-fA-F]{64}", str(version))
        }
        input_snapshot = raw.get("input_snapshot") if isinstance(raw.get("input_snapshot"), Mapping) else None
        judgements.append({
            "row": row,
            "raw_safe": {
                "input_versions": safe_versions,
                "input_post_ids": [str(item) for item in raw.get("input_post_ids", []) if re.fullmatch(r"\d{1,25}", str(item))]
                if isinstance(raw.get("input_post_ids"), list) else [],
                "input_snapshot": dict(input_snapshot) if input_snapshot is not None else None,
                "input_snapshot_id": raw.get("input_snapshot_id") if isinstance(raw.get("input_snapshot_id"), str) else None,
                "triggers": [str(item) for item in raw.get("triggers", []) if isinstance(item, str)][:20]
                if isinstance(raw.get("triggers"), list) else [],
                "pending_inputs": [str(item) for item in raw.get("pending_inputs", []) if re.fullmatch(r"\d{1,25}", str(item))]
                if isinstance(raw.get("pending_inputs"), list) else [],
            },
            "raw_source": raw,
        })
    events = []
    if _columns(connection, "reset_events") and int(connection.execute("SELECT COUNT(*) FROM reset_events").fetchone()[0]) > MAX_SOURCE_ROWS:
        raise ReviewRangeTooLarge(f"legacy_event_scan_exceeds_{MAX_SOURCE_ROWS}; narrow the time window")
    for row in _read_rows(connection, "reset_events", _LEGACY_EVENT_COLUMNS, order="id"):
        recorded = _maybe_utc(row.get("updated_at")) or _maybe_utc(row.get("created_at"))
        if recorded is not None and recorded <= freeze_dt:
            events.append({"row": row, "recorded_at": recorded})
    return judgements, events, []


def _activity_time(row: Mapping[str, Any]) -> tuple[datetime | None, str]:
    occurred = _maybe_utc(row.get("occurred_at"))
    if occurred is not None:
        return occurred, "occurred_at"
    recorded = _maybe_utc(row.get("recorded_at"))
    if recorded is not None:
        return recorded, "recorded_at_proxy"
    return None, "missing"


def _in_window(when: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if start is None and end is None:
        return True
    if when is None:
        return False
    return (start is None or when >= start) and (end is None or when < end)


def _payload_ref_details(payload: Mapping[str, Any]) -> list[tuple[str, str, str | None, str | None]]:
    refs: dict[tuple[str, str], tuple[str | None, str | None]] = {}
    key_targets = {
        "runtime_artifact_ref": "runtime_identities",
        "runtime_identity_artifact_ref": "runtime_identities",
        "runtime_identity_artifact_id": "runtime_identities",
        "input_snapshot_artifact_ref": "input_snapshots",
        "input_snapshot_artifact_id": "input_snapshots",
        "input_frame_artifact_ref": "input_snapshots",
        "request_artifact_ref": "input_snapshots",
        "prompt_artifact_ref": "input_snapshots",
        "schema_artifact_ref": "input_snapshots",
        "public_prompt_artifact_ref": "input_snapshots",
        "judge_schema_artifact_ref": "input_snapshots",
        "output_artifact_ref": "outputs",
        "body_artifact_ref": "public_evidence",
        "source_event_snapshot_ref": "public_evidence",
        "evidence_artifact_ids": "public_evidence",
        "public_evidence_artifact_ids": "public_evidence",
    }
    role_targets = {
        "evidence": "public_evidence", "public_evidence": "public_evidence", "text_content": "public_evidence",
        "truth_evidence": "public_evidence", "input_snapshot": "input_snapshots", "input_frame": "input_snapshots",
        "request_descriptor": "input_snapshots", "public_prompt": "input_snapshots", "judge_schema": "input_snapshots",
        "runtime_identity": "runtime_identities",
    }

    def target_for(kind: object, hint: str | None) -> str:
        kind_text = str(kind or "").strip().lower()
        if kind_text:
            target = _ARTIFACT_KIND_TARGET.get(kind_text)
            if target is None:
                raise ReviewReadError("artifact_reference_kind_unsupported")
            return target
        return hint or "input_snapshots"

    def add_one(target: str, artifact_id: str, kind: str | None, content_hash: str | None) -> None:
        previous = refs.get((target, artifact_id))
        if previous is not None:
            old_kind, old_hash = previous
            if old_kind and kind and old_kind != kind:
                raise ReviewReadError("artifact_reference_kind_conflict")
            if old_hash and content_hash and old_hash != content_hash:
                raise ReviewReadError("artifact_reference_hash_conflict")
            kind = kind or old_kind
            content_hash = content_hash or old_hash
        refs[(target, artifact_id)] = (kind, content_hash)

    def add_reference(value: object, hint: str | None) -> None:
        if isinstance(value, (list, tuple)):
            for child in value:
                add_reference(child, hint)
            return
        if isinstance(value, (str, int)):
            if str(value):
                add_one(hint or "input_snapshots", str(value), None, None)
            return
        if not isinstance(value, Mapping):
            return
        artifact_id = value.get("artifact_id")
        if isinstance(artifact_id, (str, int)) and str(artifact_id):
            kind_text = str(value.get("kind") or "").strip().lower() or None
            hash_value = value.get("content_hash")
            if hash_value is not None and not isinstance(hash_value, str):
                raise ReviewReadError("artifact_reference_hash_invalid")
            target = target_for(kind_text, hint)
            if hash_value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", hash_value):
                raise ReviewReadError("artifact_reference_hash_invalid")
            if kind_text and hint and _ARTIFACT_KIND_TARGET[kind_text] != hint:
                raise ReviewReadError("artifact_reference_role_conflict")
            add_one(target, str(artifact_id), kind_text, hash_value.lower() if hash_value else None)
            return
        # Modern truth evidence stores artifact references inside role wrappers.
        wrapped_ref = value.get("artifact_ref")
        if isinstance(wrapped_ref, Mapping):
            add_reference(wrapped_ref, hint)
            return
        for role, child in value.items():
            role_target = role_targets.get(str(role).lower())
            if role_target:
                add_reference(child, role_target)

    def walk(value: object) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                if key_text in _REFERENCE_KEYS:
                    add_reference(child, key_targets.get(key_text))
                elif isinstance(child, (Mapping, list, tuple)):
                    walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    walk(payload)
    return [(target, artifact_id, expected[0], expected[1])
            for (target, artifact_id), expected in refs.items()]


def _payload_refs(payload: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [(target, artifact_id) for target, artifact_id, _, _ in _payload_ref_details(payload)]


def _explicit_event_ids(value: object) -> set[str]:
    """Collect only explicitly named event identity fields from frozen structures."""
    found: set[str] = set()

    def add_scalar(item: object) -> None:
        if isinstance(item, int) and not isinstance(item, bool):
            if item >= 0:
                found.add(str(item))
        elif isinstance(item, str) and re.fullmatch(r"\d{1,25}", item.strip()):
            found.add(item.strip())

    def walk(node: object) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if str(key) in {"event_id", "reset_event_id"}:
                    add_scalar(child)
                elif str(key) in {"event_ids", "reset_event_ids"}:
                    if isinstance(child, (list, tuple)):
                        for identifier in child:
                            add_scalar(identifier)
                if isinstance(child, (Mapping, list, tuple)):
                    walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(value)
    return found


def _source_role_artifact(kind: object) -> str | None:
    return _ARTIFACT_KIND_TARGET.get(str(kind or "").strip().lower())


def _record_id(row: Mapping[str, Any]) -> str:
    return str(row.get("record_id") or f"ledger-seq-{row.get('seq')}")


def _id(value: object) -> str | None:
    return str(value) if value is not None and str(value) else None


def _legacy_snapshot_rows(
    connection: sqlite3.Connection,
    judgements: list[dict[str, Any]],
    freeze_dt: datetime,
    current_policies: Mapping[tuple[int, str], bool | None],
    gaps: Counter[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    post_columns = _columns(connection, "tibo_posts")
    post_rows: dict[str, dict[str, Any]] = {}
    if {"tweet_id", "id"}.issubset(post_columns):
        select_columns = [name for name in ("tweet_id", "id", "text_hash") if name in post_columns]
        cursor = connection.execute(f'SELECT {", ".join(select_columns)} FROM tibo_posts')
        for raw_row in cursor.fetchall():
            current = dict(zip(select_columns, raw_row))
            post_rows[str(current["tweet_id"])] = {"post_id": int(current["id"]), "text_hash": current.get("text_hash")}
    input_cols = _columns(connection, "reply_context_inputs")
    history_cols = _columns(connection, "reply_context_history")
    for item in judgements:
        row, raw = item["row"], item["raw_safe"]
        judgement_id = row.get("id")
        as_of = _maybe_utc(row.get("created_at"))
        versions = raw["input_versions"]
        snapshot_id = raw.get("input_snapshot_id")
        snapshot_record = {
            "id": f"legacy-snapshot-{judgement_id}",
            "snapshot_id": snapshot_id,
            "judgement_id": judgement_id,
            "source_record_id": judgement_id,
            "source_kind": "legacy_judge_version_summary",
            "judgement_as_of": row.get("created_at"),
            "input_versions": versions,
            "input_snapshot": raw.get("input_snapshot"),
            "content_policy_version": None,
            "is_synthetic": None,
            "omission_reason": "legacy_snapshot_has_versions_not_full_request_or_policy_text",
            "evidence_refs": [],
        }
        for tweet_id, version in sorted(versions.items()):
            ref_id = f"legacy-evidence-{judgement_id}-{tweet_id}"
            current_post = post_rows.get(tweet_id) or {}
            post_id = current_post.get("post_id")
            archived = None
            required_input_cols = {"input_hash", "post_id", "input_json", "created_at"}
            if required_input_cols.issubset(input_cols) and post_id is not None:
                selected = ("input_hash", "post_id", "input_json", "created_at")
                candidate = connection.execute(
                    f"SELECT {', '.join(selected)} FROM reply_context_inputs WHERE input_hash=? AND post_id=?",
                    (version, post_id),
                ).fetchone()
                if candidate:
                    archived = dict(zip(selected, candidate))
            body = _json_object(archived.get("input_json")) if archived else None
            archive_time = _maybe_utc(archived.get("created_at")) if archived else None
            archived_post_id = None
            try:
                archived_post_id = int(archived.get("post_id")) if archived else None
            except (TypeError, ValueError):
                pass
            if body and archived and archived.get("input_hash") == version and archived_post_id == post_id and str(body.get("tweet_id") or "") == tweet_id and archive_time and as_of and archive_time <= as_of:
                text = body.get("text") if isinstance(body.get("text"), str) else None
                current_hash = current_post.get("text_hash")
                policy = current_policies.get((post_id, str(current_hash))) if post_id is not None and current_hash else None
                omission = "current_content_policy_restricts_export" if policy is False else None
                evidence_row = {
                    "id": ref_id, "tweet_id": tweet_id, "author": body.get("author_handle"), "author_role": "target_post",
                    "text": None if omission else text, "original_text": None,
                    "translation": None, "posted_at": body.get("posted_at"), "observed_at": archived.get("created_at"),
                    "content_version": version, "relation": "target", "is_parent": False,
                    "historical_policy_status": "current_restriction_applied" if policy is False else "unknown_not_snapshotted",
                    "omission_reason": omission or ("legacy_translation_not_archived" if text else "legacy_body_missing"),
                    "redacted": policy is False,
                    "redaction_categories": ["current_content_policy_restriction"] if policy is False else [],
                }
                evidence.append(evidence_row)
                for node in _context_nodes(body.get("reply_context")):
                    node_id = str(node.get("tweet_id") or "")
                    version_id = str(node.get("content_hash") or "")
                    if not re.fullmatch(r"\d{1,25}", node_id) or not re.fullmatch(r"[0-9a-fA-F]{64}", version_id):
                        gaps["legacy_parent_version_unverifiable"] += 1
                        missing_id = ref_id + "-parent-" + (node_id or "unknown")
                        evidence.append(_missing_evidence(missing_id, "historical_parent_version_not_proven"))
                        snapshot_record["evidence_refs"].append({"target": "public_evidence", "id": missing_id, "status": "missing", "reason": "historical_parent_version_not_proven"})
                        continue
                    verified = None
                    if {"tweet_id", "content_hash", "body_json", "observed_at"}.issubset(history_cols):
                        candidate = connection.execute(
                            "SELECT tweet_id,content_hash,body_json,observed_at FROM reply_context_history WHERE tweet_id=? AND content_hash=?",
                            (node_id, version_id),
                        ).fetchone()
                        if candidate:
                            verified = dict(zip(("tweet_id", "content_hash", "body_json", "observed_at"), candidate))
                    historical_node = _json_object(verified.get("body_json")) if verified else None
                    seen = _maybe_utc(verified.get("observed_at")) if verified else None
                    if not historical_node or not verified or verified.get("tweet_id") != node_id or historical_node.get("tweet_id") != node_id or verified.get("content_hash") != version_id or not seen or not as_of or seen > as_of:
                        gaps["legacy_parent_version_unavailable"] += 1
                        missing_id = ref_id + "-parent-" + node_id
                        evidence.append(_missing_evidence(missing_id, "historical_parent_version_unavailable_as_of_judgement"))
                        snapshot_record["evidence_refs"].append({"target": "public_evidence", "id": missing_id, "status": "missing", "reason": "historical_parent_version_unavailable_as_of_judgement"})
                        continue
                    if node.get("parent_id") != historical_node.get("parent_id") or node.get("relation_source") != historical_node.get("relation_source"):
                        gaps["legacy_parent_relation_mismatch"] += 1
                        missing_id = ref_id + "-parent-" + node_id
                        evidence.append(_missing_evidence(missing_id, "historical_parent_relation_unverified"))
                        snapshot_record["evidence_refs"].append({"target": "public_evidence", "id": missing_id, "status": "missing", "reason": "historical_parent_relation_unverified"})
                        continue
                    parent_post = post_rows.get(node_id) or {}
                    parent_post_id = parent_post.get("post_id")
                    parent_current_hash = parent_post.get("text_hash")
                    parent_policy = current_policies.get((parent_post_id, str(parent_current_hash))) if parent_post_id is not None and parent_current_hash else None
                    parent_omission = parent_policy is False
                    parent_id = ref_id + "-parent-" + node_id
                    evidence.append({
                        "id": parent_id, "tweet_id": node_id,
                        "author": historical_node.get("author"), "author_role": "parent_context",
                        "parent_tweet_id": historical_node.get("parent_id"), "text": None if parent_omission else historical_node.get("text"),
                        "posted_at": historical_node.get("posted_at"), "observed_at": verified.get("observed_at"),
                        "content_version": version_id, "relation_source": historical_node.get("relation_source"),
                        "relation": "parent_context", "depth": node.get("depth"), "is_parent": True,
                        "url": historical_node.get("url"),
                        "historical_policy_status": "current_restriction_applied" if parent_omission else "unknown_not_snapshotted",
                        "omission_reason": "current_content_policy_restricts_export" if parent_omission else None,
                        "redacted": parent_omission,
                        "redaction_categories": ["current_content_policy_restriction"] if parent_omission else [],
                    })
                    snapshot_record["evidence_refs"].append({"target": "public_evidence", "id": parent_id, "status": "included", "reason": None})
                snapshot_record["evidence_refs"].append({"target": "public_evidence", "id": ref_id, "status": "included", "reason": None})
            else:
                gaps["legacy_input_snapshot_body_missing"] += 1
                evidence.append(_missing_evidence(ref_id, "exact_historical_input_body_unavailable"))
                snapshot_record["evidence_refs"].append({"target": "public_evidence", "id": ref_id, "status": "missing", "reason": "exact_historical_input_body_unavailable"})
        if not versions:
            snapshot_record["omission_reason"] = "legacy_judge_has_no_saved_input_versions"
            gaps["legacy_input_versions_missing"] += 1
        snapshots.append(snapshot_record)
    return evidence, snapshots


def _context_nodes(value: object) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return [dict(node) for node in nodes if isinstance(node, Mapping)]
    if isinstance(value, list):
        return [dict(node) for node in value if isinstance(node, Mapping)]
    return []


def _missing_evidence(identifier: str, reason: str) -> dict[str, Any]:
    return {"id": identifier, "placeholder": True, "omission_reason": reason, "text": None, "redacted": False, "redaction_categories": []}


def _policy_map(connection: sqlite3.Connection) -> dict[tuple[int, str], bool | None]:
    columns = _columns(connection, "post_content_policies")
    required = {"post_id", "content_hash"}
    if not required.issubset(columns):
        return {}
    allowed_columns = [
        name for name in ("judge_evidence_allowed", "event_promotion_allowed") if name in columns
    ]
    if not allowed_columns:
        return {}
    selected = ["post_id", "content_hash", *allowed_columns]
    rows = connection.execute(f"SELECT {', '.join(selected)} FROM post_content_policies").fetchall()
    result: dict[tuple[int, str], bool | None] = {}
    for row in rows:
        post_id, version, *flags = row
        if any(flag == 0 for flag in flags):
            allowed = False
        elif flags and all(flag == 1 for flag in flags):
            allowed = True
        else:
            allowed = None
        result[(int(post_id), str(version))] = allowed
    return result


def _current_post_map(connection: sqlite3.Connection) -> dict[int, str]:
    columns = _columns(connection, "tibo_posts")
    if not {"id", "text_hash"}.issubset(columns):
        return {}
    rows = connection.execute("SELECT id,text_hash FROM tibo_posts").fetchall()
    return {int(row[0]): str(row[1]) for row in rows if row[0] is not None and row[1] is not None}


def _frame_text_sources(value: object) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []

    def walk(node: object) -> None:
        if isinstance(node, Mapping):
            artifact_ref = node.get("artifact_ref")
            source_ref = node.get("source_ref")
            if isinstance(artifact_ref, Mapping) and isinstance(source_ref, Mapping):
                artifact_id = artifact_ref.get("artifact_id")
                if isinstance(artifact_id, (str, int)) and str(artifact_id):
                    found.append((str(artifact_id), dict(source_ref)))
            for child in node.values():
                if isinstance(child, (Mapping, list, tuple)):
                    walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(value)
    return found


def _runtime_identity_projection(payload: Mapping[str, Any], identifier: str, context: PrivacyContext) -> dict[str, Any]:
    algorithm = payload.get("algorithm") if isinstance(payload.get("algorithm"), Mapping) else {}
    prompt = payload.get("prompt") if isinstance(payload.get("prompt"), Mapping) else {}
    raw_code_hashes = algorithm.get("callable_code_hashes")
    projection = {
        "runtime_id": payload.get("runtime_id"),
        "program_commit": payload.get("program_commit"),
        "disk_head": payload.get("disk_head"),
        "app_version": payload.get("app_version"),
        "algorithm_version": algorithm.get("version"),
        "algorithm_fingerprint": payload.get("algorithm_hash"),
        "config_fingerprint": payload.get("config_hash"),
        "prompt_fingerprint": prompt.get("sha256"),
        "runtime_fingerprint": payload.get("runtime_fingerprint"),
        "loaded_code_fingerprints": raw_code_hashes if isinstance(raw_code_hashes, Mapping) else {},
        "model_version": payload.get("model"),
        "prompt_version": prompt.get("version"),
        "runtime_scope": payload.get("identity_scope"),
        "identity_status": "captured",
        "captured_at": payload.get("captured_at"),
        "is_synthetic": _synthetic_marker(payload),
    }
    return _dto(projection, _RUNTIME_FIELDS, context, identifier=identifier)


def _synthetic_marker(payload: Mapping[str, Any]) -> bool | None:
    value = payload.get("is_synthetic")
    return value if isinstance(value, bool) else None


def _synthetic_consensus(markers: Iterable[bool | None]) -> tuple[bool | None, str]:
    values = set(markers)
    declared = {value for value in values if isinstance(value, bool)}
    if len(declared) > 1:
        return None, "conflict"
    if not values or None in values:
        return None, "undeclared"
    if len(declared) == 1:
        return next(iter(declared)), "declared"
    return None, "undeclared"


def _artifact_synthetic_provenance(
    included: list[dict[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    artifact_refs: Iterable[tuple[str, str]],
    gaps: Counter[str],
) -> dict[str, bool | None]:
    """Propagate source markers over the already-validated artifact-reference closure."""
    run_markers: dict[str, list[bool | None]] = defaultdict(list)
    for item in included:
        row, payload = item["row"], item["payload"]
        run_id = _row_run(row, payload)
        if row.get("kind") == "run_started" and run_id:
            run_markers[str(run_id)].append(_synthetic_marker(payload))

    origins: dict[str, set[bool | None]] = defaultdict(set)
    queue: list[tuple[str, bool | None]] = []
    for item in included:
        row, payload = item["row"], item["payload"]
        own_marker = _synthetic_marker(payload)
        if own_marker is not None:
            marker = own_marker
        else:
            parent_markers = run_markers.get(str(_row_run(row, payload) or ""), [])
            marker, _ = _synthetic_consensus(parent_markers)
        for _, artifact_id in item.get("artifact_refs", []):
            queue.append((artifact_id, marker))

    visited: set[tuple[str, bool | None]] = set()
    while queue:
        artifact_id, marker = queue.pop()
        node = (artifact_id, marker)
        if node in visited:
            continue
        visited.add(node)
        origins[artifact_id].add(marker)
        artifact = artifacts.get(artifact_id)
        payload = artifact.get("payload") if isinstance(artifact, Mapping) else None
        if not isinstance(payload, Mapping):
            continue
        for _, child_id in _payload_refs(payload):
            queue.append((child_id, marker))

    relevant_ids = {
        artifact_id for target, artifact_id in artifact_refs
        if target in _SYNTHETIC_ARTIFACT_TARGETS
    }
    result: dict[str, bool | None] = {}
    for artifact_id in sorted(relevant_ids):
        markers = origins.get(artifact_id, set())
        value, status = _synthetic_consensus(markers)
        result[artifact_id] = value
        if status == "conflict":
            gaps["artifact_synthetic_provenance_conflict"] += 1
        elif status == "undeclared":
            gaps["artifact_synthetic_provenance_undeclared"] += 1
    return result


def _normal_baseline_synthetic_marker(
    event: Mapping[str, Any], included: list[dict[str, Any]], gaps: Counter[str],
) -> bool | None:
    row = event.get("row") if isinstance(event.get("row"), Mapping) else event
    event_id = str(row.get("id"))
    markers = [
        _synthetic_marker(item["payload"])
        for item in included
        if item["row"].get("kind") == "truth_revision"
        and str(item["row"].get("event_id") or item["payload"].get("event_id") or "") == event_id
    ]
    trusted, status = _synthetic_consensus(markers)
    if status == "conflict":
        gaps["normal_baseline_source_truth_provenance_conflict"] += 1
    elif status == "undeclared" and markers:
        gaps["normal_baseline_source_truth_provenance_undeclared"] += 1
    raw_provenance = _json_object(row.get("provenance")) or {}
    untrusted = raw_provenance.get("is_synthetic")
    if isinstance(untrusted, bool):
        if trusted is not None and trusted != untrusted:
            gaps["normal_baseline_synthetic_provenance_conflict"] += 1
            return None
        if trusted is None:
            gaps["normal_baseline_untrusted_external_provenance_ignored"] += 1
    return trusted


def _normal_baseline_projection(
    event: Mapping[str, Any], freeze_text: str, freeze_dt: datetime, *, is_synthetic: bool | None = None,
) -> dict[str, Any]:
    row = event.get("row") if isinstance(event.get("row"), Mapping) else event
    anchor_start = _maybe_utc(row.get("occurred_at"))
    anchor_end = _maybe_utc(row.get("occurred_at_end"))
    if anchor_start is None:
        raise ReviewReadError("normal_baseline_anchor_time_unavailable")
    projected_start = anchor_start + timedelta(days=7)
    projected_end = anchor_end + timedelta(days=7) if anchor_end is not None else None
    event_id = str(row.get("id"))
    basis = str(row.get("time_basis") or "unknown")
    provenance = _json_object(row.get("provenance")) or {}
    raw_precision = provenance.get("time_precision") or provenance.get("precision")
    if isinstance(raw_precision, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", raw_precision):
        precision = raw_precision
        precision_reason = None
    elif projected_end is not None:
        precision = "range"
        precision_reason = None
    elif basis == "post_time_proxy":
        precision = "proxy"
        precision_reason = "source_event_records_post_time_proxy_without_finer_precision"
    else:
        precision = "unknown"
        precision_reason = "source_event_does_not_record_precision"
    target_time = projected_end or projected_start
    status = "expired" if freeze_dt > target_time else "baseline"
    scope_value = str(row.get("scope") or "unknown")
    return {
        "id": f"normal-weekly-compat-{event_id}",
        "forecast_id": f"normal-weekly-compat-{event_id}",
        "series_id": "normal-weekly-compatibility",
        "event_id": row.get("id"),
        "revision": None,
        "target": "NORMAL_WEEKLY",
        "scope": {
            "value": scope_value,
            "certainty": "inherited_from_full_anchor" if scope_value != "unknown" else "unknown",
        },
        "record_kind": "baseline",
        "method": None,
        "basis": "user_full_plus_7d",
        "predicted_start": utc_text(projected_start),
        "predicted_end": utc_text(projected_end) if projected_end is not None else None,
        "prediction_form": "range" if projected_end is not None else "unknown",
        "source_timezone": None,
        "precision": precision,
        "precision_reason": precision_reason,
        "time_basis": basis,
        "source_anchor_at": str(row.get("occurred_at")),
        "source_anchor_time_basis": basis,
        "anchor_precision": precision,
        "judgement_as_of": None,
        "recorded_at": None,
        "output_available_at": None,
        "status": status,
        "source_kind": "normal_baseline_compatibility_view",
        "selection_basis": "latest_formal_full_anchor_as_of_freeze",
        "version_history_complete": False,
        "is_synthetic": is_synthetic if isinstance(is_synthetic, bool) else None,
        "is_dependency": True,
        "dependency_reason": "normal_baseline_compatibility_view_has_no_historical_version_record",
    }


def _ledger_evidence_projection(
    identifier: str,
    payload: Mapping[str, Any],
    source_refs: list[Mapping[str, Any]],
    context: PrivacyContext,
    policy_map: Mapping[tuple[int, str], bool | None],
    current_posts: Mapping[int, str],
) -> dict[str, Any]:
    safe_sources: list[dict[str, Any]] = []
    restricted = False
    for source in source_refs:
        post_id = source.get("post_id")
        try:
            post_id_int = int(post_id) if post_id is not None else None
        except (TypeError, ValueError):
            post_id_int = None
        current_hash = current_posts.get(post_id_int) if post_id_int is not None else None
        if current_hash is not None and policy_map.get((post_id_int, current_hash)) is False:
            restricted = True
        role = source.get("role")
        relation = source.get("relation_to_target")
        safe_sources.append({
            "tweet_id": source.get("tweet_id"),
            "author": source.get("author"),
            "author_role": role,
            "role": role,
            "relation": relation,
            "relation_to_target": relation,
            "parent_tweet_id": source.get("parent_tweet_id"),
            "relation_source": source.get("relation_source"),
            "source_version": source.get("source_version"),
            "policy_version": source.get("policy_version"),
        })
    text = payload.get("text") if isinstance(payload.get("text"), str) else None
    projection = {
        "text": None if restricted else text,
        "content_hash": payload.get("content_hash"),
        "source_refs": safe_sources,
        "historical_policy_status": "current_restriction_applied" if restricted else "current_policy_not_restricting_or_unknown",
        "omission_reason": "current_content_policy_restricts_export" if restricted else None,
        "redacted": restricted,
        "redaction_categories": ["current_content_policy_restriction"] if restricted else [],
        "is_parent": any(str(source.get("role") or "").startswith("parent") for source in source_refs),
    }
    if safe_sources:
        first = safe_sources[0]
        for key in ("tweet_id", "author", "author_role", "parent_tweet_id", "relation_source", "relation", "relation_to_target", "role"):
            projection[key] = first.get(key)
    return _dto(projection, _EVIDENCE_FIELDS, context, identifier=identifier)


def _payload_time(payload: Mapping[str, Any], primary: str, fallback: object) -> object:
    value = payload.get(primary)
    return value if isinstance(value, str) else fallback


def _row_scope(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str | None:
    return _id(row.get("series_id") or payload.get("series_id"))


def _row_forecast(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str | None:
    return _id(row.get("forecast_id") or payload.get("forecast_id"))


def _row_attempt(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str | None:
    return _id(row.get("attempt_id") or payload.get("attempt_id"))


def _row_run(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str | None:
    return _id(row.get("run_id") or payload.get("run_id"))


def _dto(base: Mapping[str, Any], fields: set[str], context: PrivacyContext, *, identifier: str, source_id: str | None = None) -> dict[str, Any]:
    value = dict(base)
    safe = sanitize_dto(value, fields, context)
    safe["id"] = identifier
    if source_id:
        safe["source_record_id"] = source_id
    return safe


def _reference(
    target: str,
    identifier: str | None,
    available: set[str],
    missing_reason: str,
    placeholders: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if identifier and identifier in available:
        placeholder = (placeholders or {}).get(identifier)
        if placeholder:
            return {"target": target, "id": identifier, "status": "missing", "reason": str(placeholder.get("omission_reason") or missing_reason)}
        return {"target": target, "id": identifier, "status": "included", "reason": None}
    return {"target": target, "id": identifier, "status": "missing", "reason": missing_reason}


def _canonical_row_payload(row: Mapping[str, Any]) -> dict[str, Any] | None:
    return _json_object(row.get("payload_json"))


def _selection_matches(
    row: Mapping[str, Any], payload: Mapping[str, Any], start: datetime | None, end: datetime | None, series_id: str | None
) -> tuple[bool, bool, str]:
    series = _row_scope(row, payload)
    timestamp, basis = _activity_time(row)
    in_window = _in_window(timestamp, start, end)
    if series_id is not None:
        return series == series_id and (in_window if start is not None or end is not None else True), in_window, basis
    return in_window, in_window, basis


def _safe_reason_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate[:80] if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", candidate) else None


def _build_ledger_records(
    included: list[dict[str, Any]],
    context: PrivacyContext,
    gaps: Counter[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    forecasts: list[dict[str, Any]] = []
    output_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    attempts_by_key: dict[str, dict[str, Any]] = {}
    truth: list[dict[str, Any]] = []
    runtime: list[dict[str, Any]] = []
    forecast_ids_seen: set[str] = set()
    run_payloads = {
        str(_row_run(item["row"], item["payload"])): item["payload"]
        for item in included
        if item["row"].get("kind") == "run_started" and _row_run(item["row"], item["payload"])
    }
    forecast_synthetic: dict[str, bool] = {}
    for item in included:
        row, payload = item["row"], item.get("payload") or {}
        if row.get("kind") == "output_committed":
            forecast_id = _row_forecast(row, payload)
            run_id = _row_run(row, payload)
            run_payload = run_payloads.get(str(run_id)) if run_id else None
            if forecast_id and run_payload is not None and isinstance(run_payload.get("is_synthetic"), bool):
                forecast_synthetic[forecast_id] = bool(run_payload["is_synthetic"])
    for item in included:
        row, payload = item["row"], item.get("payload") or {}
        kind = str(row.get("kind") or "")
        row_id, seq = _record_id(row), row.get("seq")
        series_id = _row_scope(row, payload)
        forecast_id = _row_forecast(row, payload)
        attempt_id = _row_attempt(row, payload)
        run_id = _row_run(row, payload)
        occurred = row.get("occurred_at")
        recorded = row.get("recorded_at")
        common = {
            **payload,
            "record_id": row_id,
            "series_id": series_id or payload.get("series_id"),
            "forecast_id": forecast_id or payload.get("forecast_id"),
            "attempt_id": attempt_id or payload.get("attempt_id"),
            "run_id": run_id or payload.get("run_id"),
            "occurred_at": occurred or payload.get("occurred_at"),
            "recorded_at": recorded,
        }
        if row.get("payload_invalid"):
            gaps["ledger_payload_invalid"] += 1
        if kind in {"forecast_version", "normal_baseline"}:
            safe_id = forecast_id or str(payload.get("forecast_id") or f"legacy-ledger-forecast-{seq}")
            if safe_id in forecast_ids_seen:
                raise ReviewReadError("duplicate_forecast_version_identity")
            forecast_ids_seen.add(safe_id)
            base = dict(common)
            forecast_body = payload.get("forecast")
            if isinstance(forecast_body, Mapping):
                base.update(forecast_body)
            base.setdefault("forecast_id", forecast_id)
            base.setdefault("record_kind", "baseline" if kind == "normal_baseline" else None)
            if safe_id in forecast_synthetic:
                base["is_synthetic"] = forecast_synthetic[safe_id]
            elif "is_synthetic" not in base:
                base["is_synthetic"] = None
            item_out = _dto(base, _FORECAST_FIELDS, context, identifier=safe_id, source_id=row_id)
            item_out["ledger_seq"] = seq
            item_out["ledger_kind"] = kind
            item_out["is_dependency"] = item.get("dependency_reason") is not None
            item_out["dependency_reason"] = item.get("dependency_reason")
            forecasts.append(item_out)
        elif kind in {"output_committed", "output_observed"}:
            output_id = _id(payload.get("output_id")) or row_id
            output_rows[output_id].append(item)
        elif kind in {"attempt_started", "attempt_event", "run_started", "recovery_observed"}:
            key = f"attempt:{attempt_id}" if attempt_id else f"run:{run_id or row_id}"
            base = attempts_by_key.setdefault(key, {
                "id": attempt_id or f"run-lifecycle-{run_id or row_id}",
                "attempt_id": attempt_id,
                "series_id": series_id,
                "forecast_id": forecast_id,
                "run_id": run_id,
                "record_type": "attempt" if attempt_id else "run_lifecycle",
                "is_attempt": attempt_id is not None,
                "is_synthetic": (run_payloads.get(str(run_id)) or {}).get("is_synthetic") if run_id else None,
                "events": [],
                "is_dependency": item.get("dependency_reason") is not None,
                "dependency_reason": item.get("dependency_reason"),
                "redacted": False,
                "redaction_categories": [],
            })
            raw_event_type = payload.get("event_type")
            real_event_type = (
                _safe_reason_code(raw_event_type) if isinstance(raw_event_type, str)
                else (None if kind == "attempt_event" else kind)
            )
            if raw_event_type and real_event_type is None:
                gaps["unsafe_attempt_event_type_omitted"] += 1
            status_value = payload.get("terminal_status") or real_event_type
            safe_status = _safe_reason_code(status_value) if isinstance(status_value, str) else None
            reason_code = _safe_reason_code(payload.get("reason_code") or payload.get("status_reason"))
            if (payload.get("reason_code") or payload.get("status_reason")) and reason_code is None:
                gaps["unsafe_attempt_reason_code_omitted"] += 1
            event_source = {
                **common,
                "stage": payload.get("stage") or payload.get("phase") or kind,
                "event_type": real_event_type,
                "status": safe_status,
                "reason_code": reason_code,
                "attempt_started_at": payload.get("attempt_started_at") or (occurred if kind == "attempt_started" else None),
                "attempt_finished_at": payload.get("attempt_finished_at") or payload.get("actual_finished_at"),
                "output_available_at": payload.get("output_available_at"),
                "response_received_at": payload.get("response_received_at") or payload.get("received_at"),
                "usage": payload.get("usage"),
                "usage_source": payload.get("usage_source"),
                "source_status": payload.get("source_status") if isinstance(payload.get("source_status"), str) and payload.get("source_status") in {"KNOWN", "UNKNOWN"} else None,
                "source_attempt_ref": (
                    {"target": "attempts", "id": str(payload.get("source_attempt_id")), "status": "included", "reason": None}
                    if payload.get("source_status") == "KNOWN" and isinstance(payload.get("source_attempt_id"), str)
                    else None
                ),
                "clock_anomaly": _safe_reason_code(payload.get("clock_anomaly")),
                "time_limitation": _safe_reason_code(payload.get("time_limitation")),
                "publication_status": _safe_reason_code(payload.get("publication_status")),
                "failure_terminal": payload.get("failure_terminal") if isinstance(payload.get("failure_terminal"), bool) else None,
                "structured_output": payload.get("structured_output"),
                "input_version_delta": payload.get("input_version_delta"),
                "is_synthetic": base.get("is_synthetic"),
            }
            safe_event = _dto(event_source, _ATTEMPT_FIELDS, context, identifier=row_id, source_id=row_id)
            safe_event["ledger_seq"] = seq
            safe_event["ledger_kind"] = kind
            safe_event["attempt_id"] = attempt_id
            safe_event["dependency_reason"] = item.get("dependency_reason")
            base["events"].append(safe_event)
            base["is_dependency"] = bool(base.get("is_dependency") and item.get("dependency_reason") is not None)
            if base.get("series_id") is None:
                base["series_id"] = series_id
            if base.get("forecast_id") is None:
                base["forecast_id"] = forecast_id
            if base.get("run_id") is None:
                base["run_id"] = run_id
        elif kind == "truth_revision":
            base = dict(common)
            true_fields = payload.get("true_fields")
            if isinstance(true_fields, Mapping):
                base.update(true_fields)
            base.setdefault("event_id", row.get("event_id") or payload.get("event_id"))
            base.setdefault("truth_revision", payload.get("revision") or row.get("revision"))
            base.setdefault("previous_revision", payload.get("previous_revision"))
            base.setdefault("truth_status", payload.get("truth_status"))
            base.setdefault("adjudication_version", payload.get("adjudication_version"))
            base.setdefault("actual_event_type", (true_fields or {}).get("actual_event_type") if isinstance(true_fields, Mapping) else None)
            base.setdefault("reason_summary", payload.get("reason"))
            base["is_synthetic"] = payload.get("is_synthetic") if isinstance(payload.get("is_synthetic"), bool) else None
            item_out = _dto(base, _TRUTH_FIELDS, context, identifier=row_id, source_id=row_id)
            item_out["ledger_seq"] = seq
            item_out["ledger_kind"] = kind
            item_out["is_dependency"] = item.get("dependency_reason") is not None
            item_out["dependency_reason"] = item.get("dependency_reason")
            truth.append(item_out)
        elif kind == "runtime_identity":
            item_out = _dto(common, _RUNTIME_FIELDS, context, identifier=f"runtime-ledger-{row_id}", source_id=row_id)
            item_out["ledger_seq"] = seq
            item_out["ledger_kind"] = kind
            item_out["is_dependency"] = item.get("dependency_reason") is not None
            item_out["dependency_reason"] = item.get("dependency_reason")
            runtime.append(item_out)
        else:
            gaps["unsupported_ledger_kind"] += 1
    outputs: list[dict[str, Any]] = []
    for output_id, records in output_rows.items():
        records.sort(key=lambda item: int(item["row"].get("seq") or 0))
        committed_records = [item for item in records if item["row"].get("kind") == "output_committed"]
        if len(committed_records) > 1:
            raise ReviewReadError("duplicate_committed_output_identity")
        committed = committed_records[0] if committed_records else None
        observations = [item for item in records if item["row"].get("kind") == "output_observed"]
        canonical = committed or records[0]
        row, payload = canonical["row"], canonical["payload"]
        base = {
            **payload,
            "record_id": _record_id(row),
            "output_id": output_id,
            "forecast_id": _row_forecast(row, payload),
            "series_id": _row_scope(row, payload),
            "attempt_id": _row_attempt(row, payload) or _id(payload.get("accepted_attempt_id")),
            "run_id": _row_run(row, payload),
            "recorded_at": row.get("recorded_at"),
            "occurred_at": row.get("occurred_at"),
            "output_kind": "judge_structured_output" if committed else "observed_without_committed_record",
            "is_dependency": any(item.get("dependency_reason") is not None for item in records),
            "dependency_reason": next((item.get("dependency_reason") for item in records if item.get("dependency_reason")), None),
        }
        validation = payload.get("validation")
        if isinstance(validation, Mapping):
            base["validation_status"] = validation.get("status")
            base["status"] = validation.get("status")
        structured = payload.get("structured_output")
        if isinstance(structured, Mapping):
            picked = {key: structured[key] for key in _OUTPUT_STRUCTURED_FIELDS if key in structured}
            base["structured_output"] = picked
            if "reason_summary" in structured:
                base["reason_summary"] = structured.get("reason_summary")
            if "model" in structured:
                base["declared_model"] = structured.get("model")
            if "prompt_version" in structured:
                base["prompt_version"] = structured.get("prompt_version")
        else:
            base.pop("structured_output", None)
        observed_data: list[dict[str, object]] = []
        for observation in observations:
            observation_payload = observation["payload"]
            observed_at = observation_payload.get("observed_at")
            source = observation_payload.get("source")
            observed_data.append({
                "record_id": _record_id(observation["row"]),
                "observed_at": observed_at if isinstance(observed_at, str) else None,
                "source": source if isinstance(source, str) else None,
                "clock_anomaly": _safe_reason_code(observation_payload.get("clock_anomaly")),
                "time_limitation": _safe_reason_code(observation_payload.get("time_limitation")),
            })
        observed_data.sort(key=lambda item: (str(item.get("observed_at") or ""), str(item.get("record_id") or "")))
        if observed_data:
            first_observation = observed_data[0]
            base["observed_at"] = first_observation["observed_at"]
            base["availability_source"] = first_observation["source"]
            base["observation_record_id"] = first_observation["record_id"]
            # The first formal read is an upper bound: the output existed by then.
            base["output_available_at"] = first_observation["observed_at"]
            base["availability_observations"] = observed_data
        elif payload.get("output_available_at") is not None:
            base["output_available_at"] = payload.get("output_available_at")
        else:
            base["output_available_at"] = None
        run_payload = run_payloads.get(str(base.get("run_id"))) if base.get("run_id") else None
        if run_payload is not None and isinstance(run_payload.get("is_synthetic"), bool):
            base["is_synthetic"] = bool(run_payload["is_synthetic"])
        else:
            base["is_synthetic"] = None
        item_out = _dto(base, _OUTPUT_FIELDS, context, identifier=output_id, source_id=_record_id(row))
        item_out["ledger_seq"] = int(row.get("seq") or 0)
        item_out["ledger_kind"] = "output_committed" if committed else "output_observed"
        item_out["dependency_reason"] = base.get("dependency_reason")
        outputs.append(item_out)
    outputs.sort(key=lambda item: (int(item.get("ledger_seq") or 0), str(item.get("id"))))
    attempts: list[dict[str, Any]] = []
    for key in sorted(attempts_by_key):
        attempt = attempts_by_key[key]
        attempt["events"].sort(key=lambda event: (event.get("ledger_seq") if event.get("ledger_seq") is not None else -1, event.get("id", "")))
        attempts.append(attempt)
    forecasts.sort(key=lambda item: (str(item.get("series_id") or ""), int(item.get("revision") or 0), str(item.get("id"))))
    outputs.sort(key=lambda item: (int(item.get("ledger_seq") or 0), str(item.get("id"))))
    truth.sort(key=lambda item: (int(item.get("ledger_seq") or 0), str(item.get("id"))))
    runtime.sort(key=lambda item: str(item.get("id")))
    return forecasts, outputs, attempts, truth, runtime


def _attach_references(
    collections: Mapping[str, list[dict[str, Any]]],
    included: list[dict[str, Any]],
    artifact_id_map: Mapping[tuple[str, str], str],
    missing_artifact_map: Mapping[tuple[str, str], tuple[str, str]],
    processing_output_id_by_reference: Mapping[tuple[str, str], str] | None = None,
) -> None:
    forecast_ids = {str(row.get("id")) for row in collections.get("forecasts", [])}
    attempt_ids = {str(row.get("id")) for row in collections.get("attempts", [])}

    # Every non-resolving identity is represented by an explicit package-local
    # placeholder, so a missing ref is never silently dangling.
    event_truth: dict[str, str] = {}
    for truth_row in collections.get("truth_revisions", []):
        if truth_row.get("event_id") is not None:
            event_truth[str(truth_row["event_id"])] = str(truth_row["id"])
    for item in included:
        row, payload = item["row"], item["payload"]
        forecast_id = _row_forecast(row, payload)
        if forecast_id and forecast_id not in forecast_ids:
            collections["forecasts"].append({
                "id": forecast_id, "forecast_id": forecast_id, "placeholder": True,
                "omission_reason": "forecast_version_not_in_package", "redacted": False, "redaction_categories": [],
            })
            forecast_ids.add(forecast_id)
        attempt_id = _row_attempt(row, payload)
        if attempt_id and attempt_id not in attempt_ids:
            collections["attempts"].append({
                "id": attempt_id, "attempt_id": attempt_id, "record_type": "missing_attempt",
                "is_attempt": True, "events": [], "placeholder": True,
                "omission_reason": "attempt_not_recorded_or_outside_freeze", "redacted": False, "redaction_categories": [],
            })
            attempt_ids.add(attempt_id)
        source_attempt_id = payload.get("source_attempt_id")
        if payload.get("source_status") == "KNOWN" and isinstance(source_attempt_id, str) and source_attempt_id not in attempt_ids:
            collections["attempts"].append({
                "id": source_attempt_id, "attempt_id": source_attempt_id, "record_type": "missing_attempt",
                "is_attempt": True, "events": [], "placeholder": True,
                "omission_reason": "known_cache_source_attempt_not_available_as_of_freeze",
                "redacted": False, "redaction_categories": [],
            })
            attempt_ids.add(source_attempt_id)
        event_id = row.get("event_id") or payload.get("event_id")
        if event_id is not None and str(event_id) not in event_truth:
            placeholder_id = f"missing-truth-event-{event_id}"
            collections["truth_revisions"].append({
                "id": placeholder_id, "event_id": str(event_id), "placeholder": True,
                "omission_reason": "truth_revision_not_in_package", "redacted": False, "redaction_categories": [],
            })
            event_truth[str(event_id)] = placeholder_id

    included_by_record = {_record_id(item["row"]): item for item in included}
    id_sets = {name: {str(row.get("id")) for row in rows} for name, rows in collections.items()}
    placeholders = {
        name: {str(row.get("id")): row for row in rows if row.get("placeholder") is True}
        for name, rows in collections.items()
    }

    def attach(row: dict[str, Any], collection_name: str) -> None:
        references = dict(row.get("references") or {})
        forecast_id = _id(row.get("forecast_id"))
        if forecast_id:
            references["forecast"] = _reference("forecasts", forecast_id, id_sets.get("forecasts", set()), "forecast_version_not_in_package", placeholders.get("forecasts"))
        attempt_id = _id(row.get("attempt_id"))
        if attempt_id:
            references["attempt"] = _reference("attempts", attempt_id, id_sets.get("attempts", set()), "attempt_not_recorded_or_outside_freeze", placeholders.get("attempts"))
        source_attempt_ref = row.get("source_attempt_ref")
        if isinstance(source_attempt_ref, Mapping):
            source_id = _id(source_attempt_ref.get("id"))
            row["source_attempt_ref"] = _reference(
                "attempts", source_id, id_sets.get("attempts", set()),
                "known_cache_source_attempt_not_available_as_of_freeze", placeholders.get("attempts"),
            )
        event_id = _id(row.get("event_id"))
        if event_id and collection_name != "truth_revisions":
            truth_id = event_truth.get(event_id)
            references["truth"] = _reference("truth_revisions", truth_id, id_sets.get("truth_revisions", set()), "truth_revision_not_in_package", placeholders.get("truth_revisions"))

        source_ids: set[str] = set()
        if row.get("source_record_id"):
            source_ids.add(str(row["source_record_id"]))
        for observation in row.get("availability_observations", []):
            if isinstance(observation, Mapping) and observation.get("record_id"):
                source_ids.add(str(observation["record_id"]))
        artifact_refs: set[tuple[str, str]] = set()
        for source_id in source_ids:
            source = included_by_record.get(source_id)
            if source:
                artifact_refs.update(source.get("artifact_refs", []))
        safe_artifact_refs = []
        for target, raw_id in sorted(artifact_refs):
            missing = missing_artifact_map.get((target, raw_id))
            resolved = (
                (processing_output_id_by_reference or {}).get((str(row.get("source_record_id") or ""), raw_id))
                if target == "outputs" else None
            )
            if resolved is None:
                for source_id in source_ids:
                    resolved = (processing_output_id_by_reference or {}).get((source_id, raw_id))
                    if resolved is not None:
                        break
            if resolved is None:
                resolved = artifact_id_map.get((target, raw_id))
            if target == "outputs" and resolved == str(row.get("id")):
                continue
            if missing:
                safe_artifact_refs.append({"target": target, "id": missing[0], "status": "missing", "reason": missing[1]})
            elif resolved:
                safe_artifact_refs.append({"target": target, "id": resolved, "status": "included", "reason": None})
        if safe_artifact_refs:
            references["artifacts"] = safe_artifact_refs
        if references:
            row["references"] = references

    for collection_name, rows in collections.items():
        for row in rows:
            attach(row, collection_name)
            if collection_name == "attempts":
                for event in row.get("events", []):
                    if isinstance(event, dict):
                        attach(event, collection_name)


def _synthetic_provenance(collections: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    declared_synthetic = 0
    declared_real = 0
    legacy_undeclared = 0
    undeclared = 0
    for rows in collections.values():
        for row in rows:
            if row.get("placeholder") is True:
                continue
            value = row.get("is_synthetic")
            if value is True:
                declared_synthetic += 1
            elif value is False:
                declared_real += 1
            else:
                legacy = (
                    str(row.get("id") or "").startswith("legacy-")
                    or str(row.get("source_mode") or "").startswith("legacy_")
                    or str(row.get("source_kind") or "").startswith("legacy_")
                    or "legacy_judgement_id" in row
                )
                if legacy:
                    legacy_undeclared += 1
                else:
                    undeclared += 1
    if declared_synthetic and declared_real:
        status = "MIXED"
    elif declared_synthetic:
        status = "SYNTHETIC_WITH_LEGACY_UNDECLARED" if legacy_undeclared else (
            "SYNTHETIC_WITH_UNDECLARED" if undeclared else "SYNTHETIC"
        )
    elif declared_real:
        status = "REAL_WITH_LEGACY_UNDECLARED" if legacy_undeclared else (
            "REAL_WITH_UNDECLARED" if undeclared else "REAL"
        )
    elif legacy_undeclared:
        status = "LEGACY_UNDECLARED"
    elif undeclared:
        status = "UNDECLARED"
    else:
        status = "EMPTY"
    return {
        "status": status,
        "counts": {
            "declared_synthetic": declared_synthetic,
            "declared_real": declared_real,
            "legacy_undeclared": legacy_undeclared,
            "undeclared": undeclared,
        },
        "basis": "frozen DTO is_synthetic declarations; legacy and unknown provenance remain undeclared",
    }


def read_review(
    connection: sqlite3.Connection,
    selection: Mapping[str, object],
    freeze_at: str,
    high_water: int | None = None,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> dict[str, Any]:
    """Read a bounded review timeline from one query-only SQLite snapshot."""
    if not isinstance(selection, Mapping):
        raise ReviewReadError("selection_must_be_object")
    if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records <= 0:
        raise ReviewReadError("max_records_must_be_positive")
    start_dt = _utc(selection["start"], "start")[0] if selection.get("start") is not None else None
    end_dt = _utc(selection["end"], "end")[0] if selection.get("end") is not None else None
    freeze_dt, freeze_text = _utc(freeze_at, "freeze_at")
    raw_series_id = selection.get("series_id")
    if raw_series_id is not None and (not isinstance(raw_series_id, str) or not raw_series_id.strip() or len(raw_series_id) > 200):
        raise ReviewReadError("series_id_must_be_nonempty_string")
    series_id = raw_series_id.strip() if isinstance(raw_series_id, str) else None
    if start_dt and end_dt and start_dt >= end_dt:
        raise ReviewReadError("window_start_must_precede_end")
    if start_dt is None and end_dt is None and not series_id:
        raise ReviewReadError("selection_requires_time_bound_or_series")
    if high_water is not None and (isinstance(high_water, bool) or not isinstance(high_water, int) or high_water < 0):
        raise ReviewReadError("high_water_must_be_nonnegative_integer")

    if connection.in_transaction:
        raise ReviewReadError("connection_must_be_idle_before_read")
    connection.execute("PRAGMA query_only=ON")
    if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 1:
        raise ReviewReadError("sqlite_query_only_unavailable")
    connection.execute("BEGIN")
    try:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        ledger_available = "prediction_ledger" in tables
        artifacts_available = "prediction_artifacts" in tables
        max_seq = 0
        ledger_rows: list[dict[str, Any]] = []
        gaps: Counter[str] = Counter()
        if ledger_available:
            columns = _columns(connection, "prediction_ledger")
            missing_columns = sorted(set(_LEDGER_COLUMNS) - columns)
            if missing_columns:
                gaps["prediction_ledger_schema_incomplete"] += 1
                effective_high_water = None
            elif int(connection.execute("SELECT COUNT(*) FROM prediction_ledger").fetchone()[0]) > MAX_SOURCE_ROWS:
                raise ReviewRangeTooLarge(f"source_scan_exceeds_{MAX_SOURCE_ROWS}; narrow the series or window")
            else:
                raw_rows = _read_rows(connection, "prediction_ledger", _LEDGER_COLUMNS, order="seq")
                frozen_seq = 0
                for row in raw_rows:
                    recorded_dt = _maybe_utc(row.get("recorded_at"))
                    if recorded_dt is not None and recorded_dt <= freeze_dt:
                        frozen_seq = max(frozen_seq, int(row.get("seq") or 0))
                effective_high_water = min(high_water, frozen_seq) if high_water is not None else frozen_seq
                for row in raw_rows:
                    if int(row.get("seq") or 0) > effective_high_water:
                        continue
                    recorded_dt = _maybe_utc(row.get("recorded_at"))
                    if recorded_dt is None:
                        gaps["ledger_recorded_time_invalid"] += 1
                        continue
                    if recorded_dt > freeze_dt:
                        continue
                    payload = _canonical_row_payload(row)
                    ledger_rows.append({
                        "row": row,
                        "payload": payload or {},
                        "payload_invalid": payload is None,
                        "artifact_refs": _payload_refs(payload or {}),
                        "artifact_ref_details": _payload_ref_details(payload or {}),
                    })
                max_seq = effective_high_water
        else:
            effective_high_water = None

        # Load legacy event identities before ledger closure so any selected event
        # can pull its complete frozen modern truth chain by event_id.
        legacy_judgements, legacy_events, _ = _load_legacy(connection, freeze_dt)
        normal_baseline_requested = series_id in {None, "normal-weekly-compatibility"}
        normal_anchor_candidates = []
        if normal_baseline_requested:
            for event in legacy_events:
                row = event["row"]
                occurred = _maybe_utc(row.get("occurred_at"))
                ended = _maybe_utc(row.get("occurred_at_end"))
                if (row.get("event_type") == "FULL_RESET" and occurred is not None and occurred <= freeze_dt
                        and (ended is None or ended <= freeze_dt)):
                    normal_anchor_candidates.append((occurred, int(row.get("id") or 0), event))
        normal_anchor_event = max(normal_anchor_candidates, key=lambda entry: (entry[0], entry[1]))[2] if normal_anchor_candidates else None
        legacy_event_seed_ids = {
            str(event["row"].get("id"))
            for event in legacy_events
            if series_id is None and _in_window(
                _maybe_utc(event["row"].get("occurred_at")) or event.get("recorded_at"), start_dt, end_dt
            )
        }
        if normal_anchor_event is not None:
            legacy_event_seed_ids.add(str(normal_anchor_event["row"].get("id")))

        selected_by_seq: dict[int, dict[str, Any]] = {}
        seed_seqs: set[int] = set()
        for item in ledger_rows:
            matched, in_window, basis = _selection_matches(item["row"], item["payload"], start_dt, end_dt, series_id)
            item["window_time_basis"] = basis
            if matched:
                seq = int(item["row"]["seq"])
                item["dependency_reason"] = None
                selected_by_seq[seq] = item
                seed_seqs.add(seq)

        by_forecast = {_row_forecast(item["row"], item["payload"]): item for item in ledger_rows if item["row"].get("kind") == "forecast_version" and _row_forecast(item["row"], item["payload"])}
        by_attempt: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_runtime_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in ledger_rows:
            payload, row = item["payload"], item["row"]
            if _row_attempt(row, payload):
                by_attempt[str(_row_attempt(row, payload))].append(item)
            if _row_run(row, payload):
                by_run[str(_row_run(row, payload))].append(item)
            if row.get("kind") == "runtime_identity" and payload.get("runtime_id"):
                by_runtime_id[str(payload["runtime_id"])].append(item)
            event_id = row.get("event_id") or payload.get("event_id")
            if event_id is not None and row.get("kind") == "truth_revision":
                by_event[str(event_id)].append(item)

        explicit_event_seeds: set[str] = set(legacy_event_seed_ids)
        for item in selected_by_seq.values():
            explicit_event_seeds.update(_explicit_event_ids(item["payload"]))
            event_id = item["row"].get("event_id") or item["payload"].get("event_id")
            if event_id is not None:
                explicit_event_seeds.add(str(event_id))

        queue = list(selected_by_seq.values())
        for event_id in sorted(explicit_event_seeds):
            for candidate in by_event.get(event_id, []):
                seq = int(candidate["row"].get("seq") or 0)
                if seq not in selected_by_seq:
                    candidate["dependency_reason"] = "truth_revision_event_closure"
                    selected_by_seq[seq] = candidate
                    queue.append(candidate)
        while queue:
            current = queue.pop()
            row, payload = current["row"], current["payload"]
            current_kind = str(row.get("kind") or "")
            related: list[tuple[dict[str, Any], str]] = []
            forecast = _row_forecast(row, payload)
            attempt = _row_attempt(row, payload)
            run = _row_run(row, payload)
            if forecast:
                if current_kind == "forecast_version":
                    previous = _id(payload.get("previous_id") or payload.get("previous_forecast_id"))
                    if previous and previous in by_forecast:
                        related.append((by_forecast[previous], "previous_forecast_version"))
                    elif previous:
                        gaps["previous_forecast_version_missing"] += 1
                related.extend((linked, "forecast_linked_attempt_or_output") for linked in ledger_rows if _row_forecast(linked["row"], linked["payload"]) == forecast and linked is not current)
            if attempt:
                related.extend((linked, "attempt_event_closure") for linked in by_attempt.get(attempt, []) if linked is not current)
            if run:
                related.extend((linked, "run_event_closure") for linked in by_run.get(run, []) if linked is not current)
            explicit_event_ids = _explicit_event_ids(payload)
            event_id = row.get("event_id") or payload.get("event_id")
            if event_id is not None:
                explicit_event_ids.add(str(event_id))
            for linked_event_id in explicit_event_ids:
                related.extend((linked, "truth_revision_event_closure") for linked in by_event.get(linked_event_id, []) if linked is not current)
            source_status = payload.get("source_status")
            source_attempt_id = payload.get("source_attempt_id")
            if source_status == "KNOWN" and isinstance(source_attempt_id, str) and source_attempt_id:
                related.extend((linked, "known_cache_source_attempt") for linked in by_attempt.get(source_attempt_id, []) if linked is not current)
            source_run_id = payload.get("source_run_id")
            if source_status == "KNOWN" and isinstance(source_run_id, str) and source_run_id:
                related.extend((linked, "known_cache_source_run") for linked in by_run.get(source_run_id, []) if linked is not current)
            runtime_object = payload.get("runtime") if isinstance(payload.get("runtime"), Mapping) else {}
            runtime_id = _id(runtime_object.get("runtime_id")) if current_kind == "run_started" else None
            if runtime_id:
                related.extend((linked, "runtime_identity_for_run") for linked in by_runtime_id.get(runtime_id, []) if linked is not current)
            for candidate, reason in related:
                seq = int(candidate["row"]["seq"])
                if seq not in selected_by_seq:
                    candidate["dependency_reason"] = reason
                    selected_by_seq[seq] = candidate
                    queue.append(candidate)

        # Read explicitly referenced frozen inputs from the complete selected
        # ledger closure (including run/input dependencies), then resolve their
        # event IDs only against the frozen/high-water-filtered by_event index.
        frozen_input_event_ids: set[str] = set()
        for item in selected_by_seq.values():
            frozen_input_event_ids.update(_explicit_event_ids(item["payload"]))
        if artifacts_available and selected_by_seq:
            artifact_columns = _columns(connection, "prediction_artifacts")
            if set(_ARTIFACT_COLUMNS).issubset(artifact_columns):
                input_artifact_ids = sorted({
                    artifact_id
                    for item in selected_by_seq.values()
                    for target, artifact_id, _, _ in item["artifact_ref_details"]
                    if target == "input_snapshots"
                })
                for artifact_id in input_artifact_ids:
                    raw_artifact = connection.execute(
                        "SELECT id,kind,content_hash,payload_json,recorded_at FROM prediction_artifacts WHERE id=?",
                        (artifact_id,),
                    ).fetchone()
                    if raw_artifact is None:
                        continue
                    artifact = dict(zip(_ARTIFACT_COLUMNS, raw_artifact))
                    recorded = _maybe_utc(artifact.get("recorded_at"))
                    if recorded is None or recorded > freeze_dt:
                        continue
                    frozen_payload = _json_object(artifact.get("payload_json"))
                    if frozen_payload is None:
                        raise ReviewReadError("referenced_artifact_payload_invalid")
                    if sha256_json(frozen_payload) != str(artifact.get("content_hash") or "").lower():
                        raise ReviewReadError("referenced_artifact_content_hash_mismatch")
                    frozen_input_event_ids.update(_explicit_event_ids(frozen_payload))
        for event_id in sorted(frozen_input_event_ids):
            for candidate in by_event.get(event_id, []):
                seq = int(candidate["row"].get("seq") or 0)
                if seq not in selected_by_seq:
                    candidate["dependency_reason"] = "truth_revision_frozen_input_event_closure"
                    selected_by_seq[seq] = candidate

        included = sorted(selected_by_seq.values(), key=lambda item: int(item["row"].get("seq") or 0))
        if len(included) > max_records:
            raise ReviewRangeTooLarge(f"selection_has_more_than_{max_records}_ledger_records; narrow the series or window")
        if any(item["window_time_basis"] == "recorded_at_proxy" for item in included if int(item["row"].get("seq") or 0) in seed_seqs):
            gaps["window_uses_recorded_at_proxy"] += sum(
                1 for item in included if item["window_time_basis"] == "recorded_at_proxy" and int(item["row"].get("seq") or 0) in seed_seqs
            )
        for item in included:
            item["artifact_refs"] = _payload_refs(item["payload"])
            item["artifact_ref_details"] = _payload_ref_details(item["payload"])

        selected_judgements: list[dict[str, Any]] = []
        linked_judgement_ids = {
            str(item["row"].get("judgement_id") or item["payload"].get("origin_judgement_id") or item["payload"].get("judgement_id"))
            for item in included
            if item["row"].get("judgement_id") is not None or item["payload"].get("origin_judgement_id") is not None or item["payload"].get("judgement_id") is not None
        }
        for judgement in legacy_judgements:
            row = judgement["row"]
            created = _maybe_utc(row.get("created_at"))
            matched = _in_window(created, start_dt, end_dt) and series_id is None
            if matched or str(row.get("id")) in linked_judgement_ids:
                judgement["is_dependency"] = not matched
                selected_judgements.append(judgement)
            elif series_id is not None and _in_window(created, start_dt, end_dt):
                gaps["legacy_judgement_series_unresolvable"] += 1
        if len(included) + len(selected_judgements) > max_records:
            raise ReviewRangeTooLarge(f"selection_has_more_than_{max_records}_records; narrow the series or window")

        selected_truth_events: list[dict[str, Any]] = []
        linked_event_ids = {
            str(item["row"].get("event_id") or item["payload"].get("event_id"))
            for item in included
            if item["row"].get("event_id") is not None or item["payload"].get("event_id") is not None
        }
        if normal_anchor_event is not None:
            linked_event_ids.add(str(normal_anchor_event["row"].get("id")))
        modern_truth_event_ids = {
            str(item["row"].get("event_id") or item["payload"].get("event_id"))
            for item in included
            if item["row"].get("kind") == "truth_revision"
            and (item["row"].get("event_id") is not None or item["payload"].get("event_id") is not None)
        }
        for event in legacy_events:
            row = event["row"]
            if str(row.get("id")) in modern_truth_event_ids:
                continue
            occurrence = _maybe_utc(row.get("occurred_at"))
            creation = event["recorded_at"]
            in_window = _in_window(occurrence or creation, start_dt, end_dt) and series_id is None
            if in_window or str(row.get("id")) in linked_event_ids:
                event["is_dependency"] = not in_window
                selected_truth_events.append(event)

        source_values: list[object] = [item["payload"] for item in included]
        source_values.extend(item["raw_source"] for item in selected_judgements)
        source_values.extend(item["row"] for item in selected_truth_events)
        artifact_refs = sorted({ref for item in included for ref in item["artifact_refs"]})
        artifact_ref_set = set(artifact_refs)
        referenced_ids = sorted({identifier for _, identifier in artifact_refs})
        expected_artifacts: dict[str, dict[str, str | None]] = {}
        expected_targets: dict[str, str] = {}

        def register_reference(target: str, artifact_id: str, expected_kind: str | None, expected_hash: str | None) -> None:
            previous_target = expected_targets.get(artifact_id)
            if previous_target is not None and previous_target != target:
                raise ReviewReadError("artifact_reference_role_conflict")
            expected_targets[artifact_id] = target
            previous = expected_artifacts.setdefault(artifact_id, {"kind": None, "content_hash": None})
            for key, value in (("kind", expected_kind), ("content_hash", expected_hash)):
                if value is None:
                    continue
                old_value = previous.get(key)
                if old_value is not None and old_value != value:
                    code = "artifact_reference_kind_conflict" if key == "kind" else "artifact_reference_hash_conflict"
                    raise ReviewReadError(code)
                previous[key] = value

        for item in included:
            for target, artifact_id, expected_kind, expected_hash in item["artifact_ref_details"]:
                register_reference(target, artifact_id, expected_kind, expected_hash)
        artifacts: dict[str, dict[str, Any]] = {}
        policy_map = _policy_map(connection)
        current_posts = _current_post_map(connection)

        artifact_cols = _columns(connection, "prediction_artifacts") if artifacts_available else set()
        if referenced_ids and artifacts_available and not set(_ARTIFACT_COLUMNS).issubset(artifact_cols):
            gaps["prediction_artifacts_schema_incomplete"] += 1
        elif referenced_ids and artifacts_available:
            pending_ids = set(referenced_ids)
            fetched_ids: set[str] = set()
            while pending_ids:
                batch_ids = sorted(pending_ids - fetched_ids)
                if not batch_ids:
                    break
                if len(fetched_ids) + len(batch_ids) > MAX_SOURCE_ROWS:
                    raise ReviewRangeTooLarge(f"artifact_reference_closure_exceeds_{MAX_SOURCE_ROWS}; narrow the selection")
                pending_ids.clear()
                fetched_ids.update(batch_ids)
                for offset in range(0, len(batch_ids), 500):
                    batch = batch_ids[offset:offset + 500]
                    marks = ",".join("?" for _ in batch)
                    query = f"SELECT {', '.join(_ARTIFACT_COLUMNS)} FROM prediction_artifacts WHERE id IN ({marks})"
                    for raw in connection.execute(query, batch).fetchall():
                        artifact = dict(zip(_ARTIFACT_COLUMNS, raw))
                        artifact_id = str(artifact.get("id") or "")
                        expected = expected_artifacts.get(artifact_id, {})
                        actual_kind = str(artifact.get("kind") or "")
                        expected_kind = expected.get("kind")
                        expected_hash = expected.get("content_hash")
                        if expected_kind is not None and expected_kind != actual_kind:
                            raise ReviewReadError("artifact_reference_kind_conflict")
                        if expected_hash is not None and expected_hash != str(artifact.get("content_hash") or "").lower():
                            raise ReviewReadError("artifact_reference_hash_conflict")
                        target = expected_targets.get(artifact_id)
                        if target is not None and _source_role_artifact(actual_kind) != target:
                            raise ReviewReadError("artifact_reference_role_conflict")
                        when = _maybe_utc(artifact.get("recorded_at"))
                        if when is None or when > freeze_dt:
                            gaps["artifact_not_available_as_of_freeze"] += 1
                            continue
                        parsed = _json_object(artifact.get("payload_json"))
                        if parsed is None:
                            raise ReviewReadError("referenced_artifact_payload_invalid")
                        if sha256_json(parsed) != str(artifact.get("content_hash") or "").lower():
                            raise ReviewReadError("referenced_artifact_content_hash_mismatch")
                        if when <= freeze_dt:
                            artifact["payload"] = parsed
                            artifacts[artifact_id] = artifact
                            source_values.append(parsed)
                            for nested_target, nested_id, nested_kind, nested_hash in _payload_ref_details(parsed):
                                register_reference(nested_target, nested_id, nested_kind, nested_hash)
                                nested_ref = (nested_target, nested_id)
                                if nested_ref not in artifact_ref_set:
                                    artifact_ref_set.add(nested_ref)
                                    artifact_refs.append(nested_ref)
                                    pending_ids.add(nested_id)
            artifact_refs = sorted(set(artifact_refs))
        legacy_evidence, legacy_snapshots = _legacy_snapshot_rows(connection, selected_judgements, freeze_dt, policy_map, gaps)
        source_values.extend(legacy_evidence)
        source_values.extend(legacy_snapshots)
        privacy = PrivacyContext.from_sources(source_values)

        forecasts, outputs, attempts, truth, runtime = _build_ledger_records(included, privacy, gaps)
        normal_baseline = None
        if normal_baseline_requested:
            if normal_anchor_event is None:
                gaps["normal_baseline_anchor_missing"] += 1
            else:
                gaps["normal_baseline_history_not_backfilled"] += 1
                baseline_synthetic = _normal_baseline_synthetic_marker(normal_anchor_event, included, gaps)
                normal_raw = _normal_baseline_projection(
                    normal_anchor_event, freeze_text, freeze_dt, is_synthetic=baseline_synthetic,
                )
                normal_baseline = _dto(normal_raw, _FORECAST_FIELDS, privacy, identifier=str(normal_raw["id"]))
                normal_baseline["is_dependency"] = True
                normal_baseline["dependency_reason"] = normal_raw["dependency_reason"]
                forecasts.append(normal_baseline)
                forecasts.sort(key=lambda item: (str(item.get("series_id") or ""), int(item.get("revision") or 0), str(item.get("id"))))
        public_evidence = [sanitize_dto(row, _EVIDENCE_FIELDS, privacy) | {"id": str(row["id"])} for row in legacy_evidence]
        input_snapshots = [sanitize_dto(row, _SNAPSHOT_FIELDS, privacy) | {"id": str(row["id"])} for row in legacy_snapshots]

        artifact_id_map: dict[tuple[str, str], str] = {}
        missing_artifact_map: dict[tuple[str, str], tuple[str, str]] = {}
        artifact_ids_by_target: dict[str, list[str]] = defaultdict(list)
        for target, raw_id in artifact_refs:
            artifact_ids_by_target[target].append(raw_id)
        for target in artifact_ids_by_target:
            for index, raw_id in enumerate(sorted(set(artifact_ids_by_target[target])), 1):
                artifact_id_map[(target, raw_id)] = f"{target.replace('_', '-')}-{index:04d}"
        artifact_ref_set = set(artifact_refs)
        frame_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        run_frame_text_sources: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for item in included:
            row, payload = item["row"], item["payload"]
            if row.get("kind") != "run_started":
                continue
            run_id = _row_run(row, payload)
            if not run_id:
                continue
            for target, frame_id in item["artifact_refs"]:
                frame_artifact = artifacts.get(frame_id) if target == "input_snapshots" else None
                if frame_artifact and frame_artifact.get("kind") == "input_frame":
                    run_frame_text_sources[str(run_id)].extend(
                        _frame_text_sources(frame_artifact.get("payload"))
                    )
        truth_body_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        truth_body_refs: dict[str, tuple[str, str]] = {}
        output_source_groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        run_synthetic: dict[str, bool | None] = {}
        for item in included:
            row, payload = item["row"], item["payload"]
            run_id = _row_run(row, payload)
            if row.get("kind") == "run_started" and run_id:
                value = payload.get("is_synthetic")
                run_synthetic[str(run_id)] = value if isinstance(value, bool) else None
            for target, raw_id in item["artifact_refs"]:
                if target == "outputs":
                    attempt_id = _row_attempt(row, payload) or _id(payload.get("source_attempt_id"))
                    group_run_id = _id(payload.get("source_run_id")) or _row_run(row, payload)
                    group_key = f"attempt:{group_run_id or ''}:{attempt_id}" if attempt_id else f"event:{_record_id(row)}"
                    group = output_source_groups[raw_id].setdefault(
                        group_key, {"item": item, "items": [], "record_ids": set()}
                    )
                    if int(row.get("seq") or 0) < int(group["item"]["row"].get("seq") or 0):
                        group["item"] = item
                    group["items"].append(item)
                    group["record_ids"].add(_record_id(row))
        processing_output_instance_ids: dict[tuple[str, str], str] = {}
        processing_output_id_by_reference: dict[tuple[str, str], str] = {}
        used_output_ids = {str(row.get("id")) for row in outputs}
        next_processing_output_number = 1
        for raw_id, groups in sorted(output_source_groups.items()):
            for group_key, group in sorted(groups.items()):
                safe_id = f"processing-output-{next_processing_output_number:06d}"
                while safe_id in used_output_ids:
                    next_processing_output_number += 1
                    safe_id = f"processing-output-{next_processing_output_number:06d}"
                next_processing_output_number += 1
                used_output_ids.add(safe_id)
                processing_output_instance_ids[(raw_id, group_key)] = safe_id
                for record_id in group["record_ids"]:
                    processing_output_id_by_reference[(record_id, raw_id)] = safe_id
            if groups:
                first_group_key = sorted(groups)[0]
                artifact_id_map[("outputs", raw_id)] = processing_output_instance_ids[(raw_id, first_group_key)]
        for artifact_id, artifact in artifacts.items():
            if str(artifact.get("kind")) == "input_frame":
                for text_id, source_ref in _frame_text_sources(artifact.get("payload")):
                    frame_sources[text_id].append(source_ref)
                    ref = ("public_evidence", text_id)
                    if ref not in artifact_ref_set:
                        artifact_ref_set.add(ref)
                        artifact_refs.append(ref)
                        pending_refs_gaps = text_id not in artifacts
                        if pending_refs_gaps:
                            gaps["frame_text_artifact_not_loaded"] += 1
                        artifact_ids_by_target[ref[0]].append(ref[1])
            elif str(artifact.get("kind")) == "truth_evidence":
                truth_payload = artifact.get("payload") if isinstance(artifact.get("payload"), Mapping) else {}
                body_ref = truth_payload.get("body_artifact_ref")
                if isinstance(body_ref, Mapping) and isinstance(body_ref.get("artifact_id"), (str, int)):
                    body_id = str(body_ref["artifact_id"])
                    truth_body_refs[artifact_id] = ("public_evidence", body_id)
                    truth_body_sources[body_id].append({
                        "post_id": truth_payload.get("post_id"),
                        "tweet_id": truth_payload.get("tweet_id"),
                        "author": truth_payload.get("author"),
                        "parent_tweet_id": truth_payload.get("parent_tweet_id"),
                        "role": truth_payload.get("role"),
                        "relation_to_target": truth_payload.get("relation_to_target"),
                        "relation_source": truth_payload.get("relation_source"),
                        "source_version": truth_payload.get("source_version"),
                        "policy_version": truth_payload.get("policy_version"),
                        "snapshot_status": truth_payload.get("snapshot_status"),
                    })
                    ref = ("public_evidence", body_id)
                    if ref not in artifact_ref_set:
                        artifact_ref_set.add(ref)
                        artifact_refs.append(ref)
                        if body_id not in artifacts:
                            gaps["truth_body_artifact_not_loaded"] += 1
                        artifact_ids_by_target[ref[0]].append(ref[1])
        # The ledger normally includes these frame references in input_artifact_refs;
        # also collect them directly so an older/incomplete run still gets explicit closure.
        for target in list(artifact_ids_by_target):
            known = {raw_id for mapped_target, raw_id in artifact_id_map if mapped_target == target}
            for index, raw_id in enumerate(sorted(set(artifact_ids_by_target[target]) - known), len(known) + 1):
                artifact_id_map[(target, raw_id)] = f"{target.replace('_', '-')}-{index:04d}"

        input_snapshot_nested_refs: dict[str, list[tuple[str, str]]] = {}

        def add_artifact_placeholder(target: str, raw_id: str, reason: str) -> None:
            safe_id = artifact_id_map[(target, raw_id)]
            missing_artifact_map[(target, raw_id)] = (safe_id, reason)
            placeholder = {
                "id": safe_id, "placeholder": True, "omission_reason": reason,
                "redacted": False, "redaction_categories": [],
            }
            collection = {
                "public_evidence": public_evidence,
                "input_snapshots": input_snapshots,
                "runtime_identities": runtime,
                "outputs": outputs,
            }[target]
            collection.append(placeholder)

        for target, raw_id in sorted(set(artifact_refs)):
            artifact = artifacts.get(raw_id)
            if artifact is None:
                gaps["artifact_not_available_as_of_freeze"] += 1
                add_artifact_placeholder(target, raw_id, "referenced_artifact_not_available_as_of_freeze")
                continue
            actual_target = _source_role_artifact(artifact.get("kind"))
            if actual_target != target:
                raise ReviewReadError("artifact_reference_role_conflict")
            kind = str(artifact.get("kind") or "")
            payload = artifact.get("payload") if isinstance(artifact.get("payload"), Mapping) else {}
            identifier = artifact_id_map[(target, raw_id)]
            if kind == "input_frame":
                projection = {
                    "source_kind": "ledger_input_frame",
                    "input_frame": payload,
                    "is_synthetic": None,
                }
                input_snapshot_nested_refs[identifier] = _payload_refs(payload)
                input_snapshots.append(_dto(projection, _SNAPSHOT_FIELDS, privacy, identifier=identifier))
            elif kind == "request_descriptor":
                projection = {
                    "source_kind": "ledger_request_descriptor",
                    "request_descriptor": payload,
                    "is_synthetic": None,
                }
                input_snapshot_nested_refs[identifier] = _payload_refs(payload)
                input_snapshots.append(_dto(projection, _SNAPSHOT_FIELDS, privacy, identifier=identifier))
            elif kind in {"public_prompt", "judge_schema"}:
                reason = "prompt_material_not_exported" if kind == "public_prompt" else "schema_artifact_not_exported"
                add_artifact_placeholder(target, raw_id, reason)
                if kind == "public_prompt":
                    gaps["prompt_material_omitted"] += 1
                else:
                    gaps["judge_schema_omitted"] += 1
                continue
            elif kind == "text_content":
                sources = [*frame_sources.get(raw_id, []), *truth_body_sources.get(raw_id, [])]
                if not sources:
                    gaps["text_artifact_source_reference_missing"] += 1
                    add_artifact_placeholder(target, raw_id, "text_artifact_source_reference_unavailable")
                    continue
                public_evidence.append(_ledger_evidence_projection(
                    identifier, payload, sources, privacy, policy_map, current_posts,
                ))
            elif kind == "processing_output":
                operation = payload.get("operation")
                if operation not in {"post_analysis", "post_translation"} or not isinstance(payload.get("output"), Mapping):
                    gaps["processing_output_operation_unsupported"] += 1
                    add_artifact_placeholder(target, raw_id, "processing_output_operation_or_payload_unsupported")
                    continue
                groups = output_source_groups.get(raw_id, {})
                if not groups:
                    gaps["processing_output_execution_reference_missing"] += 1
                    add_artifact_placeholder(target, raw_id, "processing_output_execution_reference_unavailable")
                    continue
                for group_key, group in sorted(groups.items()):
                    source_item = group["item"]
                    source_row, source_payload = source_item["row"], source_item["payload"]
                    run_id = _row_run(source_row, source_payload)
                    instance_id = processing_output_instance_ids[(raw_id, group_key)]
                    run_sources = run_frame_text_sources.get(str(run_id), []) if run_id else []
                    source_output = payload["output"]
                    mentioned_tweets: set[str] = set()
                    output_tweet_id = source_output.get("tweet_id")
                    if isinstance(output_tweet_id, (str, int)):
                        mentioned_tweets.add(str(output_tweet_id))
                    evidence_post_ids = source_output.get("evidence_post_ids")
                    if isinstance(evidence_post_ids, (list, tuple)):
                        mentioned_tweets.update(str(value) for value in evidence_post_ids if isinstance(value, (str, int)))
                    effects = source_output.get("effects")
                    if isinstance(effects, (list, tuple)):
                        mentioned_tweets.update(
                            str(effect["tweet_id"])
                            for effect in effects
                            if isinstance(effect, Mapping) and isinstance(effect.get("tweet_id"), (str, int))
                        )
                    matched_sources = [
                        (text_id, source_ref) for text_id, source_ref in run_sources
                        if not mentioned_tweets or str(source_ref.get("tweet_id") or "") in mentioned_tweets
                    ]
                    policy_restricted = False
                    # Privacy is evaluated against every source actually frozen
                    # for the run, including parents/ancestors not named as the
                    # output's target Tweet.
                    for _, source_ref in run_sources:
                        try:
                            post_id = int(source_ref.get("post_id")) if source_ref.get("post_id") is not None else None
                        except (TypeError, ValueError):
                            post_id = None
                        current_hash = current_posts.get(post_id) if post_id is not None else None
                        if current_hash is not None and policy_map.get((post_id, current_hash)) is False:
                            policy_restricted = True

                    safe_evidence_refs: list[dict[str, Any]] = []
                    seen_source_refs: set[str] = set()
                    for text_id, source_ref in run_sources:
                        safe_text_id = artifact_id_map.get(("public_evidence", text_id))
                        if safe_text_id is None or safe_text_id in seen_source_refs:
                            continue
                        seen_source_refs.add(safe_text_id)
                        missing_reason = (
                            "referenced_artifact_not_available_as_of_freeze" if text_id not in artifacts else None
                        )
                        safe_evidence_refs.append({
                            "target": "public_evidence", "id": safe_text_id,
                            "role": _safe_reason_code(source_ref.get("role")) or "input_text",
                            "status": "missing" if missing_reason else "included", "reason": missing_reason,
                        })
                    source_content_status = (
                        "restricted_by_current_policy" if policy_restricted else
                        "current_policy_not_restricting_or_unknown" if matched_sources else
                        "source_version_unresolved"
                    )
                    safe_processing_payload: dict[str, Any] = {
                        "operation": operation,
                        "output": dict(source_output),
                    }
                    redacted = policy_restricted or not matched_sources
                    redaction_categories: list[str] = []
                    if redacted:
                        text_fields = {
                            "evidence_quote", "summary", "event_title", "normalization_notes", "translation_zh",
                        }
                        safe_output = {key: value for key, value in source_output.items() if key not in text_fields}
                        if isinstance(effects, (list, tuple)):
                            safe_output["effects"] = [
                                {key: value for key, value in effect.items() if key not in text_fields}
                                for effect in effects if isinstance(effect, Mapping)
                            ]
                        safe_processing_payload["output"] = safe_output
                        redaction_categories.append(
                            "current_content_policy_restriction" if policy_restricted else "output_source_version_unresolved"
                        )
                        if not matched_sources:
                            gaps["processing_output_source_version_unresolved"] += 1
                    projection = {
                        "record_id": _record_id(source_row),
                        "output_id": instance_id,
                        "forecast_id": _row_forecast(source_row, source_payload),
                        "series_id": _row_scope(source_row, source_payload),
                        "attempt_id": _row_attempt(source_row, source_payload) or _id(source_payload.get("source_attempt_id")),
                        "run_id": run_id,
                        "output_kind": "processing_output",
                        "operation": operation,
                        "processing_output": safe_processing_payload,
                        "status": "recorded",
                        "recorded_at": artifact.get("recorded_at"),
                        "artifact_recorded_at": artifact.get("recorded_at"),
                        "occurred_at": source_row.get("occurred_at"),
                        "output_available_at": None,
                        "evidence_refs": safe_evidence_refs,
                        "source_content_status": source_content_status,
                        "is_synthetic": run_synthetic.get(str(run_id)) if run_id else None,
                        "is_dependency": any(item.get("dependency_reason") for item in group["items"]),
                        "redacted": redacted,
                        "redaction_categories": redaction_categories,
                        "selection_basis": "processing_output_artifact_reference",
                    }
                    outputs.append(_dto(
                        projection, _OUTPUT_FIELDS, privacy, identifier=instance_id,
                        source_id=_record_id(source_row),
                    ))
            elif kind == "runtime_identity":
                runtime.append(_runtime_identity_projection(payload, identifier, privacy))
            elif kind == "input_snapshot":
                projection = dict(payload)
                projection.update({
                    "input_snapshot_id": identifier,
                    "snapshot_hash": payload.get("semantic_input_hash"),
                    "source_kind": "ledger_input_snapshot",
                    "evidence_refs": [],
                })
                input_snapshot_nested_refs[identifier] = [
                    ref for ref in _payload_refs(payload)
                ]
                input_snapshots.append(_dto(projection, _SNAPSHOT_FIELDS, privacy, identifier=identifier))
            elif kind == "truth_evidence" or target == "public_evidence":
                evidence_projection = dict(payload)
                evidence_projection.pop("source_event_snapshot_hash", None)
                if isinstance(payload.get("source_event_snapshot"), Mapping):
                    evidence_projection["source_snapshot"] = payload["source_event_snapshot"]
                body_relation = truth_body_refs.get(raw_id)
                if body_relation:
                    body_target, body_raw_id = body_relation
                    body_missing = body_raw_id not in artifacts
                    evidence_projection["body_ref"] = {
                        "target": body_target,
                        "id": artifact_id_map[(body_target, body_raw_id)],
                        "status": "missing" if body_missing else "included",
                        "reason": "referenced_artifact_not_available_as_of_freeze" if body_missing else None,
                    }
                public_evidence.append(_dto(evidence_projection, _EVIDENCE_FIELDS, privacy, identifier=identifier))
            else:
                gaps["artifact_kind_not_projected"] += 1
                add_artifact_placeholder(target, raw_id, "artifact_kind_not_projected_to_public_dto")

        included_by_record = {_record_id(item["row"]): item for item in included}
        truth_by_record = {str(item.get("record_id")): item for item in truth if item.get("record_id") is not None}
        for source_record_id, source_item in included_by_record.items():
            if source_item["row"].get("kind") != "truth_revision":
                continue
            truth_item = truth_by_record.get(source_record_id)
            if truth_item is None:
                continue
            payload = source_item["payload"]
            snapshot_ref = payload.get("source_event_snapshot_ref")
            if isinstance(snapshot_ref, Mapping) and isinstance(snapshot_ref.get("artifact_id"), (str, int)):
                snapshot_artifact = artifacts.get(str(snapshot_ref["artifact_id"]))
                snapshot_payload = snapshot_artifact.get("payload") if isinstance(snapshot_artifact, Mapping) else None
                source_snapshot = snapshot_payload.get("source_event_snapshot") if isinstance(snapshot_payload, Mapping) else None
                if isinstance(source_snapshot, Mapping):
                    truth_item["source_snapshot"] = sanitize_dto(
                        {"source_snapshot": source_snapshot}, {"source_snapshot"}, privacy
                    )["source_snapshot"]

            raw_refs = payload.get("evidence_refs")
            raw_refs = raw_refs if isinstance(raw_refs, (list, tuple)) else []
            if isinstance(snapshot_ref, Mapping) and not any(
                isinstance(entry, Mapping)
                and isinstance(entry.get("artifact_ref"), Mapping)
                and str(entry["artifact_ref"].get("artifact_id")) == str(snapshot_ref.get("artifact_id"))
                for entry in raw_refs
            ):
                raw_refs = [*raw_refs, {"artifact_ref": snapshot_ref, "role": "reset_event_source_snapshot"}]
            safe_evidence_refs: list[dict[str, Any]] = []
            seen_refs: set[tuple[str, str, str]] = set()
            for index, raw_ref in enumerate(raw_refs, 1):
                if not isinstance(raw_ref, Mapping):
                    continue
                role = raw_ref.get("role")
                role_text = role[:100] if isinstance(role, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", role) else "evidence"
                artifact_ref = raw_ref.get("artifact_ref") if isinstance(raw_ref.get("artifact_ref"), Mapping) else raw_ref
                raw_id = artifact_ref.get("artifact_id") if isinstance(artifact_ref, Mapping) else None
                kind_hint = artifact_ref.get("kind") if isinstance(artifact_ref, Mapping) else None
                target = _source_role_artifact(kind_hint) or "public_evidence"
                if isinstance(raw_id, (str, int)) and str(raw_id):
                    raw_id = str(raw_id)
                    missing = missing_artifact_map.get((target, raw_id))
                    safe_id = missing[0] if missing else artifact_id_map.get((target, raw_id))
                    if safe_id is None:
                        safe_id = f"missing-evidence-{int(source_item['row'].get('seq') or 0):08d}-{index:04d}"
                        public_evidence.append({
                            "id": safe_id, "placeholder": True,
                            "omission_reason": "truth_evidence_artifact_reference_unavailable",
                            "redacted": False, "redaction_categories": [],
                        })
                        missing = (safe_id, "truth_evidence_artifact_reference_unavailable")
                    status = "missing" if missing else "included"
                    reason = missing[1] if missing else None
                else:
                    tweet_id = raw_ref.get("tweet_id")
                    safe_id = f"missing-evidence-{int(source_item['row'].get('seq') or 0):08d}-{index:04d}"
                    reason = "source_not_local_at_truth_revision" if raw_ref.get("snapshot_status") == "source_not_local" else "truth_evidence_snapshot_unavailable"
                    public_evidence.append({
                        "id": safe_id, "tweet_id": str(tweet_id)[:100] if isinstance(tweet_id, (str, int)) else None,
                        "role": role_text, "placeholder": True, "omission_reason": reason,
                        "redacted": False, "redaction_categories": [],
                    })
                    status = "missing"
                ref_key = (target, str(safe_id), role_text)
                if ref_key in seen_refs:
                    continue
                seen_refs.add(ref_key)
                safe_evidence_refs.append({
                    "target": target, "id": safe_id, "role": role_text,
                    "status": status, "reason": reason,
                })
            truth_item["evidence_refs"] = safe_evidence_refs

        for snapshot in input_snapshots:
            nested_refs = input_snapshot_nested_refs.get(str(snapshot.get("id")), [])
            if not nested_refs:
                continue
            evidence_refs = []
            artifact_package_refs = []
            for target, raw_id in sorted(set(nested_refs)):
                missing = missing_artifact_map.get((target, raw_id))
                safe_id = missing[0] if missing else artifact_id_map.get((target, raw_id))
                reference = {
                    "target": target, "id": safe_id,
                    "status": "missing" if missing else "included",
                    "reason": missing[1] if missing else None,
                }
                if target == "public_evidence":
                    evidence_refs.append(reference)
                else:
                    artifact_package_refs.append(reference)
            if evidence_refs:
                snapshot["evidence_refs"] = evidence_refs
            if artifact_package_refs:
                references = dict(snapshot.get("references") or {})
                references["artifacts"] = artifact_package_refs
                snapshot["references"] = references

        for judgement in selected_judgements:
            row = judgement["row"]
            raw = judgement["raw_safe"]
            jid = str(row.get("id"))
            structured = {
                "action_level": row.get("action_level"), "horizon_24h": row.get("horizon_24h"),
                "horizon_48h": row.get("horizon_48h"), "horizon_72h": row.get("horizon_72h"),
                "estimated_start": row.get("estimated_start"), "estimated_end": row.get("estimated_end"),
                "estimate_basis": row.get("estimate_basis"), "data_health": row.get("data_health"),
                "judgement_as_of": row.get("created_at"), "status": row.get("status"),
            }
            structured = {key: value for key, value in structured.items() if key in _OUTPUT_STRUCTURED_FIELDS}
            output_source = {
                "record_id": f"legacy-judgement-{jid}", "output_id": f"legacy-output-{jid}",
                "output_kind": "legacy_judgement_structured_output", "status": row.get("status"),
                "validation_status": "not_revalidated_during_export", "output_available_at": None,
                "structured_output": structured, "reason_summary": row.get("reason_summary"),
                "judgement_as_of": row.get("created_at"), "declared_model": row.get("model"),
                "prompt_version": row.get("prompt_version"), "is_synthetic": None,
                "time_gap_reason": "legacy_attempt_and_output_available_times_not_recorded",
                "is_dependency": judgement.get("is_dependency", False),
                "selection_basis": "judgement_as_of_proxy",
                "forecast_ref": {"target": "forecasts", "id": None, "status": "missing", "reason": "legacy_semantic_forecast_version_not_recorded"},
                "attempt_ref": {"target": "attempts", "id": None, "status": "missing", "reason": "legacy_attempt_not_recorded"},
                "evidence_refs": [],
            }
            for ref in next((snap.get("evidence_refs", []) for snap in legacy_snapshots if str(snap.get("judgement_id")) == jid), []):
                output_source["evidence_refs"].append(ref)
            output = sanitize_dto(output_source, _OUTPUT_FIELDS | {"judgement_as_of", "declared_model", "time_gap_reason", "is_dependency", "selection_basis", "forecast_ref", "attempt_ref", "evidence_refs"}, privacy)
            output["id"] = f"legacy-output-{jid}"
            output["legacy_judgement_id"] = row.get("id")
            outputs.append(output)
            # The old Judge fields are preserved as a legacy output; they do not
            # assert a recoverable semantic forecast revision or completed time.
            if row.get("failure_reason"):
                gaps["legacy_failure_detail_restricted_to_safe_summary"] += 1

        for event in selected_truth_events:
            row = event["row"]
            event_id = str(row.get("id"))
            base = {
                "record_id": f"legacy-event-{event_id}", "event_id": event_id,
                "event_type": row.get("event_type"), "special_type": row.get("special_type"),
                "scope": row.get("scope"), "actual_start": row.get("occurred_at"),
                "actual_start_end": row.get("occurred_at_end"), "actual_time_basis": row.get("time_basis"),
                "actual_precision": None, "truth_revision": None, "previous_revision": None,
                "truth_status": "legacy_event_snapshot_not_independently_adjudicated",
                "recorded_at": row.get("updated_at") or row.get("created_at"),
                "reason_summary": row.get("summary"), "is_synthetic": None,
                "is_dependency": event.get("is_dependency", False), "source_mode": "legacy_reset_events",
                "evidence_post_ids": _json_object(row.get("evidence_post_ids")) if isinstance(row.get("evidence_post_ids"), str) else row.get("evidence_post_ids"),
            }
            out = sanitize_dto(base, _TRUTH_FIELDS | {"is_dependency", "source_mode"}, privacy)
            out["id"] = f"legacy-event-{event_id}"
            out["time_precision"] = None
            out["time_precision_reason"] = "legacy_reset_events_does_not_record_independent_precision"
            truth.append(out)

        outputs.sort(key=lambda item: (str(item.get("occurred_at") or item.get("judgement_as_of") or ""), str(item.get("id"))))
        public_evidence.sort(key=lambda item: str(item.get("id", "")))
        input_snapshots.sort(key=lambda item: str(item.get("id", "")))
        runtime.sort(key=lambda item: str(item.get("id", "")))
        collections = {
            "forecasts": forecasts,
            "outputs": outputs,
            "attempts": attempts,
            "truth_revisions": truth,
            "public_evidence": public_evidence,
            "input_snapshots": input_snapshots,
            "runtime_identities": runtime,
        }
        _attach_references(
            collections, included, artifact_id_map, missing_artifact_map,
            processing_output_id_by_reference,
        )
        artifact_synthetic = _artifact_synthetic_provenance(included, artifacts, artifact_refs, gaps)
        raw_artifact_by_safe_id = {
            (target, safe_id): raw_id
            for (target, raw_id), safe_id in artifact_id_map.items()
            if target in _SYNTHETIC_ARTIFACT_TARGETS
        }
        for collection_name in ("public_evidence", "input_snapshots", "runtime_identities"):
            for dto in collections[collection_name]:
                if dto.get("placeholder") is True:
                    continue
                raw_id = raw_artifact_by_safe_id.get((collection_name, str(dto.get("id") or "")))
                if raw_id is not None and raw_id in artifact_synthetic:
                    dto["is_synthetic"] = artifact_synthetic[raw_id]
        package_rows = sum(len(rows) for rows in collections.values())
        if package_rows > max_records:
            raise ReviewRangeTooLarge(f"package_projection_has_more_than_{max_records}_records; narrow the selection")
        if len(artifact_refs) > max_records:
            raise ReviewRangeTooLarge(f"selection_has_more_than_{max_records}_artifact_references; narrow the selection")

        in_window_counts: Counter[str] = Counter()
        dependency_counts: Counter[str] = Counter()
        for item in included:
            name = str(item["row"].get("kind") or "unsupported")
            if int(item["row"].get("seq") or 0) in seed_seqs:
                in_window_counts[name] += 1
            else:
                dependency_counts[name] += 1
        in_window_counts["legacy_judgements"] = sum(not item.get("is_dependency", False) for item in selected_judgements)
        in_window_counts["legacy_reset_events"] = sum(not item.get("is_dependency", False) for item in selected_truth_events)
        dependency_counts["legacy_judgements"] = sum(bool(item.get("is_dependency")) for item in selected_judgements)
        dependency_counts["legacy_reset_events"] = sum(bool(item.get("is_dependency")) for item in selected_truth_events)
        closure_reasons = Counter(str(item.get("dependency_reason")) for item in included if item.get("dependency_reason"))
        if normal_baseline is not None:
            closure_reasons[normal_raw["dependency_reason"]] += 1
        source_modes = []
        if ledger_available:
            source_modes.append("prediction_ledger_readonly")
        if "radar_judgements" in tables:
            source_modes.append("legacy_judgement_adapter")
        if "reset_events" in tables:
            source_modes.append("legacy_event_snapshot_adapter")
        if normal_baseline is not None:
            source_modes.append("normal_baseline_compatibility_view")
            dependency_counts["normal_baseline_compatibility_view"] += 1
        metadata = {
            "review_schema_version": REVIEW_SCHEMA_VERSION,
            "freeze_at": freeze_text,
            "window": {
                "start_utc": _utc(selection["start"], "start")[1] if selection.get("start") is not None else None,
                "end_utc_exclusive": _utc(selection["end"], "end")[1] if selection.get("end") is not None else None,
                "series_id": series_id,
                "semantics": "start_inclusive_end_exclusive",
                "legacy_judgement_time_basis": "judgement_as_of_proxy",
            },
            "high_water": effective_high_water,
            "high_water_source": "prediction_ledger_same_read_snapshot" if ledger_available else "not_available_legacy_database",
            "counts_in_window": dict(sorted(in_window_counts.items())),
            "dependency_counts": dict(sorted(dependency_counts.items())),
            "closure_reasons": dict(sorted(closure_reasons.items())),
            "gaps": [{"code": code, "count": count} for code, count in sorted(gaps.items()) if count],
            "capabilities": {
                "prediction_ledger": "READ_ONLY" if ledger_available else "NOT_PRESENT_LEGACY_COMPATIBILITY",
                "independent_banked_forecasts": "NOT_IMPLEMENTED",
                "normal_baseline": "COMPATIBILITY_VIEW_ONLY",
                "normal_baseline_history": "NOT_BACKFILLED",
                "assessments": "NOT_IMPLEMENTED",
            },
            "source_modes": source_modes or ["empty_readonly_source"],
            "synthetic_provenance": _synthetic_provenance(collections),
            "max_records": max_records,
            "records_selected": len(included) + len(selected_judgements) + len(selected_truth_events) + (1 if normal_baseline is not None else 0),
            "package_records": package_rows,
        }
        result = {
            "forecasts": forecasts,
            "outputs": outputs,
            "attempts": attempts,
            "truth_revisions": truth,
            "public_evidence": public_evidence,
            "input_snapshots": input_snapshots,
            "runtime_identities": runtime,
            "assessments": [],
            "metadata": metadata,
        }
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
