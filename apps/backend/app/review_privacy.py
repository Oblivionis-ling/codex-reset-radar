from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit

from .notifications.security import redact


REDACTION_VERSION = "crr-review-redaction-v1"
_SECRET_KEY = re.compile(r"(?:secret|token|api[_-]?key|cookie|password|credential|authorization|smtp[_-]?(?:user|pass))", re.I)
_RUNTIME_KEY = re.compile(r"(?:runtime|instance|device|session|account)[_-]?(?:id|key|name)?", re.I)
_PATH_KEY = re.compile(r"(?:^|_)(?:path|file|directory|cwd|workdir)(?:$|_)", re.I)
_FORBIDDEN_KEY = re.compile(
    r"(?:reasoning(?:_content)?|chain[_-]?of[_-]?thought|\bcot\b|raw[_-]?json|"
    r"system[_-]?prompt|request[_-]?(?:body|headers?)|response[_-]?(?:body|headers?)|"
    r"full[_-]?(?:response|config|configuration)|cookie|password|credential|api[_-]?key|token|secret)",
    re.I,
)
_EMAIL = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I)
_MENTION = re.compile(r"(?<![\w/])@[A-Z0-9_][A-Z0-9_.-]{1,30}", re.I)
_LOCAL_PATH = re.compile(
    r"(?:(?<![A-Z0-9+.-])[A-Z]:[\\/]|\\\\|(?<!:)//)[^\s<>\"']+|/(?:Users|home|mnt|private|var|tmp)/[^\s<>\"']+",
    re.I,
)
_PRIVATE_ID = re.compile(
    r"\b(?:session|device|account|profile|tenant)[_-]?(?:id)?\s*[:=]\s*[^\s,;]+", re.I
)
_SECRET_BAIT = re.compile(
    r"\b(?:sk|pk|api[_-]?key|token|secret|session|device)[_=:-][A-Z0-9._~+/-]{6,}", re.I
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_PUBLIC_POST_PATH = re.compile(r"^/(?:[A-Za-z0-9_]{1,30}/status/\d+|i/web/status/\d+)/?$", re.I)
_HASH_VALUE = re.compile(r"^[A-Fa-f0-9]{32,128}$")
_UUID_VALUE = re.compile(r"^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[1-8][A-Fa-f0-9]{3}-[89ABab][A-Fa-f0-9]{3}-[A-Fa-f0-9]{12}$")
_PUBLIC_HANDLE = re.compile(r"^@?[A-Za-z0-9_]{1,30}$")
_PUBLIC_FINGERPRINT_FIELDS = {
    "program_commit", "disk_head", "algorithm_fingerprint", "config_fingerprint",
    "prompt_fingerprint", "runtime_fingerprint",
}
_LOADED_CODE_HASH_FIELDS = {
    "main.create_app",
    "db.Database.judgement_context",
    "db.Database._insert_judgement",
    "pipeline.IntelligencePipeline._run_judge",
    "intelligence.judge",
    "reply_context.ReplyContexts.input",
    "collector_health.collector_health",
    "active_client.complete_json",
}


def _iter_values(value: object):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key), child
            yield from _iter_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_values(child)


def collect_secret_values(values: Iterable[object]) -> set[str]:
    """Collect bait values from secret-named source fields for exact redaction only."""
    found: set[str] = set()
    for source in values:
        for key, value in _iter_values(source):
            if _SECRET_KEY.search(key) and isinstance(value, str) and len(value.strip()) >= 4:
                found.add(value.strip())
    return found


