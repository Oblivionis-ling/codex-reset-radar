"""Loaded, shared target/time contract. No database writes or model calls."""
from __future__ import annotations

import copy
import math
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .review_common import sha256_json

PREDICTION_CONTRACT_VERSION = "crr-prediction-targets-v1"
PREDICTION_ALGORITHM_VERSION = "three-lines-time-v1"
PREDICTION_TARGETS = ("EXTRA_FULL", "BANKED")
ALL_PREDICTION_TARGETS = ("NORMAL_WEEKLY", *PREDICTION_TARGETS)
PredictionTarget = Literal["NORMAL_WEEKLY", "EXTRA_FULL", "BANKED"]
PREDICTION_API_VERSION = "prediction-three-lines-v1"
PREDICTION_FORMS = frozenset({"point", "range", "date", "start_only", "end_only", "relative", "unknown"})
PREDICTION_METHODS = frozenset({"official_time_extraction", "model_inference"})
LIFECYCLES = frozenset({"planned", "announced", "delayed", "cancelled", "completed", "unknown"})
TARGET_FIELDS = frozenset({
    "target", "status", "method", "scope", "predicted_start", "predicted_end", "prediction_form",
    "source_timezone", "precision", "time_basis", "expression", "relative_anchor_at", "relative_offset_seconds",
    "reason", "unresolved_reason", "evidence_post_ids", "evidence_refs", "lifecycle",
    "date_boundaries", "timezone_status", "validation", "target_output_id", "output_revision",
    "resolved_prediction_form", "resolution_basis",
})
PREDICTION_PROMPT_EXTENSION = (
    "另须返回 predictions 对象，键恰为 EXTRA_FULL 与 BANKED：前者仅预测下一次额外完整重置实际开始，"
    "后者仅预测独立重置卡实际开始发放，不是个人到账或用卡。两个日期目标独立，不改变上述 Full 四等级含义。"
    "逐目标声明 KNOWN 或 UNKNOWN、方法、范围、形式、原时间表达/时区/精度、原帖相对时间锚点、理由、引用及生命周期。"
    "缺目标不是 UNKNOWN；没有独立前瞻依据须明确 UNKNOWN 及原因，不能使用 Normal 加七天代替。"
    "official_time_extraction 仅用于可核验官方明确未来计划，time_basis=official_planned；"
    "evidence_refs 的 evidence_quote 必须逐作者连续原文引句，不能把第三方父帖日期当作官方承诺。"
    "model_inference 是推断，不伪称官方。仅引用实际 context 暴露且有正文的版本；Banked 引用仅放自己的目标，"
    "不得写入旧 Full evidence_post_ids。日期不是午夜执行时刻，单边不补另一端，无时区不补 UTC。"
    "相对时间以对应说话人的 posted_at 为锚，不以 Judge/抓取时间滚动。延期/取消/完成单独写 lifecycle，"
    "已完成计划不是下一次预测；同帖独立未来效果仍需保留。\n"
)


class TargetContractError(ValueError):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


class PredictionTargetsError(ValueError):
    def __init__(self, structured_output: dict[str, Any]):
        super().__init__("No prediction target passed the required contract")
        self.reason_code = "ALL_PREDICTION_TARGETS_REJECTED"
        self.structured_output = structured_output


def prediction_schema() -> dict[str, Any]:
    return {target: {
        "target": target, "status": "KNOWN|UNKNOWN", "method": "official_time_extraction|model_inference",
        "scope": {"value": "unknown|all_paid|work_and_codex|plus_pro|partial_users|banked_only", "certainty": "说明范围来源"},
        "predicted_start": None, "predicted_end": None,
        "prediction_form": "point|range|date|start_only|end_only|relative|unknown",
        "source_timezone": None, "precision": "day|minute|second|fractional_second|unknown",
        "time_basis": "official_planned|model_inference|relative_to_post|unknown",
        "expression": None, "relative_anchor_at": None, "relative_offset_seconds": None,
        "reason": "本目标简短依据", "unresolved_reason": None, "evidence_post_ids": [], "evidence_refs": [],
        "lifecycle": "planned|announced|delayed|cancelled|completed|unknown",
    } for target in PREDICTION_TARGETS}


