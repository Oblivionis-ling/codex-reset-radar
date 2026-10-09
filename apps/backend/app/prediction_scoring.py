"""Deterministic, offline scoring of explicitly associated frozen review DTOs.

No database, model, network, current configuration or clock is consulted here.
Package verification is a separate prerequisite, not a prediction quality claim.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any, Mapping, Sequence

from .review_common import sha256_json, utc_text
from .review_privacy import PrivacyContext, sanitize_dto
from .review_reader import core_collection_binding, record_digest


ALGORITHM_VERSION = "crr-prediction-scoring-v1"
SET_SCHEMA_VERSION = "crr-evaluation-set-v1"
ASSESSMENT_SCHEMA_VERSION = "crr-prediction-assessment-v1"
TARGETS = ("EXTRA_FULL", "BANKED")
METHODS = ("official_time_extraction", "model_inference")
CATEGORIES = (
    "no_prediction", "prediction_unknown", "undetermined", "definite_hit",
    "definite_miss", "error_indeterminate",
)
# These are explicit adjudication contracts, not aliases for source-event rows.
TRUSTED_TRUTH_PAIRS = frozenset({
    ("ADJUDICATED", "verified_execution_start"),
    ("fixture_adjudicated", "synthetic_trusted_fixture"),
})
UPPER_BOUND_SOURCE = "formal_read_post_commit_upper_bound"
# An exact source must explicitly certify availability, not attempt completion.
EXACT_AVAILABILITY_SOURCES = frozenset({"formal_commit_exact"})
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
_HOUR_US = 3_600_000_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_SET_ITEMS = 20_000


class ScoringContractError(ValueError):
    """Only fixed, non-private reason codes are raised to callers."""


def _token(value: object, code: str = "invalid_identifier") -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ScoringContractError(code)
    text = str(value)
    if not _TOKEN.fullmatch(text):
        raise ScoringContractError(code)
    return text


def _instant(value: object) -> int:
    if not isinstance(value, str):
        raise ScoringContractError("missing_time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ScoringContractError("timezone_required")
        delta = parsed.astimezone(UTC) - _EPOCH
        return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    except ScoringContractError:
        raise
    except (ValueError, OverflowError):
        raise ScoringContractError("invalid_time") from None


def _utc(value: object) -> str:
    _instant(value)
    return utc_text(value)


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ScoringContractError("interval_endpoint_not_numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ScoringContractError("interval_endpoint_not_finite") from None
    if not result.is_finite():
        raise ScoringContractError("interval_endpoint_not_finite")
    return result


def _interval(value: Sequence[object]) -> tuple[Decimal, Decimal]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ScoringContractError("finite_closed_interval_required")
    lower, upper = map(_decimal, value)
    if lower > upper:
        raise ScoringContractError("interval_endpoints_reversed")
    return lower, upper


def _metrics(predicted: Sequence[object], actual: Sequence[object], divisor: int) -> dict[str, Any]:
    lower, upper = _interval(predicted)
    start, end = _interval(actual)
    scale = Decimal(divisor)
    minimum = max(Decimal(0), start - upper, lower - end)
    maximum = max(abs(lower - end), abs(upper - start))
    values = [minimum / scale, maximum / scale, (upper - lower) / scale, (end - start) / scale]
    result_values = [float(value) for value in values]
    if not all(math.isfinite(value) for value in result_values):
        raise ScoringContractError("interval_metrics_not_finite")
    coverage = (
        "definitely_covered" if lower <= start and end <= upper else
        "definitely_not_covered" if upper < start or end < lower else
        "coverage_indeterminate"
    )
    return dict(zip(("e_min_hours", "e_max_hours", "prediction_width_hours", "truth_width_hours"), result_values),
                coverage=coverage)


def interval_metrics(predicted: Sequence[object], actual: Sequence[object]) -> dict[str, Any]:
    """I=[L,U], J=[a,b], in hours; never midpoint/clip/synthesize endpoints."""
    return _metrics(predicted, actual, 1)


def classify_error(metrics: Mapping[str, Any], threshold_hours: float) -> str:
    threshold = _decimal(threshold_hours)
    minimum = _decimal(metrics.get("e_min_hours"))
    maximum = _decimal(metrics.get("e_max_hours"))
    if threshold < 0 or minimum < 0 or maximum < minimum:
        raise ScoringContractError("invalid_error_metrics")
    if maximum <= threshold:
        return "definite_hit"
    if minimum > threshold:
        return "definite_miss"
    return "error_indeterminate"


def availability_from_output(output: Mapping[str, Any]) -> dict[str, Any]:
    """Only explicitly certified exact times or formal-read upper bounds count.

    Unknown sources, malformed times and any clock/order limitation are missing.
    created_at/as_of/attempt_finished_at/recorded_at are deliberately not read.
    """
    source = output.get("availability_source")
    source = source if isinstance(source, str) and _TOKEN.fullmatch(source) else None
    observations = output.get("availability_observations")
    observations = observations if isinstance(observations, list) else []
    codes: list[str] = []
    safe_observations = []
    for row in [output, *[item for item in observations if isinstance(item, Mapping)]]:
        anomaly, limitation = row.get("clock_anomaly"), row.get("time_limitation")
        if anomaly:
            codes.append("clock_anomaly")
        if limitation:
            codes.append("time_limitation")
        if row is not output:
            try:
                observed_at = _utc(row.get("observed_at"))
            except ScoringContractError:
                observed_at = None
                codes.append("observation_time_missing_or_invalid")
            safe_observations.append({
                "record_id": row.get("record_id") if isinstance(row.get("record_id"), str) and _TOKEN.fullmatch(row["record_id"]) else None,
                "observed_at": observed_at,
                "source": row.get("source") if isinstance(row.get("source"), str) and _TOKEN.fullmatch(row["source"]) else None,
                "clock_anomaly": anomaly if isinstance(anomaly, str) and _TOKEN.fullmatch(anomaly) else ("present" if anomaly else None),
                "time_limitation": limitation if isinstance(limitation, str) and _TOKEN.fullmatch(limitation) else ("present" if limitation else None),
            })
    at = output.get("output_available_at")
    try:
        at = _utc(at)
    except ScoringContractError:
        at = None
        codes.append("output_available_time_missing_or_invalid")
    if source == UPPER_BOUND_SOURCE:
        kind = "observed_upper_bound"
    elif source in EXACT_AVAILABILITY_SOURCES:
        kind = "exact"
    elif source == "synthetic_exact_fixture" and output.get("is_synthetic") is True:
        kind = "exact"
    else:
        kind = "missing"
        codes.append("availability_source_not_certified")
    if codes:
        kind = "missing"
    return {"kind": kind, "at": at, "source": source, "reason_codes": sorted(set(codes)),
            "observations": safe_observations}


def _truth(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if row is None or row.get("placeholder"):
        return {"trusted": False, "interval": None, "reason_codes": ["missing_truth"]}
    codes = []
    pair = (row.get("truth_status"), row.get("actual_time_basis"))
    if pair not in TRUSTED_TRUTH_PAIRS:
        codes.append("truth_not_independently_adjudicated")
    if pair == ("fixture_adjudicated", "synthetic_trusted_fixture") and row.get("is_synthetic") is not True:
        codes.append("synthetic_truth_without_explicit_provenance")
    if not row.get("actual_precision"):
        codes.append("truth_precision_missing")
    try:
        start, end = _instant(row.get("actual_start")), _instant(row.get("actual_start_end"))
        if start > end:
            raise ScoringContractError("interval_endpoints_reversed")
        interval = [start, end]
    except ScoringContractError:
        interval = None
        codes.append("truth_not_finite_closed_interval")
    return {"trusted": not codes, "interval": interval, "reason_codes": sorted(set(codes))}


def _prediction(row: Mapping[str, Any]) -> dict[str, Any]:
    form = row.get("prediction_form")
    date_status = row.get("status")
    if date_status not in {"KNOWN", "UNKNOWN"}:
        return {"state": "unusable", "interval": None, "reason_codes": ["prediction_date_status_missing_or_invalid"]}
    if form is None:
        return {"state": "unusable", "interval": None, "reason_codes": ["prediction_form_missing"]}
    if date_status == "UNKNOWN":
        # A missing field or a contradictory known endpoint is not legal UNKNOWN.
        if form not in {"unknown", "relative"} or "predicted_start" not in row or "predicted_end" not in row or row.get("predicted_start") is not None or row.get("predicted_end") is not None:
            return {"state": "unusable", "interval": None, "reason_codes": ["unknown_contract_invalid"]}
        return {"state": "unknown", "interval": None, "reason_codes": ["explicit_prediction_unknown"]}
    if form == "date":
        if row.get("date_boundaries") != "closed_conservative_local_day_envelope_not_execution_instants" or row.get("precision") != "day":
            return {"state": "unknown", "interval": None, "reason_codes": ["date_closed_envelope_not_declared"]}
    if form == "relative":
        if (row.get("resolved_prediction_form") != "point"
                or row.get("resolution_basis") != "source_posted_at_and_explicit_relative_expression"
                or not row.get("source_timezone") or row.get("source_timezone") == "unknown"):
            return {"state": "unknown", "interval": None, "reason_codes": ["relative_not_explicit_closed_interval"]}
        try:
            _instant(row.get("relative_anchor_at"))
        except ScoringContractError:
            return {"state": "unknown", "interval": None, "reason_codes": ["relative_anchor_not_known"]}
        form = "point"  # The persisted resolution marker, not a guessed endpoint.
    if form in {"start_only", "end_only"}:
        return {"state": "unknown", "interval": None, "reason_codes": ["prediction_not_finite_closed_interval"]}
    if form not in {"point", "range", "date"}:
        return {"state": "unusable", "interval": None, "reason_codes": ["prediction_form_unsupported"]}
    if "predicted_start" not in row or "predicted_end" not in row:
        return {"state": "unusable", "interval": None, "reason_codes": ["prediction_endpoint_field_missing"]}
    try:
        start = _instant(row.get("predicted_start"))
        # An explicit point is the only allowed endpoint normalization.
        end = start if form == "point" and row.get("predicted_end") is None else _instant(row.get("predicted_end"))
        if start > end or (form == "point" and start != end):
            raise ScoringContractError("interval_endpoints_reversed")
    except ScoringContractError:
        return {"state": "unknown", "interval": None, "reason_codes": ["prediction_interval_invalid"]}
    return {"state": "known", "interval": [start, end], "reason_codes": ["conservative_day_envelope_not_execution_instants"] if form == "date" else []}


def _timing(candidate: Mapping[str, Any], truth: Mapping[str, Any]) -> str:
    if not truth.get("trusted"):
        return "uncertain"
    availability = candidate.get("availability") or {}
    if availability.get("kind") not in {"exact", "observed_upper_bound"}:
        return "uncertain"
    try:
        at = _instant(availability.get("at"))
    except ScoringContractError:
        return "uncertain"
    start, end = truth["interval"]
    if at < start:
        return "pre"
    if availability["kind"] == "exact" and at >= end:
        return "post"
    # u>=b is NOT a post-event proof for an upper bound.
    return "uncertain"


def _before(left: Mapping[str, Any], right: Mapping[str, Any], ranks: Mapping[str, int]) -> bool:
    a, b = left.get("availability") or {}, right.get("availability") or {}
    if a.get("kind") not in {"exact", "observed_upper_bound"} or b.get("kind") != "exact":
        return False
    try:
        ta, tb = _instant(a.get("at")), _instant(b.get("at"))
    except ScoringContractError:
        return False
    if ta < tb:
        return True
    if ta == tb and a["kind"] == "exact":
        lid, rid = str(left.get("id")), str(right.get("id"))
        return lid in ranks and rid in ranks and ranks[lid] < ranks[rid]
    return False


def select_candidate(
    candidates: Sequence[Mapping[str, Any]], truth: Mapping[str, Any], boundary: str,
    tie_order: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Select an extreme only when *every* potentially pre-event row permits it.

    tie_order is a pre-frozen, persisted SAME EXACT timestamp order, never a
    lexicographic fallback or a way to rank differing observational upper bounds.
    """
    if boundary not in {"first", "last"}:
        raise ScoringContractError("invalid_boundary")
    if len(candidates) > MAX_SET_ITEMS:
        raise ScoringContractError("candidate_limit_exceeded")
    ids = [_token(row.get("id")) for row in candidates]
    if len(ids) != len(set(ids)):
        raise ScoringContractError("duplicate_candidate_id")
    order = list(tie_order or [])
    if len(order) != len(set(order)):
        raise ScoringContractError("duplicate_tie_order_id")
    ranks = {value: index for index, value in enumerate(order)}
    active = [row for row in candidates if _timing(row, truth) != "post"]
    codes = list(truth.get("reason_codes") or [])
    if not active:
        if candidates:
            codes.append("only_definitely_post_event_versions")
        return {"status": "no_prediction", "selected": None, "reason_codes": sorted(set(codes))}
    # This priority applies only to legal, accepted UNKNOWNs, not failed records.
    if all((row.get("prediction") or {}).get("state") == "unknown" for row in active):
        codes.append("all_eligible_predictions_unknown")
        return {"status": "prediction_unknown", "selected": None, "reason_codes": sorted(set(codes))}
    if not truth.get("trusted"):
        return {"status": "undetermined", "selected": None, "reason_codes": sorted(set(codes))}
    pre = [row for row in active if _timing(row, truth) == "pre"]
    winners = []
    for row in pre:
        others = [other for other in active if other["id"] != row["id"]]
        if boundary == "first":
            proven = all(_before(row, other, ranks) for other in others)
        else:
            proven = all(_before(other, row, ranks) for other in others)
        if proven:
            winners.append(row)
    if len(winners) != 1:
        codes.append("first_last_order_or_precedence_unproven")
        return {"status": "undetermined", "selected": None, "reason_codes": sorted(set(codes))}
    chosen = winners[0]
    state = (chosen.get("prediction") or {}).get("state")
    status = "selected" if state == "known" else "prediction_unknown" if state == "unknown" else "undetermined"
    codes.extend((chosen.get("prediction") or {}).get("reason_codes") or [])
    return {"status": status, "selected": dict(chosen), "reason_codes": sorted(set(codes))}