@dataclass
class PrivacyContext:
    secrets: set[str] = field(default_factory=set)
    runtime_aliases: dict[str, str] = field(default_factory=dict)
    path_aliases: dict[str, str] = field(default_factory=dict)
    hash_aliases: dict[str, str] = field(default_factory=dict)
    artifact_aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_sources(cls, values: Iterable[object]) -> "PrivacyContext":
        material = list(values)
        runtime_ids: set[str] = set()
        paths: set[str] = set()
        hashes: set[str] = set()
        artifacts: set[str] = set()
        for source in material:
            for key, value in _iter_values(source):
                if not isinstance(value, str) or not value.strip():
                    continue
                stripped = value.strip()
                if _HASH_VALUE.fullmatch(stripped):
                    hashes.add(stripped)
                if "artifact" in key.lower() and ("id" in key.lower() or "ref" in key.lower()) and _UUID_VALUE.fullmatch(stripped):
                    artifacts.add(stripped)
                if _RUNTIME_KEY.fullmatch(key.replace("_", "").replace("-", "")) or _RUNTIME_KEY.search(key):
                    runtime_ids.add(stripped)
                if _PATH_KEY.search(key) and _looks_like_local_path(value):
                    paths.add(stripped)
                paths.update(_LOCAL_PATH.findall(value))
        return cls(
            secrets=collect_secret_values(material),
            runtime_aliases={value: f"runtime-{index:04d}" for index, value in enumerate(sorted(runtime_ids), 1)},
            path_aliases={value: f"local-path-{index:04d}" for index, value in enumerate(sorted(paths), 1)},
            hash_aliases={value: f"private-hash-{index:04d}" for index, value in enumerate(sorted(hashes), 1)},
            artifact_aliases={value: f"artifact-{index:04d}" for index, value in enumerate(sorted(artifacts), 1)},
        )

    def runtime_alias(self, value: str) -> str:
        return self.runtime_aliases.get(value, "runtime-unknown")

    def path_alias(self, value: str) -> str:
        return self.path_aliases.get(value, "local-path-unknown")

    def hash_alias(self, value: str) -> str:
        return self.hash_aliases.get(value, "private-hash-unknown")

    def artifact_alias(self, value: str) -> str:
        return self.artifact_aliases.get(value, "artifact-unknown")


def _looks_like_local_path(value: str) -> bool:
    return bool(_LOCAL_PATH.search(value)) or bool(re.match(r"^[A-Z]:[\\/]", value, re.I))


def _private_host(host: str) -> bool:
    normalized = host.strip("[]").lower()
    if normalized in {"localhost", "localhost.localdomain"} or normalized.endswith((".local", ".internal", ".lan")):
        return True
    try:
        return ip_address(normalized).is_private or ip_address(normalized).is_loopback or ip_address(normalized).is_link_local
    except ValueError:
        return False


def _safe_url(match: re.Match[str], context: PrivacyContext, categories: set[str]) -> str:
    raw = match.group(0)
    suffix = ""
    while raw and raw[-1] in ".,;:!?)]}":
        suffix = raw[-1] + suffix
        raw = raw[:-1]
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        if not host or parts.username is not None or parts.password is not None or _private_host(host):
            categories.add("private_or_credentialed_url")
            return "[redacted-url]" + suffix
        if host.lower() in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} and _PUBLIC_POST_PATH.fullmatch(parts.path):
            categories.add("url_query_or_fragment_removed") if parts.query or parts.fragment else None
            return f"{parts.scheme.lower()}://{host.lower()}{parts.path}" + suffix
        categories.add("url_path_or_components_removed")
        return f"{parts.scheme.lower()}://{host.lower()}/[redacted]" + suffix
    except ValueError:
        categories.add("invalid_url_removed")
        return "[redacted-url]" + suffix


def clean_text(value: object, context: PrivacyContext, *, limit: int = 2000) -> tuple[str, set[str]]:
    text = str(value or "")
    categories: set[str] = set()

    def replace(pattern: re.Pattern[str], replacement: str, category: str) -> None:
        nonlocal text
        updated = pattern.sub(replacement, text)
        if updated != text:
            categories.add(category)
            text = updated

    before = text
    text = redact(text, context.secrets)
    if text != before:
        categories.add("known_secret_redacted")
    text = _URL.sub(lambda match: _safe_url(match, context, categories), text)
    replace(_EMAIL, "[redacted-email]", "email_redacted")

    def local_path(match: re.Match[str]) -> str:
        categories.add("local_path_aliased")
        return f"[{context.path_alias(match.group(0))}]"

    text = _LOCAL_PATH.sub(local_path, text)
    replace(_PRIVATE_ID, "[redacted-private-id]", "private_identifier_redacted")
    # Avoid naming the category like a secret assignment, which the final
    # defense-in-depth scanner correctly rejects as secret-shaped text.
    replace(_SECRET_BAIT, "[redacted-secret]", "secretlike_pattern_redacted")
    replace(_MENTION, "[redacted-account]", "account_mention_redacted")
    if len(text) > limit:
        text = text[:limit]
        categories.add("text_length_limited")
    text = " ".join(text.split())
    return text, categories