def _utc(value: str | datetime) -> str:
    # Reuse the existing conversion; new-contract timezone checks precede it.
    from .db import normalise_time
    if value is None:
        raise TargetContractError("TIME_MISSING")
    return normalise_time(value)


def _zone(value: str | None):
    if value is None:
        return None
    if not isinstance(value, str):
        raise TargetContractError("INVALID_TIMEZONE")
    if value in {"Z", "UTC", "+00:00", "UTC+00:00"}:
        return UTC
    match = re.fullmatch(r"(?:UTC)?([+-])(\d{1,2})(?::?(\d{2}))?", value)
    if match:
        hours, minutes = int(match[2]), int(match[3] or 0)
        if hours > 23 or minutes > 59:
            raise TargetContractError("INVALID_TIMEZONE")
        return timezone(timedelta(minutes=(1 if match[1] == "+" else -1) * (hours * 60 + minutes)))
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise TargetContractError("TIMEZONE_DATA_UNAVAILABLE_OR_INVALID") from None


def _instant(value: Any, source_timezone: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise TargetContractError("INVALID_INSTANT")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise TargetContractError("INVALID_INSTANT") from None
    zone = _zone(source_timezone)
    if parsed.tzinfo is None:
        if zone is None:
            raise TargetContractError("TIMEZONE_NOT_STATED")
        first, second = parsed.replace(tzinfo=zone, fold=0), parsed.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise TargetContractError("AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME")
        parsed = first
    # Aware values may already be normalized UTC. Original source zone is
    # independent metadata, not a claim that the value still uses that offset.
    return parsed


def normalize_prediction_time(value: dict[str, Any]) -> dict[str, Any]:
    """Preserve form; date bounds are labelled and one-sided inputs stay one-sided."""
    form = value.get("prediction_form")
    if form not in PREDICTION_FORMS:
        raise TargetContractError("INVALID_PREDICTION_FORM")
    output = {key: copy.deepcopy(value.get(key)) for key in (
        "prediction_form", "source_timezone", "precision", "time_basis", "expression", "relative_anchor_at", "relative_offset_seconds",
    )}
    start, end = value.get("predicted_start"), value.get("predicted_end")
    if form == "unknown":
        if start is not None or end is not None:
            raise TargetContractError("UNKNOWN_WITH_TIME")
        return {**output, "predicted_start": None, "predicted_end": None}
    if form == "date":
        expression = value.get("expression") or start
        if not isinstance(expression, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expression):
            raise TargetContractError("INVALID_DATE_EXPRESSION")
        zone = _zone(value.get("source_timezone"))
        if zone is None:
            raise TargetContractError("TIMEZONE_NOT_STATED")
        try:
            day = datetime.fromisoformat(expression).replace(tzinfo=zone)
        except ValueError:
            raise TargetContractError("INVALID_DATE_EXPRESSION") from None
        return {**output, "expression": expression, "precision": "day", "predicted_start": _utc(day),
                "predicted_end": _utc(day + timedelta(days=1)), "date_boundaries": "closed_conservative_local_day_envelope_not_execution_instants"}
    if form == "relative":
        anchor = _instant(value.get("relative_anchor_at"), None)
        if anchor is None:
            raise TargetContractError("RELATIVE_ANCHOR_MISSING")
        expression = value.get("expression")
        offset = value.get("relative_offset_seconds")
        if offset is not None:
            if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset) or abs(offset) > 366 * 86400:
                raise TargetContractError("INVALID_RELATIVE_OFFSET")
            resolved = anchor + timedelta(seconds=offset)
        else:
            match = re.fullmatch(r"(?:tomorrow|明天)(?:约|\s)*(\d{1,2}):(\d{2})(?:\s*(?:UTC[+-]\d{1,2}(?::\d{2})?))?", str(expression), re.IGNORECASE)
            zone = _zone(value.get("source_timezone"))
            if not match or zone is None:
                raise TargetContractError("RELATIVE_EXPRESSION_UNRESOLVED")
            local = anchor.astimezone(zone) + timedelta(days=1)
            try:
                local_time = local.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0, tzinfo=None)
                resolved = _instant(local_time.isoformat(), value.get("source_timezone"))
            except ValueError:
                raise TargetContractError("RELATIVE_EXPRESSION_UNRESOLVED") from None
        if end is not None:
            raise TargetContractError("RELATIVE_END_NOT_PROVEN")
        if start is not None and _utc(_instant(start, value.get("source_timezone"))) != _utc(resolved):
            raise TargetContractError("RELATIVE_TIME_CONFLICT")
        return {**output, "relative_anchor_at": _utc(anchor), "predicted_start": _utc(resolved), "predicted_end": None,
                "resolved_prediction_form": "point", "resolution_basis": "source_posted_at_and_explicit_relative_expression"}
    start_dt, end_dt = _instant(start, value.get("source_timezone")), _instant(end, value.get("source_timezone"))
    if form == "point" and end_dt is not None and start_dt is not None and start_dt.astimezone(UTC) == end_dt.astimezone(UTC):
        return {**output, "predicted_start": _utc(start_dt), "predicted_end": _utc(end_dt)}
    if form in {"point", "start_only"} and (start_dt is None or end_dt is not None):
        raise TargetContractError("INVALID_POINT_OR_START_ONLY")
    if form == "end_only" and (end_dt is None or start_dt is not None):
        raise TargetContractError("INVALID_END_ONLY")
    if form == "range" and (start_dt is None or end_dt is None):
        raise TargetContractError("RANGE_ENDPOINT_MISSING")
    if start_dt and end_dt and start_dt.astimezone(UTC) > end_dt.astimezone(UTC):
        raise TargetContractError("REVERSED_TIME_RANGE")
    return {**output, "predicted_start": _utc(start_dt) if start_dt else None, "predicted_end": _utc(end_dt) if end_dt else None}