def _provenance(row: Mapping[str, Any] | None) -> str:
    if row is None:
        return "UNDECLARED"
    marker = row.get("is_synthetic")
    if marker is True:
        return "SYNTHETIC"
    if marker is False:
        return "REAL"
    if str(row.get("source_mode") or row.get("source_kind") or "").startswith("legacy"):
        return "LEGACY_UNDECLARED"
    return "UNDECLARED"


def _index(review: Mapping[str, Any], name: str) -> dict[str, Mapping[str, Any]]:
    rows = review.get(name, [])
    if not isinstance(rows, list) or len(rows) > MAX_SET_ITEMS:
        raise ScoringContractError("collection_size_or_type_invalid")
    result = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ScoringContractError("record_must_be_object")
        identifier = _token(row.get("id"))
        if identifier in result:
            raise ScoringContractError("duplicate_record_id")
        result[identifier] = row
    return result


def _ref(target: str, identifier: object, index: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    identifier = _token(identifier)
    row = index.get(identifier)
    digest = row.get("record_sha256") if row else None
    if row and not row.get("placeholder") and isinstance(digest, str) and _HASH.fullmatch(digest):
        return {"target": target, "id": identifier, "status": "included", "reason": None, "sha256": digest.lower()}
    reason = "referenced_object_missing" if row is None else "referenced_object_placeholder" if row.get("placeholder") else "verified_record_digest_missing"
    return {"target": target, "id": identifier, "status": "missing", "reason": reason, "sha256": None}


def _resolve(ref: Mapping[str, Any], review: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if ref.get("status") != "included":
        return None
    row = _index(review, str(ref.get("target"))).get(str(ref.get("id")))
    if row is None or row.get("placeholder"):
        return None
    if row.get("record_sha256") != ref.get("sha256") or record_digest(row) != ref.get("sha256"):
        raise ScoringContractError("frozen_reference_digest_mismatch")
    return row


def _output_forecast_ids(output: Mapping[str, Any]) -> set[str]:
    result = set()
    if output.get("forecast_id") is not None:
        result.add(str(output["forecast_id"]))
    refs = [output.get("forecast_ref")]
    references = output.get("references")
    if isinstance(references, Mapping):
        refs.append(references.get("forecast"))
    refs.extend(output.get("forecast_refs") or [])
    targets = output.get("target_refs")
    if isinstance(targets, Mapping):
        for ref in targets.values():
            if not isinstance(ref, Mapping):
                continue
            if ref.get("forecast_id") is not None:
                result.add(str(ref["forecast_id"]))
            refs.extend([ref, ref.get("forecast_ref")])
    for ref in refs:
        if isinstance(ref, Mapping) and ref.get("target") == "forecasts" and ref.get("status") == "included":
            result.add(str(ref.get("id")))
    return result


def _source_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(binding, Mapping):
        raise ScoringContractError("source_binding_required")
    result = {key: binding.get(key) for key in ("snapshot_id", "source_sha256", "freeze_at", "high_water", "binding_version")}
    for key in ("sourcekind", "transaction_snapshot_digest"):
        if key in binding:
            result[key] = binding[key]
    result["snapshot_id"] = _token(result["snapshot_id"])
    result["binding_version"] = _token(result["binding_version"])
    if result["source_sha256"] is None and result.get("sourcekind") == "readonly_transaction":
        digest = result.get("transaction_snapshot_digest")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise ScoringContractError("source_transaction_digest_required")
    else:
        if not isinstance(result["source_sha256"], str) or not _HASH.fullmatch(result["source_sha256"]):
            raise ScoringContractError("source_snapshot_hash_required")
        result["source_sha256"] = result["source_sha256"].lower()
    result["freeze_at"] = _utc(result["freeze_at"])
    high_water = result["high_water"]
    if high_water is not None and (isinstance(high_water, bool) or not isinstance(high_water, int) or high_water < 0):
        raise ScoringContractError("invalid_high_water")
    return result


def _package_binding(review: Mapping[str, Any]) -> dict[str, str]:
    binding = review.get("package_binding")
    if not isinstance(binding, Mapping):
        raise ScoringContractError("package_binding_required")
    result = {}
    for key in ("source_package_sha256", "manifest_sha256"):
        value = binding.get(key)
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            raise ScoringContractError("package_hash_required")
        result[key] = value.lower()
    return result


def _scope(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, (str, Mapping)):
        raise ScoringContractError("invalid_scope")
    return sanitize_dto({"scope": value}, {"scope"}, PrivacyContext.from_sources([{"scope": value}])).get("scope")


def _scope_equal(left: object, right: object) -> bool:
    # Unknown scope is not a positive identity/association proof.
    left = left.get("value") if isinstance(left, Mapping) else left
    right = right.get("value") if isinstance(right, Mapping) else right
    if left is None or right is None or left == "unknown" or right == "unknown":
        return False
    return sha256_json(left) == sha256_json(right)


def _coverage(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("status") not in {"complete", "partial", "unknown", "stale"}:
        raise ScoringContractError("coverage_declaration_required")
    start = _utc(raw["start"]) if raw.get("start") is not None else None
    end = _utc(raw["end"]) if raw.get("end") is not None else None
    if (start is None) != (end is None) or (start and _instant(start) >= _instant(end)):
        raise ScoringContractError("invalid_coverage_window")
    return {"status": raw["status"], "start": start, "end": end}


def _event_origin(review: Mapping[str, Any], item: Mapping[str, Any], truth_ref: Mapping[str, Any]) -> tuple[dict[str, Any], str, list[str]]:
    raw_ref = item.get("event_ref", truth_ref)
    if not isinstance(raw_ref, Mapping) or raw_ref.get("target") not in {"truth_revisions", "public_evidence"}:
        raise ScoringContractError("explicit_event_origin_reference_required")
    ref = _ref(str(raw_ref["target"]), raw_ref.get("id"), _index(review, str(raw_ref["target"])))
    row = _resolve(ref, review)
    if row is None:
        return ref, "UNDECLARED", ["event_origin_unproven"]
    snapshot = row.get("source_snapshot") if isinstance(row.get("source_snapshot"), Mapping) else {}
    event_id = row.get("event_id") if row.get("event_id") is not None else snapshot.get("event_id")
    if str(event_id) != str(item["actual_event_id"]):
        return ref, "UNDECLARED", ["event_origin_identity_conflict"]
    truth_row = _resolve(truth_ref, review)
    if truth_row is not None and _provenance(truth_row) != _provenance(row):
        return ref, "UNDECLARED", ["event_origin_provenance_conflict"]
    return ref, _provenance(row), []


def _freeze_tie_order(raw: object, outputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("basis") not in {"none", "persisted_same_timestamp_order", "fixed_record_id_order"}:
        raise ScoringContractError("invalid_tie_order_basis")
    order = [_token(value) for value in _checked_list(raw.get("output_ids"))]
    if len(order) != len(set(order)) or (order and raw["basis"] == "none"):
        raise ScoringContractError("invalid_tie_order")
    if any(value not in outputs or outputs[value].get("record_sha256") != record_digest(outputs[value]) for value in order):
        raise ScoringContractError("tie_order_output_not_verified")
    if raw["basis"] == "persisted_same_timestamp_order":
        seqs = [outputs[value].get("ledger_seq") for value in order]
        if any(isinstance(seq, bool) or not isinstance(seq, int) or seq < 1 for seq in seqs) or len(set(seqs)) != len(seqs):
            return {"basis": "none", "output_ids": [], "reason_code": "persisted_order_evidence_missing"}
        expected = sorted(order, key=lambda value: (outputs[value]["ledger_seq"], value))
    else:
        expected = sorted(order)
    if expected != order:
        raise ScoringContractError("tie_order_contradicts_verified_source")
    return {"basis": raw["basis"], "output_ids": order}


def _checked_list(value: object) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_SET_ITEMS:
        raise ScoringContractError("set_list_size_or_type_invalid")
    return value


def _series_windows(review: Mapping[str, Any], item: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    windows, codes = [], []
    member = {**item, "truth_ref": {"status": "missing"}}
    for method in METHODS:
        candidates, reasons = _event_candidates(review, member, method)
        codes.extend(reasons)
        for candidate in candidates:
            interval = candidate["prediction"]["interval"]
            windows.append({"prediction_ref": candidate["prediction_ref"], "output_ref": candidate["output_ref"], "method": method,
                            "status": candidate["prediction"]["state"],
                            "predicted_start": utc_text(_EPOCH + timedelta(microseconds=interval[0])) if interval else None,
                            "predicted_end": utc_text(_EPOCH + timedelta(microseconds=interval[1])) if interval else None,
                            "reason_codes": candidate["prediction"]["reason_codes"]})
    return sorted(windows, key=lambda row: (row["prediction_ref"]["id"], row["output_ref"]["id"], row["method"])), sorted(set(codes))


def _freeze_series(review: Mapping[str, Any], raw: object, source: Mapping[str, Any]) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ScoringContractError("invalid_series_set")
    forecasts, truths, outputs = (_index(review, key) for key in ("forecasts", "truth_revisions", "outputs"))
    entries, seen, assigned_events = [], set(), {}
    for item in _checked_list(raw.get("entries")):
        series_id = _token(item.get("series_id"))
        if series_id in seen or item.get("target") not in TARGETS:
            raise ScoringContractError("duplicate_or_invalid_series")
        seen.add(series_id)
        outcome = item.get("requested_outcome", "unknown")
        if outcome not in {"cancelled", "postponed", "observed", "no_observed_event", "unknown"}:
            raise ScoringContractError("invalid_series_outcome")
        prediction_refs = [_ref("forecasts", value, forecasts) for value in _checked_list(item.get("forecast_ids"))]
        forecast_ids = {ref["id"] for ref in prediction_refs}
        output_refs = [_ref("outputs", oid, outputs) for oid, row in sorted(outputs.items()) if _output_forecast_ids(row) & forecast_ids]
        rows = [forecasts.get(ref["id"]) for ref in prediction_refs]
        provenances = {_provenance(row) for row in rows}
        provenance = next(iter(provenances)) if len(provenances) == 1 else "UNDECLARED"
        association = item.get("association_status", "unresolved")
        if association not in {"confirmed", "ambiguous", "unresolved"}:
            raise ScoringContractError("invalid_series_association")
        event_id = _token(item["outcome_event_id"]) if item.get("outcome_event_id") is not None else None
        if event_id is not None:
            key = (item["target"], event_id)
            if key in assigned_events:
                association = "ambiguous"
                assigned_events[key]["association_status"] = "ambiguous"
        entry = {"series_id": series_id, "target": item["target"], "scope": _scope(item.get("scope")),
                        "provenance": provenance, "prediction_refs": prediction_refs,
                        "output_refs": output_refs,
                        "outcome_fact_refs": [_ref("truth_revisions", value, truths) for value in _checked_list(item.get("outcome_truth_ids", []))],
                        "association_status": association, "outcome_event_id": event_id, "requested_outcome": outcome}
        entry["accepted_windows"], entry["window_reason_codes"] = _series_windows(review, entry)
        entries.append(entry)
        if event_id is not None:
            assigned_events[(item["target"], event_id)] = entry
    result = {"id": _token(raw.get("id")), "source_binding": dict(source), "entries": sorted(entries, key=lambda item: item["series_id"]),
              "observation_cutoff_at": _utc(raw.get("observation_cutoff_at")), "coverage": _coverage(raw.get("coverage"))}
    if _instant(result["observation_cutoff_at"]) > _instant(source["freeze_at"]):
        raise ScoringContractError("series_cutoff_after_source_freeze")
    result["set_hash"] = sha256_json(result)
    return result


def freeze_evaluation_set(
    review: Mapping[str, Any], definition: Mapping[str, Any], source_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze explicit membership/association, never nearest-event matching.

    review rows must come from a verified loader with record_sha256 supplied by
    the shared DTO-digest contract. Missing objects/digests remain explicit refs.
    """
    forecasts, outputs, truths = (_index(review, key) for key in ("forecasts", "outputs", "truth_revisions"))
    source = _source_binding(source_binding)
    if _source_binding(review.get("source_binding")) != source:
        raise ScoringContractError("source_binding_mismatch")
    cutoff = _utc(definition.get("observation_cutoff_at"))
    if _instant(cutoff) > _instant(source["freeze_at"]):
        raise ScoringContractError("observation_cutoff_after_source_freeze")
    rules = definition.get("rules")
    if not isinstance(rules, Mapping):
        raise ScoringContractError("set_rules_required")
    rules = {key: _token(rules.get(key), "set_rule_required") for key in
             ("inclusion", "exclusion", "deduplication", "adjudication_version")}
    events, seen, assigned = [], set(), {}
    for item in _checked_list(definition.get("events")):
        if not isinstance(item, Mapping) or item.get("target") not in TARGETS:
            raise ScoringContractError("invalid_event_target")
        event_id, target = _token(item.get("actual_event_id")), item["target"]
        key = (target, event_id)
        if key in seen:
            raise ScoringContractError("duplicate_event_membership")
        seen.add(key)
        association = item.get("association_status")
        if association not in {"confirmed", "ambiguous", "unresolved"}:
            raise ScoringContractError("association_status_required")
        raw_truth_ref = item.get("truth_ref")
        if not isinstance(raw_truth_ref, Mapping) or raw_truth_ref.get("target") != "truth_revisions":
            raise ScoringContractError("explicit_truth_revision_ref_required")
        truth_ref = _ref("truth_revisions", raw_truth_ref.get("id"), truths)
        prediction_refs = []
        for fid in _checked_list(item.get("forecast_ids")):
            fid = _token(fid)
            if fid in {ref["id"] for ref in prediction_refs}:
                raise ScoringContractError("duplicate_forecast_association")
            if fid in assigned and assigned[fid] != key:
                association = "ambiguous"
                for previous in events:
                    if any(ref["id"] == fid for ref in previous["prediction_refs"]):
                        previous["association_status"] = "ambiguous"
            assigned[fid] = key
            prediction_refs.append(_ref("forecasts", fid, forecasts))
        fids = {ref["id"] for ref in prediction_refs}
        output_ids = {oid for oid, row in outputs.items() if _output_forecast_ids(row) & fids}
        output_ids.update(_token(value) for value in _checked_list(item.get("output_ids", [])))
        output_refs = [_ref("outputs", oid, outputs) for oid in sorted(output_ids)]
        event_ref, provenance, origin_codes = _event_origin(review, item, truth_ref)
        events.append({"actual_event_id": event_id, "target": target, "scope": _scope(item.get("scope")),
                       "association_status": association, "provenance": provenance, "event_ref": event_ref, "origin_reason_codes": origin_codes,
                       "truth_ref": truth_ref, "prediction_refs": sorted(prediction_refs, key=lambda ref: ref["id"]),
                       "output_refs": sorted(output_refs, key=lambda ref: ref["id"])})
    tie = _freeze_tie_order(definition.get("tie_order", {"basis": "none", "output_ids": []}), outputs)
    result = {
        "schema_version": SET_SCHEMA_VERSION, "id": _token(definition.get("id")), "algorithm_version": ALGORITHM_VERSION,
        "source_binding": source, "package_binding": _package_binding(review),
        "core_collection_binding": core_collection_binding(review),
        "observation_cutoff_at": cutoff, "coverage": _coverage(definition.get("coverage")), "rules": rules,
        "tie_order": tie,
        "events": sorted(events, key=lambda item: (item["provenance"], item["target"], item["actual_event_id"])),
        "normal_refs": [_ref("forecasts", fid, forecasts) for fid, row in sorted(forecasts.items()) if row.get("target") == "NORMAL_WEEKLY"],
        "prediction_series_set": _freeze_series(review, definition.get("prediction_series_set"), source),
    }
    result["set_hash"] = sha256_json(result)
    result["record_sha256"] = record_digest(result)
    return result


def verify_assessment(review: Mapping[str, Any], assessment: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute an embedded assessment from its embedded frozen set/core.

    ZIP/manifest byte hashes identify the *original* source delivery. They are
    retained as provenance, not compared to a new ZIP containing this result.
    """
    if assessment.get("record_sha256") != record_digest(assessment):
        raise ScoringContractError("assessment_record_digest_mismatch")
    ref = assessment.get("evaluation_set_ref")
    if not isinstance(ref, Mapping) or ref.get("target") != "evaluation_sets":
        raise ScoringContractError("assessment_set_reference_invalid")
    frozen = _resolve(ref, review)
    if frozen is None:
        raise ScoringContractError("assessment_set_missing")
    reproduced = evaluate_review(review, frozen)
    if reproduced != dict(assessment):
        raise ScoringContractError("assessment_not_reproducible")
    return {"valid": True, "reproducible": True, "assessment_id": assessment["id"],
            "assessment_hash": assessment["assessment_hash"], "set_hash": assessment["set_hash"],
            "algorithm_version": ALGORITHM_VERSION, "prediction_quality_pass": None}


def _event_candidates(review: Mapping[str, Any], member: Mapping[str, Any], method: str) -> tuple[list[dict[str, Any]], list[str]]:
    candidates, codes = [], []
    output_rows = [(ref, _resolve(ref, review)) for ref in member["output_refs"]]
    if any(row is None for _, row in output_rows):
        # An explicitly missing execution may change either extreme even if
        # another output succeeded. It is not evidence of zero publication.
        codes.append("associated_output_missing")
    for ref in member["prediction_refs"]:
        forecast = _resolve(ref, review)
        if forecast is None:
            codes.append("associated_forecast_missing")
            continue
        if forecast.get("version_role") != "question_version" and forecast.get("method") in METHODS and forecast["method"] != method:
            continue
        if forecast.get("record_kind") != "online":
            codes.append("non_online_forecast_excluded" if forecast.get("record_kind") in {"replay", "baseline", "post_event_report"} else "forecast_mode_undeclared")
            continue
        if forecast.get("target") != member["target"]:
            codes.append("forecast_target_or_scope_conflict")
            continue
        matching = [(oref, output) for oref, output in output_rows if output is not None and str(ref["id"]) in _output_forecast_ids(output)]
        if not matching:
            missing_refs = any(row is None for _, row in output_rows)
            codes.append("associated_output_missing" if missing_refs or forecast.get("version_role") != "question_version" else "no_actual_published_output")
        for output_ref, output in matching:
            if output.get("publication_status") == "rejected" or output.get("status") in {"rejected", "failed", "error", "parse_failed"}:
                codes.append("failed_or_rejected_output_excluded")
                continue
            targets, target_refs = output.get("target_outputs"), output.get("target_refs")
            modern = isinstance(targets, Mapping) or forecast.get("version_role") == "question_version"
            material = forecast
            if modern:
                child = targets.get(member["target"]) if isinstance(targets, Mapping) else None
                link = target_refs.get(member["target"]) if isinstance(target_refs, Mapping) else None
                if not isinstance(child, Mapping) or not isinstance(link, Mapping):
                    codes.append("target_output_or_reference_missing")
                    continue
                link_ref = link.get("forecast_ref") if isinstance(link.get("forecast_ref"), Mapping) else link
                linked_id = link.get("forecast_id") if link.get("forecast_id") is not None else link_ref.get("id")
                if str(linked_id) != ref["id"] or child.get("target") != member["target"]:
                    codes.append("target_output_reference_conflict")
                    continue
                validation = child.get("validation")
                if not isinstance(validation, Mapping) or validation.get("valid") is not True:
                    codes.append("target_output_rejected_or_unvalidated")
                    continue
                material = child
            elif output.get("validation_status") != "accepted":
                codes.append("output_acceptance_unproven")
                continue
            # Methods and time/scope belong to the actual target execution.
            # A question_version's null method is never enriched from latest.
            if material.get("method") in METHODS and material["method"] != method:
                continue
            if material.get("method") not in METHODS:
                codes.append("forecast_method_undeclared")
                continue
            if not _scope_equal(material.get("scope"), member["scope"]):
                codes.append("forecast_target_or_scope_conflict")
                continue
            if material.get("lifecycle") in {"cancelled", "completed"}:
                codes.append("non_forward_target_lifecycle_excluded")
                continue
            if _provenance(forecast) != member["provenance"]:
                codes.append("forecast_provenance_conflict")
                continue
            if _provenance(output) != _provenance(forecast):
                codes.append("output_provenance_conflict")
                continue
            availability = availability_from_output(output)
            candidates.append({"id": f"{ref['id']}:{output_ref['id']}", "forecast_id": ref["id"], "output_id": output_ref["id"],
                               "prediction_ref": dict(ref), "output_ref": dict(output_ref),
                               "prediction": _prediction(material), "availability": availability})
    return candidates, sorted(set(codes))


def _lead(availability: Mapping[str, Any], interval: Sequence[int]) -> dict[str, Any]:
    at = _instant(availability["at"])
    start, end = interval
    if availability["kind"] == "observed_upper_bound":
        return {"kind": "lower_bound", "minimum_hours": (start - at) / _HOUR_US, "maximum_hours": None}
    return {"kind": "exact_availability_interval", "minimum_hours": (start - at) / _HOUR_US, "maximum_hours": (end - at) / _HOUR_US}


def _event_result(review: Mapping[str, Any], member: Mapping[str, Any], method: str, boundary: str, threshold: int, tie: Mapping[str, Any]) -> dict[str, Any]:
    truth_row = _resolve(member["truth_ref"], review)
    truth = _truth(truth_row)
    candidates, codes = _event_candidates(review, member, method)
    codes.extend(truth["reason_codes"])
    codes.extend(member.get("origin_reason_codes") or [])
    blockers = {
        "associated_forecast_missing", "associated_output_missing", "forecast_mode_undeclared", "forecast_method_undeclared",
        "forecast_target_or_scope_conflict", "forecast_provenance_conflict", "output_acceptance_unproven", "output_provenance_conflict",
        "target_output_or_reference_missing", "target_output_reference_conflict",
    }
    if member["association_status"] != "confirmed":
        codes.append("event_association_unresolved")
    if truth_row is not None:
        if str(truth_row.get("event_id")) != member["actual_event_id"] or not _scope_equal(truth_row.get("scope"), member["scope"]):
            codes.append("truth_event_or_scope_conflict")
            blockers.add("truth_event_or_scope_conflict")
        expected_type = "FULL_RESET" if member["target"] == "EXTRA_FULL" else "SPECIAL_RESET"
        if (truth_row.get("actual_event_type") or truth_row.get("event_type")) != expected_type or (member["target"] == "BANKED" and truth_row.get("special_type") != "BANKED"):
            codes.append("truth_target_conflict")
            blockers.add("truth_target_conflict")
    # Stable same-timestamp output order is expanded into candidate identities.
    order = [row["id"] for oid in tie["output_ids"] for row in candidates if row["output_id"] == oid]
    selection = select_candidate(candidates, truth, boundary, order)
    codes.extend(selection["reason_codes"])
    pairing_conflicts = {"event_association_unresolved", "event_origin_identity_conflict", "event_origin_provenance_conflict"}
    if set(codes) & blockers or (selection["status"] == "selected" and set(codes) & pairing_conflicts):
        selection = {"status": "undetermined", "selected": None}
    category, metrics, lead = selection["status"], None, None
    selected = selection["selected"]
    if category == "selected":
        metrics = _metrics(selected["prediction"]["interval"], truth["interval"], _HOUR_US)
        category = classify_error(metrics, threshold)
    if selected and truth.get("trusted") and _timing(selected, truth) == "pre":
        lead = _lead(selected["availability"], truth["interval"])
    return {
        "actual_event_id": member["actual_event_id"], "truth_ref": dict(member["truth_ref"]), "event_ref": dict(member["event_ref"]), "category": category,
        "reason_codes": sorted(set(codes)), "selected_prediction_ref": selected.get("prediction_ref") if selected else None,
        "selected_output_ref": selected.get("output_ref") if selected else None,
        "availability": selected.get("availability") if selected else None, "lead": lead, "metrics": metrics,
    }


def _series_outcomes(review: Mapping[str, Any], series_set: Mapping[str, Any] | None) -> dict[str, Any]:
    if series_set is None:
        return {"status": "NOT_FROZEN", "groups": []}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in series_set["entries"]:
        codes = []
        windows, window_codes = _series_windows(review, item)
        if windows != item["accepted_windows"] or window_codes != item["window_reason_codes"]:
            raise ScoringContractError("series_frozen_window_mismatch")
        forecasts = [_resolve(ref, review) for ref in item["prediction_refs"]]
        facts = [_resolve(ref, review) for ref in item["outcome_fact_refs"]]
        outcome = item["requested_outcome"]
        valid_forecasts = bool(forecasts) and all(row and row.get("series_id") == item["series_id"] and row.get("target") == item["target"]
                                                and (row.get("version_role") == "question_version" or _scope_equal(row.get("scope"), item["scope"]))
                                                and _provenance(row) == item["provenance"] for row in forecasts)
        if not valid_forecasts:
            codes.append("series_prediction_identity_unproven")
        if outcome in {"cancelled", "postponed", "observed"}:
            if item["association_status"] != "confirmed" or item["outcome_event_id"] is None:
                codes.append("series_event_association_unproven")
            phases = {"completed"} if outcome == "observed" else {"delayed", "postponed"} if outcome == "postponed" else {outcome}
            proven = False
            for fact in facts:
                if not fact or fact.get("truth_status") not in {"ADJUDICATED", "fixture_adjudicated"} or _provenance(fact) != item["provenance"]:
                    continue
                if str(fact.get("event_id")) != item["outcome_event_id"]:
                    continue
                if fact.get("truth_status") == "fixture_adjudicated" and fact.get("is_synthetic") is not True:
                    continue
                expected_type = "FULL_RESET" if item["target"] == "EXTRA_FULL" else "SPECIAL_RESET"
                if (fact.get("actual_event_type") or fact.get("event_type")) != expected_type or (item["target"] == "BANKED" and fact.get("special_type") != "BANKED"):
                    continue
                snapshot = fact.get("source_snapshot") or {}
                if (fact.get("execution_stage") or snapshot.get("execution_stage")) in phases and _scope_equal(fact.get("scope"), item["scope"]):
                    proven = True
            if not proven:
                codes.append("series_outcome_fact_unproven")
        elif outcome == "no_observed_event":
            coverage = series_set["coverage"]
            intervals = [[_instant(window["predicted_start"]), _instant(window["predicted_end"])] if window["status"] == "known" else None
                         for window in windows]
            complete = (coverage["status"] == "complete" and coverage["start"] is not None and bool(intervals) and all(intervals))
            if complete:
                complete = (_instant(coverage["start"]) <= min(interval[0] for interval in intervals)
                            and _instant(coverage["end"]) >= max(interval[1] for interval in intervals)
                            and _instant(series_set["observation_cutoff_at"]) >= _instant(coverage["end"]))
            if not complete:
                codes.append("observation_coverage_insufficient")
            # Even complete collection coverage isn't proof about all reality.
            outcome = "no_event_observed_complete_coverage"
        else:
            codes.append("series_outcome_unknown")
        if codes:
            outcome = "undetermined"
        groups.setdefault((item["provenance"], item["target"]), []).append({"series_id": item["series_id"], "outcome": outcome,
                                                                               "reason_codes": codes, "outcome_fact_refs": item["outcome_fact_refs"],
                                                                               "accepted_windows": windows})
    return {"status": "SEPARATE_SERIES_DENOMINATOR", "set_hash": series_set["set_hash"], "observation_cutoff_at": series_set["observation_cutoff_at"],
            "coverage": dict(series_set["coverage"]), "groups": [
                {"provenance": key[0], "target": key[1], "K": len(rows), "counts": dict(sorted(Counter(row["outcome"] for row in rows).items())), "series": rows}
                for key, rows in sorted(groups.items())], "reality_false_positive_claim": False}


def evaluate_review(review: Mapping[str, Any], evaluation_set: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic event-N panels; results never mutate the set/source/history."""
    if evaluation_set.get("schema_version") != SET_SCHEMA_VERSION or evaluation_set.get("algorithm_version") != ALGORITHM_VERSION:
        raise ScoringContractError("unsupported_set_or_algorithm_version")
    body = {key: value for key, value in evaluation_set.items() if key not in {"set_hash", "record_sha256"}}
    if sha256_json(body) != evaluation_set.get("set_hash"):
        raise ScoringContractError("evaluation_set_hash_mismatch")
    if _source_binding(review.get("source_binding")) != evaluation_set["source_binding"]:
        raise ScoringContractError("source_binding_mismatch")
    _package_binding(review)
    if core_collection_binding(review) != evaluation_set["core_collection_binding"]:
        raise ScoringContractError("core_collection_binding_mismatch")
    series_set = evaluation_set.get("prediction_series_set")
    if series_set is not None and sha256_json({key: value for key, value in series_set.items() if key != "set_hash"}) != series_set.get("set_hash"):
        raise ScoringContractError("series_set_hash_mismatch")
    events = evaluation_set["events"]
    provenances = sorted({item["provenance"] for item in events}) or ["EMPTY"]
    panels = []
    for provenance in provenances:
        for target in TARGETS:
            members = [item for item in events if item["provenance"] == provenance and item["target"] == target]
            for method in METHODS:
                for boundary in ("first", "last"):
                    for threshold in (24, 48):
                        results = [_event_result(review, member, method, boundary, threshold, evaluation_set["tie_order"]) for member in members]
                        counts = {key: sum(row["category"] == key for row in results) for key in CATEGORIES}
                        size = len(members)
                        if sum(counts.values()) != size:
                            raise ScoringContractError("classification_not_exhaustive")
                        definite = counts["definite_hit"] + counts["definite_miss"]
                        coverage_counts = {key: sum((row["metrics"] or {}).get("coverage") == key for row in results) for key in
                                           ("definitely_covered", "definitely_not_covered", "coverage_indeterminate")}
                        coverage_counts["not_evaluable"] = size - sum(coverage_counts.values())
                        panels.append({"provenance": provenance, "target": target, "method": method, "boundary": boundary,
                                       "threshold_hours": threshold, "N": size, "counts": counts, "coverage_counts": coverage_counts,
                                       "ratios": {"definite_hits_over_N": counts["definite_hit"] / size if size else None,
                                                  "auxiliary_definite_only_hit_rate": counts["definite_hit"] / definite if definite else None,
                                                  "auxiliary_definite_only_denominator": definite}, "events": results})
    refs = lambda key: [ref for item in events for ref in (item[key] if isinstance(item[key], list) else [item[key]])]
    digest = evaluation_set.get("record_sha256")
    if digest != record_digest(evaluation_set):
        raise ScoringContractError("evaluation_set_record_digest_mismatch")
    result = {
        "schema_version": ASSESSMENT_SCHEMA_VERSION, "algorithm_version": ALGORITHM_VERSION,
        "source_binding": dict(evaluation_set["source_binding"]), "package_binding": dict(evaluation_set["package_binding"]),
        "core_collection_binding": evaluation_set["core_collection_binding"],
        "evaluation_set_ref": {"target": "evaluation_sets", "id": evaluation_set["id"], "status": "included" if digest else "missing",
                               "reason": None if digest else "verified_record_digest_missing", "sha256": digest},
        "set_hash": evaluation_set["set_hash"], "truth_refs": refs("truth_ref"), "prediction_refs": refs("prediction_refs"), "output_refs": refs("output_refs"),
        "panels": panels, "normal": {"status": "REFERENCE_ONLY", "history_count": len(evaluation_set["normal_refs"]), "refs": evaluation_set["normal_refs"]},
        "series_outcomes": _series_outcomes(review, series_set),
        "limitations": ["package_integrity_not_prediction_quality", "no_accuracy_acceptance_threshold", "provenance_cohorts_not_combined",
                         "normal_excluded_from_event_N", "observations_are_not_exact_availability", "declared_coverage_not_reality_certification"],
    }
    result["assessment_hash"] = sha256_json(result)
    result["id"] = f"assessment-{result['assessment_hash']}"
    result["record_sha256"] = record_digest(result)
    return result