_SAFE_MAP_KEYS = {
    "input_versions",
    "input_post_ids",
    "post_analysis_versions",
    "reset_event_versions",
    "historical_case_versions",
    "evidence_versions",
    "public_evidence_versions",
}
_SAFE_SNAPSHOT_KEYS = _SAFE_MAP_KEYS | {"current_cycle_version", "corpus_version", "policy_versions"}


def _safe_policy_versions(value: object, context: PrivacyContext, categories: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    allowed = {
        "post_id", "content_hash", "policy_version", "policy_status", "judge_evidence_allowed",
        "analysis_allowed", "event_promotion_allowed", "historical_case_allowed", "decision_ids",
    }
    for raw_id, raw_policy in value.items():
        if not re.fullmatch(r"\d{1,25}", str(raw_id)) or not isinstance(raw_policy, Mapping):
            categories.add("invalid_policy_version_omitted")
            continue
        policy: dict[str, object] = {}
        for key in sorted(allowed.intersection(str(item) for item in raw_policy)):
            child = raw_policy[key]
            if key.endswith("_allowed"):
                if isinstance(child, bool):
                    policy[key] = child
                else:
                    categories.add("invalid_policy_flag_omitted")
            elif key == "decision_ids":
                if isinstance(child, (list, tuple)):
                    policy[key] = [sanitize_value("decision_id", item, context, categories)
                                   for item in child[:40] if isinstance(item, (str, int))]
                else:
                    categories.add("invalid_policy_decision_ids_omitted")
            elif child is None or isinstance(child, (str, int, float)):
                policy[key] = sanitize_value(key, child, context, categories)
        if set(map(str, raw_policy)) - set(policy):
            categories.add("policy_fields_omitted")
        result[str(raw_id)] = policy
    return dict(sorted(result.items()))


def _safe_input_frame(value: object, context: PrivacyContext, categories: set[str]) -> object:
    if not isinstance(value, Mapping):
        categories.add("invalid_input_frame_omitted")
        return None

    def simple_map(source: object, allowed: set[str]) -> dict[str, object]:
        if not isinstance(source, Mapping):
            return {}
        result: dict[str, object] = {}
        for key in sorted(allowed.intersection(str(item) for item in source)):
            child = source[key]
            if child is None or isinstance(child, (str, int, float, bool, list, tuple, Mapping)):
                result[key] = sanitize_value(key, child, context, categories)
        if set(map(str, source)) - set(result):
            categories.add("input_frame_fields_omitted")
        return result

    forecast_fields = {
        "target", "scope", "question", "method", "basis", "cycle_id", "event_id", "candidate_id",
        "origin_judgement_id", "predicted_start", "predicted_end", "prediction_form", "precision",
        "source_timezone", "time_basis",
    }
    context_fields = {
        "judged_at", "data_health", "default_reference_last_full_plus_7d", "corpus_version",
    }
    event_fields = {
        "id", "event_type", "special_type", "occurred_at", "occurred_at_end", "time_basis", "scope",
        "execution_stage", "evidence_post_ids", "title", "summary", "created_at", "updated_at",
    }
    post_fields = {"tweet_id", "posted_at", "is_reply", "author"}
    case_fields = {
        "case_id", "posted_at", "outcome_type", "outcome_at", "outcome_time_precision",
        "verification_status", "coverage_limitations", "pattern_tags", "related_tweet_ids",
    }
    previous_fields = {
        "created_at", "action_level", "horizon_24h", "horizon_48h", "horizon_72h", "estimated_start",
        "estimated_end", "estimate_basis", "data_health", "reason_summary", "evidence_post_ids",
    }
    result: dict[str, object] = {}
    raw_forecast = value.get("forecast")
    if isinstance(raw_forecast, Mapping):
        result["forecast"] = simple_map(raw_forecast, forecast_fields)
    raw_snapshot = value.get("input_snapshot")
    if isinstance(raw_snapshot, Mapping):
        result["input_snapshot"] = sanitize_value("input_snapshot", raw_snapshot, context, categories)
    raw_context = value.get("context")
    if isinstance(raw_context, Mapping):
        safe_context = simple_map(raw_context, context_fields)
        for source_key, target_key, allowed in (
            ("reset_events", "reset_events", event_fields),
            ("posts", "posts", post_fields),
            ("historical_cases", "historical_cases", case_fields),
        ):
            raw_rows = raw_context.get(source_key)
            if isinstance(raw_rows, (list, tuple)):
                safe_context[target_key] = [simple_map(item, allowed) for item in raw_rows[:500] if isinstance(item, Mapping)]
                if len(raw_rows) > 500:
                    categories.add("input_frame_list_limit_applied")
        previous = raw_context.get("previous_judgement")
        if isinstance(previous, Mapping):
            safe_context["previous_judgement"] = simple_map(previous, previous_fields)
        pending = raw_context.get("pending_inputs")
        if isinstance(pending, (list, tuple)):
            pending_fields = {"tweet_id", "status", "stage", "reason_code", "updated_at"}
            safe_context["pending_inputs"] = [simple_map(item, pending_fields) for item in pending[:500] if isinstance(item, Mapping)]
            if len(pending) > 500:
                categories.add("input_frame_list_limit_applied")
        result["context"] = safe_context
    policies = value.get("policy_versions")
    if isinstance(policies, Mapping):
        result["policy_versions"] = _safe_policy_versions(policies, context, categories)
    sources = value.get("evidence_sources")
    if isinstance(sources, (list, tuple)):
        source_fields = {
            "post_id", "tweet_id", "author", "role", "relation_to_target", "parent_tweet_id",
            "relation_source", "source_version", "policy_version", "snapshot_status",
        }
        result["evidence_sources"] = [simple_map(item, source_fields) for item in sources[:1000] if isinstance(item, Mapping)]
        if len(sources) > 1000:
            categories.add("input_frame_list_limit_applied")
    if value.get("public_prompt_artifact_ref") is not None or value.get("judge_schema_artifact_ref") is not None:
        categories.add("prompt_and_schema_content_omitted")
    # Do not expose frame strings, raw request context or model prompt material.
    omitted = set(map(str, value)) - {
        "forecast", "input_snapshot", "context", "policy_versions", "evidence_sources",
        "public_prompt_artifact_ref", "judge_schema_artifact_ref",
    }
    if omitted:
        categories.add("input_frame_private_fields_omitted")
    return result


def _safe_request_descriptor(value: object, context: PrivacyContext, categories: set[str]) -> object:
    if not isinstance(value, Mapping):
        categories.add("invalid_request_descriptor_omitted")
        return None
    allowed = {
        "stage", "judgement_as_of", "input_cutoff_at", "model", "temperature", "top_p",
        "frequency_penalty", "presence_penalty", "max_tokens", "message_count", "response_format",
        "request_hash", "input_snapshot_hash", "forecast_semantic_hash",
    }
    result: dict[str, object] = {}
    for key in sorted(allowed.intersection(str(item) for item in value)):
        child = value[key]
        if key == "response_format":
            if isinstance(child, Mapping) and isinstance(child.get("type"), str):
                result[key] = {"type": clean_text(child["type"], context, limit=80)[0]}
            else:
                categories.add("unsafe_response_format_omitted")
        elif child is None or isinstance(child, (str, int, float, bool)):
            result[key] = sanitize_value(key, child, context, categories)
    if set(map(str, value)) - allowed:
        categories.add("request_descriptor_fields_omitted")
    return result


def _safe_version_map(value: object, context: PrivacyContext, categories: set[str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, version in value.items():
        key_text, version_text = str(key), str(version)
        if not re.fullmatch(r"[A-Za-z0-9:_-]{1,100}", key_text):
            categories.add("invalid_version_key_omitted")
            continue
        if _HASH_VALUE.fullmatch(version_text):
            result[key_text] = context.hash_alias(version_text)
            categories.add("private_hash_aliased")
        else:
            cleaned, found = clean_text(version_text, context, limit=200)
            result[key_text] = cleaned
            categories.update(found)
            categories.add("nonhash_version_value_sanitized")
    return dict(sorted(result.items()))


_SAFE_REFERENCE_FIELDS = {
    "target", "id", "status", "reason", "placeholder", "omission_reason", "role", "relation",
    "relation_source", "relation_to_target", "tweet_id", "author", "author_role", "parent_tweet_id",
    "parent_author", "parent_author_role", "depth", "source_version", "policy_version", "redacted",
    "redaction_categories", "record_id", "observed_at", "source", "clock_anomaly", "time_limitation",
}

_INPUT_VERSION_DELTA_CLASSES = {
    "input_version", "post_analysis_version", "reset_event_version", "historical_case_version",
    "content_policy_version", "current_cycle", "corpus", "pending_input",
}


def _safe_input_version_delta(value: object, context: PrivacyContext, categories: set[str]) -> object:
    if not isinstance(value, (list, tuple)):
        categories.add("invalid_input_version_delta_omitted")
        return None
    projected: list[dict[str, object]] = []
    for entry in value[:1000]:
        if not isinstance(entry, Mapping):
            continue
        delta_class = entry.get("class")
        entity = entry.get("entity")
        if not isinstance(delta_class, str) or delta_class not in _INPUT_VERSION_DELTA_CLASSES:
            categories.add("unapproved_input_version_delta_class_omitted")
            continue
        if not isinstance(entity, str) or not entity.strip() or len(entity) > 300:
            categories.add("invalid_input_version_delta_entity_omitted")
            continue
        item: dict[str, object] = {
            "class": delta_class,
            "entity": sanitize_value("entity", entity, context, categories),
        }
        for key in ("old_hash", "new_hash"):
            digest = entry.get(key)
            if digest is None:
                item[key] = None
            elif isinstance(digest, str) and _HASH_VALUE.fullmatch(digest):
                item[key] = context.hash_alias(digest)
                categories.add("private_hash_aliased")
            else:
                categories.add("invalid_input_version_hash_omitted")
        if set(map(str, entry)) - {"class", "entity", "old_hash", "new_hash"}:
            categories.add("input_version_delta_fields_omitted")
        projected.append(item)
    if len(value) > 1000:
        categories.add("input_version_delta_list_limit_applied")
    return projected


def _safe_reference_tree(value: object, context: PrivacyContext, categories: set[str]) -> object:
    if isinstance(value, (list, tuple)):
        return [_safe_reference_tree(item, context, categories) for item in value]
    if not isinstance(value, Mapping):
        categories.add("invalid_reference_omitted")
        return None
    result: dict[str, object] = {}
    for key in sorted(_SAFE_REFERENCE_FIELDS.intersection(str(item) for item in value)):
        child = value[key]
        if key in {"redacted", "placeholder"} and isinstance(child, bool):
            result[key] = child
        elif key == "depth" and isinstance(child, int):
            result[key] = child
        elif key == "redaction_categories" and isinstance(child, (list, tuple)):
            result[key] = [str(item)[:80] for item in child[:40] if isinstance(item, str)]
        elif isinstance(child, (Mapping, list, tuple)):
            result[key] = _safe_reference_tree(child, context, categories)
        elif child is None or isinstance(child, (str, int, float)):
            result[key] = sanitize_value(key, child, context, categories)
    if set(map(str, value)) - set(result):
        categories.add("reference_fields_omitted")
    return result


def _safe_source_snapshot(value: object, context: PrivacyContext, categories: set[str]) -> object:
    if not isinstance(value, Mapping):
        categories.add("invalid_source_snapshot_omitted")
        return None
    allowed = {
        "event_id", "event_type", "special_type", "occurred_at", "occurred_at_end", "time_basis",
        "scope", "execution_stage", "source_post_id", "title", "summary", "evidence_post_ids",
        "created_at", "updated_at",
    }
    result: dict[str, object] = {}
    for key in sorted(allowed.intersection(str(item) for item in value)):
        child = value[key]
        if key == "evidence_post_ids" and isinstance(child, (list, tuple)):
            result[key] = [str(item)[:100] for item in child[:500] if isinstance(item, (str, int))]
        elif child is None or isinstance(child, (str, int, float, bool)):
            if key in {"title", "summary"} and isinstance(child, str):
                cleaned, found = clean_text(child, context)
                result[key] = cleaned
                categories.update(found)
            else:
                result[key] = sanitize_value(key, child, context, categories)
    if set(map(str, value)) - set(result):
        categories.add("source_snapshot_fields_omitted")
    return result


def _safe_usage(value: object, categories: set[str]) -> object:
    if not isinstance(value, Mapping):
        categories.add("invalid_usage_omitted")
        return None
    token_keys = {
        "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "reasoning_tokens",
        "prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "prompt_tokens_details",
        "completion_tokens_details",
    }

    def project(node: Mapping[str, object], depth: int) -> dict[str, object]:
        safe: dict[str, object] = {}
        for key in sorted(token_keys.intersection(str(item) for item in node)):
            child = node[key]
            if isinstance(child, Mapping) and depth < 2:
                nested = project(child, depth + 1)
                if nested:
                    safe[key] = nested
            elif isinstance(child, (int, float)) and not isinstance(child, bool):
                safe[key] = child
        return safe

    result = project(value, 0)
    if set(map(str, value)) - set(result):
        categories.add("usage_fields_omitted")
    return result


def _safe_processing_output(value: object, context: PrivacyContext, categories: set[str]) -> object:
    """Project only validated upstream processing DTO fields, never provider envelopes."""
    if not isinstance(value, Mapping):
        categories.add("invalid_processing_output_omitted")
        return None
    operation = value.get("operation")
    output = value.get("output")
    if operation == "post_translation":
        if not isinstance(output, Mapping):
            categories.add("invalid_processing_output_omitted")
            return None
        result: dict[str, object] = {"operation": operation}
        text = output.get("translation_zh")
        if isinstance(text, str):
            cleaned, found = clean_text(text, context, limit=12000)
            result["translation_zh"] = cleaned
            categories.update(found)
        if set(map(str, output)) - {"translation_zh"}:
            categories.add("processing_output_fields_omitted")
        if set(map(str, value)) - {"operation", "output"}:
            categories.add("processing_output_envelope_fields_omitted")
        return result
    if operation != "post_analysis" or not isinstance(output, Mapping):
        categories.add("unsupported_processing_output_omitted")
        return None

    scalar_fields = {
        "tweet_id", "category", "codex_relevant", "temporal_mode", "explicit_announcement",
        "event_status", "event_type", "special_type", "canonical_eligible", "scope",
        "execution_stage", "event_time_start", "event_time_end", "time_basis",
        "context_sufficient", "model_category",
    }
    text_fields = {"evidence_quote", "summary", "event_title", "normalization_notes"}
    effect_fields = {
        "temporal_mode", "explicit_announcement", "event_status", "event_type", "special_type",
        "canonical_eligible", "scope", "execution_stage", "event_time_start", "event_time_end",
        "time_basis", "evidence_quote", "summary", "event_title", "claim_kind",
    }

    def safe_fact(key: str, child: object) -> object:
        if key == "scope" and isinstance(child, Mapping):
            return sanitize_value("scope", child, context, categories)
        if key in text_fields and isinstance(child, str):
            cleaned, found = clean_text(child, context, limit=1000)
            categories.update(found)
            return cleaned
        if child is None or isinstance(child, (bool, int, float)):
            return child
        if isinstance(child, str):
            cleaned, found = clean_text(child, context, limit=300)
            categories.update(found)
            return cleaned
        return None

    projected: dict[str, object] = {}
    for key in sorted((scalar_fields | text_fields).intersection(str(item) for item in output)):
        child = safe_fact(key, output[key])
        if child is not None or output[key] is None:
            projected[key] = child
    effects = output.get("effects")
    if isinstance(effects, (list, tuple)):
        safe_effects = []
        for effect in effects[:500]:
            if not isinstance(effect, Mapping):
                continue
            safe_effect: dict[str, object] = {}
            for key in sorted(effect_fields.intersection(str(item) for item in effect)):
                child = safe_fact(key, effect[key])
                if child is not None or effect[key] is None:
                    safe_effect[key] = child
            safe_effects.append(safe_effect)
        projected["effects"] = safe_effects
        if len(effects) > 500:
            categories.add("processing_output_list_limit_applied")
    if set(map(str, output)) - (scalar_fields | text_fields | {"effects"}):
        categories.add("processing_output_fields_omitted")
    if set(map(str, value)) - {"operation", "output"}:
        categories.add("processing_output_envelope_fields_omitted")
    return {"operation": operation, "output": projected}


def sanitize_value(field_name: str, value: object, context: PrivacyContext, categories: set[str]) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if field_name == "input_frame":
        return _safe_input_frame(value, context, categories)
    if field_name == "request_descriptor":
        return _safe_request_descriptor(value, context, categories)
    if field_name == "source_snapshot":
        return _safe_source_snapshot(value, context, categories)
    if field_name == "usage":
        return _safe_usage(value, categories)
    if field_name == "processing_output":
        return _safe_processing_output(value, context, categories)
    if field_name == "input_version_delta":
        return _safe_input_version_delta(value, context, categories)
    if field_name in {"estimated_start_time_metadata", "estimated_end_time_metadata"}:
        if not isinstance(value, Mapping):
            categories.add("invalid_time_metadata_omitted")
            return None
        allowed = {"precision", "source_timezone", "timezone_status"}
        safe_metadata: dict[str, object] = {}
        for key in sorted(allowed.intersection(str(item) for item in value)):
            child = value[key]
            if child is None or isinstance(child, str):
                safe_metadata[key] = sanitize_value(key, child, context, categories)
        if set(map(str, value)) - set(safe_metadata):
            categories.add("time_metadata_fields_omitted")
        return safe_metadata
    if field_name == "policy_versions":
        return _safe_policy_versions(value, context, categories)
    if field_name in _PUBLIC_FINGERPRINT_FIELDS:
        if isinstance(value, str) and _HASH_VALUE.fullmatch(value):
            return value.lower()
        if isinstance(value, str) and field_name == "program_commit" and re.fullmatch(r"[A-Fa-f0-9]{7,40}", value):
            return value.lower()
        categories.add("invalid_public_fingerprint_omitted")
        return None
    if field_name == "loaded_code_fingerprints":
        if not isinstance(value, Mapping):
            categories.add("invalid_loaded_code_fingerprints_omitted")
            return {}
        result: dict[str, str] = {}
        for name in sorted(_LOADED_CODE_HASH_FIELDS.intersection(str(key) for key in value)):
            digest = value[name]
            if isinstance(digest, str) and _HASH_VALUE.fullmatch(digest):
                result[name] = digest.lower()
            elif digest is not None:
                categories.add("invalid_loaded_code_fingerprint_omitted")
        if set(map(str, value)) - set(result):
            categories.add("unapproved_loaded_code_fingerprint_omitted")
        return result
    if field_name in _SAFE_MAP_KEYS:
        return _safe_version_map(value, context, categories)
    if field_name in {"evidence_refs", "source_refs", "forecast_ref", "attempt_ref", "source_attempt_ref", "body_ref", "artifact_refs", "references", "availability_observations"}:
        if field_name == "references" and isinstance(value, Mapping):
            allowed = {"forecast", "attempt", "truth", "artifacts"}
            if set(map(str, value)) - allowed:
                categories.add("reference_fields_omitted")
            return {
                str(key): _safe_reference_tree(child, context, categories)
                for key, child in value.items() if str(key) in allowed
            }
        return _safe_reference_tree(value, context, categories)
    if field_name == "scope" and isinstance(value, Mapping):
        safe_scope: dict[str, object] = {}
        for key in ("value", "certainty"):
            child = value.get(key)
            if child is None or isinstance(child, (str, int, float, bool)):
                safe_scope[key] = sanitize_value(key, child, context, categories)
        if set(map(str, value)) - set(safe_scope):
            categories.add("scope_fields_omitted")
        return safe_scope
    if field_name in {"input_snapshot", "snapshot"}:
        if not isinstance(value, Mapping):
            categories.add("invalid_snapshot_omitted")
            return None
        safe: dict[str, object] = {}
        for key in sorted(_SAFE_SNAPSHOT_KEYS.intersection(str(item) for item in value)):
            child = value[key]
            if key in _SAFE_MAP_KEYS:
                safe[key] = _safe_version_map(child, context, categories)
            elif key == "policy_versions":
                safe[key] = _safe_policy_versions(child, context, categories)
            elif child is None or isinstance(child, (str, int, float, bool)):
                safe[key] = sanitize_value(key, child, context, categories)
        excluded = set(map(str, value)) - set(safe)
        if excluded:
            categories.add("snapshot_fields_omitted")
        return safe
    if field_name == "structured_output":
        if not isinstance(value, Mapping):
            categories.add("invalid_structured_output_omitted")
            return None
        allowed = {
            "action_level", "horizon_24h", "horizon_48h", "horizon_72h", "estimated_start", "estimated_end",
            "estimate_basis", "data_health", "judgement_as_of", "status", "evidence_post_ids",
            "estimated_start_expression", "estimated_end_expression",
            "estimated_start_time_metadata", "estimated_end_time_metadata", "reason_summary", "model",
            "prompt_version", "created_at",
        }
        safe_output: dict[str, object] = {}
        for key in sorted(allowed.intersection(str(item) for item in value)):
            child = value[key]
            if child is None or isinstance(child, (bool, int, float)):
                safe_output[key] = child
            elif key == "evidence_post_ids" and isinstance(child, (list, tuple)):
                safe_output[key] = [str(item)[:100] for item in child if isinstance(item, (str, int))]
            elif key in {"estimated_start_time_metadata", "estimated_end_time_metadata"}:
                safe_output[key] = sanitize_value(key, child, context, categories)
            elif isinstance(child, str):
                cleaned, found = clean_text(child, context, limit=1000 if key == "reason_summary" else 300)
                categories.update(found)
                safe_output[key] = cleaned
        if set(map(str, value)) - set(safe_output):
            categories.add("unapproved_output_fields_omitted")
        return safe_output
    if isinstance(value, (list, tuple)):
        if field_name == "runtime_scope":
            return [clean_text(item, context)[0] for item in value if isinstance(item, str)]
        if field_name in {"evidence_post_ids", "special_event_ids", "historical_case_ids", "candidate_ids", "tweet_ids"}:
            return [str(item)[:100] for item in value if isinstance(item, (str, int))]
        if field_name == "redaction_categories":
            return [str(item)[:80] for item in value if isinstance(item, str)]
        return []
    if isinstance(value, Mapping):
        categories.add("nested_payload_omitted")
        return None
    if isinstance(value, str):
        if _HASH_VALUE.fullmatch(value):
            categories.add("private_hash_aliased")
            return context.hash_alias(value)
        if field_name == "artifact_id" and _UUID_VALUE.fullmatch(value):
            categories.add("artifact_identifier_aliased")
            return context.artifact_alias(value)
        if field_name in {"author", "parent_author", "author_handle"} and _PUBLIC_HANDLE.fullmatch(value):
            return value
        if _RUNTIME_KEY.search(field_name) and field_name.lower() not in {"runtime_alias", "runtime_scope", "runtime_identity_status"}:
            categories.add("runtime_identifier_aliased")
            return context.runtime_alias(value)
        if _PATH_KEY.search(field_name):
            categories.add("local_path_aliased")
            return context.path_alias(value)
        cleaned, found = clean_text(value, context)
        categories.update(found)
        return cleaned
    categories.add("unsupported_value_omitted")
    return None


def sanitize_dto(source: Mapping[str, object], allowed_fields: Iterable[str], context: PrivacyContext) -> dict[str, object]:
    allowed = set(allowed_fields)
    categories: set[str] = set()
    result: dict[str, object] = {}
    for field_name in sorted(allowed.intersection(source)):
        value = source[field_name]
        sanitized = sanitize_value(field_name, value, context, categories)
        if sanitized is not None or value is None:
            result[field_name] = sanitized
    for key in source:
        if key not in allowed and _FORBIDDEN_KEY.search(str(key)):
            categories.add("private_or_unapproved_field_omitted")
    declared_categories = source.get("redaction_categories")
    if isinstance(declared_categories, (list, tuple)):
        categories.update(str(item)[:80] for item in declared_categories[:40] if isinstance(item, str))
    if source.get("redacted") is True and not categories:
        categories.add("source_content_redacted")
    result["redacted"] = bool(categories)
    result["redaction_categories"] = sorted(categories)
    return result


def allowed_text_fields(source: Mapping[str, object], fields: Iterable[str], context: PrivacyContext) -> dict[str, object]:
    """Return just named text fields and a shared redaction annotation."""
    return sanitize_dto(source, fields, context)