def exposed_evidence(context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Only actual request bodies; an event ID or a mutable DB row is not evidence."""
    found: dict[str, list[dict[str, Any]]] = {}
    for post in [*(context.get("posts") or []), *(context.get("event_source_posts") or [])]:
        version = post.get("input_hash")
        if not version or not post.get("text"):
            continue
        source = {"tweet_id": str(post["tweet_id"]), "source_version": version, "role": post.get("role") or "target_post",
                  "author": post.get("author"), "text": post["text"], "posted_at": post.get("posted_at"), "analysis": post.get("analysis") or {}}
        found.setdefault(source["tweet_id"], []).append(source)
        for depth, node in enumerate((post.get("reply_context") or {}).get("nodes") or [], 1):
            if not node.get("text") or node.get("relation_source") != "x_replied_to_field":
                continue
            parent = {**node, "tweet_id": str(node["tweet_id"]), "source_version": sha256_json(node),
                      "role": "direct_parent" if depth == 1 else "ancestor", "target_tweet_id": str(post["tweet_id"]),
                      "target_input_version": version, "analysis": node.get("analysis") or {}}
            found.setdefault(parent["tweet_id"], []).append(parent)
    return found


def _quoted_zone_matches(quote: str, zone_name: str | None, instant: datetime) -> bool:
    """Verify original timezone from the quote, not from normalized UTC output."""
    zone = _zone(zone_name)
    if zone is None:
        return False
    if re.search(r"(?<![\w/])" + re.escape(zone_name) + r"(?![\w/]|[+-]\d)", quote):
        return True
    # A numeric offset proves a fixed-offset zone, not a named zone's DST rules.
    if isinstance(zone, ZoneInfo):
        return False
    offsets = re.findall(r"UTC[+-]\d{1,2}(?::\d{2})?|[+-]\d{2}:\d{2}|(?<=\d)Z\b|\bUTC\b(?![+-]\d)", quote)
    return any(_zone(offset).utcoffset(instant) == zone.utcoffset(instant) for offset in offsets)


def _official_plan_matches(value: dict[str, Any], times: dict[str, Any], source: dict[str, Any], effect: dict[str, Any]) -> bool:
    """Fail closed unless the complete start-time form is recoverable from a quote."""
    quote = effect.get("evidence_quote") or ""
    if not quote or quote not in (source.get("evidence_quote") or ""):
        return False
    scope = lambda item: item.get("value") if isinstance(item, dict) else item
    if scope(effect.get("scope")) != scope(value.get("scope")):
        return False
    start = _instant(effect.get("event_time_start"), None)
    end = _instant(effect.get("event_time_end"), None)
    source_form = effect.get("prediction_form") or effect.get("time_form")
    requested_form = value["prediction_form"]
    expression = value.get("expression")
    if expression and expression not in quote:
        return False
    if requested_form == "relative":
        return bool(start and end is None and value.get("precision") == "minute"
                    and _utc(start) == times.get("predicted_start") and expression
                    and _quoted_zone_matches(quote, value.get("source_timezone"), start))
    literals = re.findall(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?", quote)
    if requested_form == "date":
        if literals or not start or not expression or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expression):
            return False
        if source_form not in {None, "date"} or value.get("precision") != "day" or not _quoted_zone_matches(quote, value.get("source_timezone"), start):
            return False
        return _utc(start) == times["predicted_start"] and (end is None or _utc(end) == times["predicted_end"])
    if not literals:
        return False
    parsed = [_instant(item, value.get("source_timezone")) for item in literals]
    literal_times = list(dict.fromkeys(_utc(item) for item in parsed))
    # Without explicit start-uncertainty metadata, two endpoints could mean
    # activity duration. Do not promote them to a range for the execution start.
    if source_form is None:
        if len(literal_times) != 1 or end is not None and _utc(end) != _utc(start):
            return False
        if re.search(r"\b(?:by|before|after|between|until)\b|之前|之后|以前|以后|不晚于|不早于", quote, re.IGNORECASE):
            return False
        source_form = "point"
    if source_form != requested_form:
        return False
    if source_form == "start_only" and not re.search(r"\bafter\b|之后|以后|不早于", quote, re.IGNORECASE):
        return False
    if source_form == "end_only" and not re.search(r"\b(?:by|before|until)\b|之前|以前|不晚于", quote, re.IGNORECASE):
        return False
    if source_form == "range" and (len(literal_times) != 2 or not re.search(r"\bbetween\b|之间", quote, re.IGNORECASE)
                                   or re.search(r"\b(?:ends?|finish(?:es)?|completes?)\b|结束|完成", quote, re.IGNORECASE)):
        return False
    expected_start, expected_end = _utc(start) if start else None, _utc(end) if end else None
    if times.get("predicted_start") != expected_start:
        return False
    if requested_form == "point":
        if times.get("predicted_end") not in {None, expected_start} or expected_end not in {None, expected_start}:
            return False
    elif times.get("predicted_end") != expected_end:
        return False
    endpoints = {stamp for stamp in (expected_start, expected_end) if stamp}
    if endpoints != set(literal_times):
        return False
    precision = "fractional_second" if any(re.search(r"\d{2}:\d{2}:\d{2}\.\d+", raw) for raw in literals) else "second" if any(re.search(r"\d{2}:\d{2}:\d{2}", raw) for raw in literals) else "minute"
    if value.get("precision") != precision or effect.get("time_precision", effect.get("precision", precision)) != precision:
        return False
    if effect.get("source_timezone") and effect["source_timezone"] != value.get("source_timezone"):
        return False
    return all(_quoted_zone_matches(raw + " " + quote, value.get("source_timezone"), instant) for raw, instant in zip(literals, parsed))


def _validate_target(target: str, value: Any, sources: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TargetContractError("MISSING_TARGET" if value is None else "INVALID_TARGET_OBJECT")
    if value.get("target") != target:
        raise TargetContractError("TARGET_KEY_MISMATCH")
    required = {"status", "method", "scope", "predicted_start", "predicted_end", "prediction_form",
                "source_timezone", "precision", "time_basis", "expression", "relative_anchor_at",
                "reason", "unresolved_reason", "evidence_post_ids", "lifecycle"}
    if required - value.keys():
        raise TargetContractError("TARGET_FIELDS_MISSING")
    if value.get("precision") not in {"day", "minute", "second", "fractional_second", "unknown"} or not isinstance(value.get("time_basis"), str):
        raise TargetContractError("INVALID_PRECISION_OR_TIME_BASIS")
    for key in ("source_timezone", "expression", "relative_anchor_at", "unresolved_reason"):
        if value.get(key) is not None and not isinstance(value[key], str):
            raise TargetContractError("INVALID_TIME_METADATA_TYPE")
    if value.get("status") not in {"KNOWN", "UNKNOWN"}:
        raise TargetContractError("INVALID_DATE_STATUS")
    if value.get("method") not in PREDICTION_METHODS:
        raise TargetContractError("INVALID_METHOD")
    scope = value.get("scope")
    if not isinstance(scope, (str, dict)) or not (scope if isinstance(scope, str) else scope.get("value")):
        raise TargetContractError("SCOPE_MISSING")
    if value.get("lifecycle") not in LIFECYCLES:
        raise TargetContractError("INVALID_LIFECYCLE")
    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise TargetContractError("REASON_MISSING")
    ids, refs = value.get("evidence_post_ids"), value.get("evidence_refs", [])
    if not isinstance(ids, list) or not isinstance(refs, list) or len(ids) + len(refs) > 64:
        raise TargetContractError("INVALID_EVIDENCE_REFERENCES")
    selected = []
    for evidence in [*ids, *refs]:
        ref = evidence if isinstance(evidence, dict) else {"tweet_id": str(evidence)}
        candidates = sources.get(str(ref.get("tweet_id")), [])
        candidates = [candidate for candidate in candidates if all(ref.get(key) is None or ref[key] == candidate.get(key) for key in ("source_version", "role", "target_tweet_id"))]
        unique = {sha256_json(candidate): candidate for candidate in candidates}
        if len(unique) != 1:
            raise TargetContractError("EVIDENCE_NOT_EXPOSED_OR_VERSION_AMBIGUOUS")
        source = next(iter(unique.values()))
        quote = ref.get("evidence_quote")
        if quote is not None and (not isinstance(quote, str) or not quote or quote not in source["text"]):
            raise TargetContractError("EVIDENCE_QUOTE_NOT_VERBATIM")
        selected.append({**source, "evidence_quote": quote})
    if value["status"] == "UNKNOWN":
        if value.get("predicted_start") is not None or value.get("predicted_end") is not None:
            raise TargetContractError("UNKNOWN_WITH_TIME")
        if not value.get("unresolved_reason"):
            raise TargetContractError("UNKNOWN_REASON_MISSING")
        if value.get("prediction_form") not in {"unknown", "relative"}:
            raise TargetContractError("UNKNOWN_FORM_CONFLICT")
        if value.get("prediction_form") == "relative" and not value.get("expression"):
            raise TargetContractError("RELATIVE_EXPRESSION_MISSING")
        if value.get("relative_anchor_at") is not None:
            _instant(value["relative_anchor_at"], None)
        times = {key: copy.deepcopy(value.get(key)) for key in ("predicted_start", "predicted_end", "prediction_form", "source_timezone", "precision", "time_basis", "expression", "relative_anchor_at", "relative_offset_seconds")}
    else:
        if not selected:
            raise TargetContractError("KNOWN_WITHOUT_EVIDENCE")
        times = normalize_prediction_time(value)
        if value.get("prediction_form") == "unknown":
            raise TargetContractError("KNOWN_WITH_UNKNOWN_FORM")
        if value.get("prediction_form") == "relative":
            if not any(source.get("posted_at") and _utc(source["posted_at"]) == times["relative_anchor_at"] for source in selected):
                raise TargetContractError("RELATIVE_ANCHOR_NOT_SOURCE_POST_TIME")
            if value.get("relative_offset_seconds") is not None:
                match = re.fullmatch(r"(?:in\s*)?(\d+(?:\.\d+)?)\s*(hours?|minutes?|小时后|分钟后)", value.get("expression") or "", re.IGNORECASE)
                scale = 3600 if match and match[2].lower() in {"hour", "hours", "小时后"} else 60
                if not match or float(match[1]) * scale != value["relative_offset_seconds"] or not any(value["expression"] in source["text"]
                        and source.get("posted_at") and _utc(source["posted_at"]) == times["relative_anchor_at"] for source in selected):
                    raise TargetContractError("RELATIVE_OFFSET_SEMANTICS_NOT_VERIFIED")
            elif not any(value.get("expression") and value["expression"] in source["text"]
                         and source.get("posted_at") and _utc(source["posted_at"]) == times["relative_anchor_at"]
                         and _quoted_zone_matches(source.get("evidence_quote") or source["text"], value.get("source_timezone"), _instant(times["predicted_start"], None))
                         for source in selected):
                raise TargetContractError("RELATIVE_CLOCK_SEMANTICS_NOT_VERIFIED")
    if value["method"] == "official_time_extraction":
        if value["status"] != "KNOWN" or value.get("time_basis") != "official_planned":
            raise TargetContractError("OFFICIAL_PLAN_NOT_VERIFIED")
        planned = []
        for source in selected:
            if str(source.get("author") or "").lstrip("@").lower() not in {"thsottiaux", "openai"} or not source.get("evidence_quote"):
                continue
            for effect in source["analysis"].get("effects") or []:
                mechanism = effect.get("event_type") == "FULL_RESET" if target == "EXTRA_FULL" else effect.get("event_type") == "SPECIAL_RESET" and effect.get("special_type") in {"BANKED", "RESET_CARD"}
                if mechanism and effect.get("claim_kind") == "planned_occurrence" and effect.get("execution_stage") == "announced" and effect.get("time_basis") == "explicit_text" and effect.get("evidence_quote") and effect["evidence_quote"] in source["evidence_quote"]:
                    if _official_plan_matches(value, times, source, effect):
                        planned.append(source)
        if not planned:
            raise TargetContractError("OFFICIAL_PLAN_NOT_VERIFIED")
    output = safe_target_output(value)
    output.update(times)
    output["reason"] = output["reason"][:1200]
    references = [{key: child for key, child in source.items() if key in {"tweet_id", "source_version", "role", "author", "posted_at", "target_tweet_id", "target_input_version", "evidence_quote"}} for source in selected]
    output["evidence_refs"] = list({sha256_json(ref): ref for ref in references}.values())
    output["validation"] = {"valid": True, "reason": "VALID", "date_status": output["status"]}
    return output


def validate_predictions(value: Any, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sources, targets = exposed_evidence(context), {}
    accepted = 0
    for target in PREDICTION_TARGETS:
        raw = value.get(target) if isinstance(value, dict) else None
        if isinstance(raw, dict) and isinstance(raw.get("validation"), dict) and raw["validation"].get("valid") is False:
            raw = raw.get("rejected_output")
        try:
            targets[target] = _validate_target(target, raw, sources)
            accepted += 1
        except (TargetContractError, TypeError, ValueError, OverflowError) as error:
            targets[target] = {"target": target, "status": None, "validation": {"valid": False, "reason": getattr(error, "reason_code", "INVALID_TARGET_TIME_OR_SHAPE")},
                               "rejected_output": safe_target_output(raw) if isinstance(raw, dict) else None}
    return targets, {"status": "accepted" if accepted == 2 else "partial" if accepted else "rejected", "accepted_targets": [key for key, child in targets.items() if child["validation"]["valid"]]}


def safe_target_output(value: dict[str, Any]) -> dict[str, Any]:
    """Bounded contract-only result, including rejected results, not raw provider JSON."""
    output = {}
    for key, child in value.items():
        if key not in TARGET_FIELDS or key in {"validation", "target_output_id", "output_revision"}:
            continue
        if isinstance(child, str):
            output[key] = child[:2000]
        elif child is None or isinstance(child, (bool, int)) or isinstance(child, float) and math.isfinite(child):
            output[key] = child
        elif key == "scope" and isinstance(child, dict):
            output[key] = {field: item[:200] for field, item in child.items() if field in {"value", "certainty"} and isinstance(item, str)}
        elif key == "evidence_post_ids" and isinstance(child, list):
            output[key] = [item[:100] for item in child[:64] if isinstance(item, str)]
        elif key == "evidence_refs" and isinstance(child, list):
            output[key] = [{field: item[:500] for field, item in ref.items() if field in {"tweet_id", "source_version", "role", "target_tweet_id", "evidence_quote"} and isinstance(item, str)} for ref in child[:64] if isinstance(ref, dict)]
    return output


def next_reset_baseline(last_full_reset: dict[str, Any] | None, *, as_of=None) -> dict[str, Any]:
    """The only +7 implementation. Preserve proxy/legacy anchor limitations."""
    empty = {"target": "NORMAL_WEEKLY", "method": None, "time_basis": "user_full_plus_7d", "prediction_form": "unknown", "time_form": "unknown",
             "predicted_start": None, "predicted_end": None, "estimated_at": None, "basis": "最近一次完整 Reset 尚无足够证据确认。"}
    if not last_full_reset or last_full_reset.get("event_type", "FULL_RESET") != "FULL_RESET" or last_full_reset.get("execution_stage") in {"announced", "cancelled", "delayed"}:
        return {**empty, "status": "waiting_for_verified_history", "unresolved_reason": "NO_BUSINESS_FULL_ANCHOR"}
    anchor = last_full_reset
    provenance = anchor.get("provenance") if isinstance(anchor.get("provenance"), dict) else {}
    precision = provenance.get("time_precision") or provenance.get("precision") or "unknown"
    declared_form = provenance.get("prediction_form") or provenance.get("time_form")
    legacy_scalar_reference = declared_form is None and anchor.get("occurred_at") is not None and anchor.get("occurred_at_end") is None
    form = declared_form or ("range" if anchor.get("occurred_at_end") and anchor["occurred_at_end"] != anchor.get("occurred_at") else "start_only")
    zone = provenance.get("source_timezone")
    proxy = anchor.get("time_basis") == "post_time_proxy"
    # A legacy value plus a newly declared form does not prove old precision.
    if form == "point" and precision == "unknown" and not proxy:
        form = "start_only"
    try:
        start = _instant(anchor.get("occurred_at"), None) if form != "end_only" else None
        end = _instant(anchor.get("occurred_at_end"), None) if form in {"range", "end_only"} else None
        if form == "range" and (start is None or end is None or start > end):
            raise TargetContractError("ANCHOR_RANGE_UNRESOLVED")
        expression, boundaries = None, None
        if form == "date":
            if not zone or start is None or precision != "day":
                raise TargetContractError("ANCHOR_TIMEZONE_NOT_VERIFIED")
            local_date = start.astimezone(_zone(zone)).date() + timedelta(days=7)
            expression = local_date.isoformat()
            bounds = normalize_prediction_time({"prediction_form": "date", "expression": expression, "source_timezone": zone})
            start = _instant(bounds["predicted_start"], None)
            end = _instant(bounds["predicted_end"], None)
            boundaries = bounds["date_boundaries"]
        else:
            start, end = start + timedelta(days=7) if start else None, end + timedelta(days=7) if end else None
        if start is None and end is None:
            raise TargetContractError("ANCHOR_TIME_MISSING")
        now = datetime.now(UTC) if as_of is None else datetime.fromisoformat(_utc(as_of).replace("Z", "+00:00"))
    except (TargetContractError, ValueError, TypeError):
        return {**empty, "status": "waiting_for_verified_history", "unresolved_reason": "ANCHOR_TIME_UNRESOLVED"}
    # Old scalar values already represented a seven-day reference deadline.
    # Preserve its expiry, not an execution upper bound or point precision.
    upper = start if form == "point" or proxy or legacy_scalar_reference else end if form in {"range", "date", "end_only"} else None
    expired = bool(upper and upper < now)
    return {**empty, "status": "expired" if expired else "baseline", "predicted_start": _utc(start) if start else None,
            "predicted_end": _utc(end) if end else None, "estimated_at": _utc(start) if start else None, "prediction_form": "proxy" if proxy else form,
            "time_form": "proxy" if proxy else form,
            "expression": expression, "date_boundaries": boundaries, "source_timezone": zone, "precision": precision,
            "anchor_event_id": anchor.get("id"), "anchor_time_basis": anchor.get("time_basis"),
            "anchor_time_form": form,
            "anchor_limitation": "POST_TIME_PROXY_NOT_ACTUAL_START" if proxy else "LEGACY_SCALAR_REFERENCE_NOT_ACTUAL_START_BOUND" if legacy_scalar_reference else "LEGACY_ANCHOR_PRECISION_NOT_VERIFIED" if precision == "unknown" else "ANCHOR_UPPER_BOUND_UNKNOWN" if upper is None else None,
            "expiry_basis": "proxy_reference_only" if proxy else "legacy_scalar_reference_only" if legacy_scalar_reference else "closed_upper_bound" if upper else "upper_bound_unknown",
            "basis": "按上次完整重置加 7 天估算；不是官方承诺或模型概率结论。", "unresolved_reason": None}
