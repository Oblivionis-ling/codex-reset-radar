from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .db import Database


CORPUS_STANDARD_VERSION = "crr-corpus-v1"
REVIEW_STATUSES = {
    "UNREVIEWED",
    "GPT_REVIEWED",
    "PROGRAM_REVIEWED",
    "AGREED",
    "NEEDS_HUMAN_REVIEW",
    "HUMAN_DECIDED",
    "INSUFFICIENT_INPUT",
    "EXCLUDED",
}
SAMPLE_PURPOSES = {"POST_SEMANTICS", "EVENT_RECOGNITION", "JUDGE_WINDOW"}


class CorpusValidationError(ValueError):
    pass


def _json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_record_hash(record: dict[str, Any]) -> str:
    return _sha256_bytes(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    )


def _author_from_url(url: str | None) -> str | None:
    match = re.search(r"(?:x|twitter)\.com/([^/?#]+)/status/", str(url or ""), flags=re.IGNORECASE)
    return match.group(1) if match else None


def _source_evidence(database: Database) -> dict[int, list[dict[str, Any]]]:
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT post_id,source_id,source_record_key,evidence_url,content_kind,text_snapshot,
            posted_at_claim,time_source,time_precision,verification_status,source_claimed_status,
            local_verification_status,completeness_status,is_truncated,has_context,conflict_status,
            author_handle,source_time_raw,source_timezone,time_semantics,parent_tweet_id,upstream_record_key
            FROM post_source_evidence ORDER BY post_id,id"""
        ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row["post_id"] is None:
            continue
        grouped.setdefault(int(row["post_id"]), []).append(dict(row))
    return grouped


def canonical_posts(database: Database) -> list[dict[str, Any]]:
    evidence_by_post = _source_evidence(database)
    with database.connect() as connection:
        rows = connection.execute("SELECT * FROM tibo_posts ORDER BY COALESCE(posted_at,collected_at),id").fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        post = dict(row)
        evidence = evidence_by_post.get(int(post["id"]), [])
        evidence_authors = sorted({str(item["author_handle"]) for item in evidence if item.get("author_handle")})
        author = evidence_authors[0] if len(evidence_authors) == 1 else _author_from_url(post.get("url"))
        parent_ids = sorted(
            {str(item["parent_tweet_id"]) for item in evidence if item.get("parent_tweet_id")}
            | ({str(post["reply_to_tweet_id"])} if post.get("reply_to_tweet_id") else set())
        )
        source_notes = [
            {
                "source_id": item["source_id"],
                "source_record_key": item["source_record_key"],
                "evidence_url": item["evidence_url"],
                "source_claimed_status": item["source_claimed_status"],
                "local_verification_status": item["local_verification_status"],
                "content_kind": item["content_kind"],
                "conflict_status": item["conflict_status"],
            }
            for item in evidence
        ]
        record = {
            "schema_version": CORPUS_STANDARD_VERSION,
            "record_type": "post",
            "stable_id": f"post:x:{post['tweet_id']}",
            "tweet_id": str(post["tweet_id"]),
            "author": {"handle": author, "status": "known" if author else "unknown"},
            "url": post["url"],
            "content": {
                "original_text": post.get("original_text") or post.get("text") or "",
                "original_language": post.get("original_language") or "unknown",
                "translation_zh": post.get("translated_text"),
                "original_text_source": post.get("original_text_source") or "unknown",
                "content_hash": post.get("text_hash"),
                "content_version": f"sha256:{post.get('text_hash')}" if post.get("text_hash") else None,
            },
            "time": {
                "published_at": post.get("posted_at"),
                "range_end": None,
                "precision": post.get("time_precision") or "unknown",
                "basis": post.get("time_source") or "unknown",
            },
            "relationships": {
                "is_reply": bool(post.get("is_reply")),
                "reply_to_tweet_id": post.get("reply_to_tweet_id"),
                "parent_tweet_ids": parent_ids,
            },
            "completeness": {
                "content_status": post.get("content_completeness") or "unknown",
                "context_status": post.get("context_status") or "unknown",
                "conflict_status": post.get("conflict_status") or "none",
            },
            "processing": {
                "ingestion_mode": post.get("ingestion_mode") or "realtime",
                "analysis_status": post.get("analysis_status") or "PENDING",
                "translation_status": post.get("translation_status") or "PENDING",
                "error": post.get("processing_error"),
            },
            "review": {"status": "UNREVIEWED", "review_result_id": None},
            "optional_source_notes": source_notes,
        }
        validate_post_record(record)
        records.append(record)
    return records


def canonical_events(database: Database) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute("SELECT * FROM reset_events ORDER BY occurred_at,id").fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        stable_key = event.get("event_key") or f"legacy-{event['id']}"
        record = {
            "schema_version": CORPUS_STANDARD_VERSION,
            "record_type": "reset_event",
            "stable_id": f"event:{stable_key}",
            "database_id": int(event["id"]),
            "event_type": event["event_type"],
            "special_type": event.get("special_type"),
            "mechanism": event["event_type"],
            "scope": event.get("scope") or "unknown",
            "execution_stage": event.get("execution_stage") or "unknown",
            "time": {
                "start": event.get("occurred_at"),
                "end": event.get("occurred_at_end"),
                "basis": event.get("time_basis") or "unknown",
            },
            "effects": [
                {
                    "event_type": event["event_type"],
                    "special_type": event.get("special_type"),
                    "cycle_start": event["event_type"] == "FULL_RESET",
                }
            ],
            "evidence_tweet_ids": [str(item) for item in _json(event.get("evidence_post_ids"), [])],
            "title": event["title"],
            "summary": event["summary"],
            "provenance": _json(event.get("provenance"), {}),
            "review": {"status": "UNREVIEWED", "gpt_reference": None, "program_result": None, "human_decision": None},
        }
        validate_event_record(record)
        records.append(record)
    return records


def canonical_review_cases(database: Database) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT h.*,p.tweet_id canonical_tweet_id FROM historical_cases h
            LEFT JOIN tibo_posts p ON p.id=h.post_id WHERE h.active=1 ORDER BY h.posted_at,h.case_id"""
        ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        case = dict(row)
        tags = _json(case.get("pattern_tags_json"), [])
        if "advance_hint" in tags:
            purpose = "JUDGE_WINDOW"
        elif any(tag in tags for tag in ("completion_evidence", "dual_effect", "special_event")):
            purpose = "EVENT_RECOGNITION"
        else:
            purpose = "POST_SEMANTICS"
        record = {
            "schema_version": CORPUS_STANDARD_VERSION,
            "record_type": "review_case",
            "sample_id": str(case["case_id"]),
            "sample_purpose": purpose,
            "related_post_stable_ids": [f"post:x:{item}" for item in _json(case.get("related_tweet_ids_json"), [])],
            "input": {
                "post_stable_id": f"post:x:{case['canonical_tweet_id']}" if case.get("canonical_tweet_id") else None,
                "posted_at": case["posted_at"],
                "original_text": case["original_text"],
                "context": case.get("context_text") or "",
            },
            "known_outcome": {
                "type": case["outcome_type"],
                "occurred_at": case.get("outcome_at"),
                "time_precision": case["outcome_time_precision"],
                "coverage_limitations": case.get("coverage_limitations") or "",
            },
            "verification_status": case["verification_status"],
            "pattern_tags": tags,
            "corpus_version": case["corpus_version"],
            "review_status": "UNREVIEWED",
            "reference_exposure": "EXISTING_PRODUCT_CASE",
            "source_mapping": {
                "source_id": case["source_id"],
                "source_record_key": case["source_record_key"],
            },
        }
        validate_review_case_record(record)
        records.append(record)
    return records


def validate_post_record(record: dict[str, Any]) -> None:
    if record.get("schema_version") != CORPUS_STANDARD_VERSION or record.get("record_type") != "post":
        raise CorpusValidationError("invalid post schema identity")
    tweet_id = record.get("tweet_id")
    if not isinstance(tweet_id, str) or not tweet_id:
        raise CorpusValidationError("tweet_id must be a non-empty string")
    content = record.get("content") or {}
    if not isinstance(content.get("original_text"), str):
        raise CorpusValidationError(f"post {tweet_id} original_text must be a string")
    if content.get("translation_zh") is not None and not isinstance(content["translation_zh"], str):
        raise CorpusValidationError(f"post {tweet_id} translation_zh must be a string or null")
    status = (record.get("review") or {}).get("status")
    if status not in REVIEW_STATUSES:
        raise CorpusValidationError(f"post {tweet_id} has invalid review status")


def validate_event_record(record: dict[str, Any]) -> None:
    if record.get("schema_version") != CORPUS_STANDARD_VERSION or record.get("record_type") != "reset_event":
        raise CorpusValidationError("invalid event schema identity")
    if record.get("event_type") not in {"FULL_RESET", "SPECIAL_RESET"}:
        raise CorpusValidationError("invalid event_type")
    if record["event_type"] == "FULL_RESET" and record.get("special_type") is not None:
        raise CorpusValidationError("FULL_RESET cannot carry special_type")
    if record["event_type"] == "SPECIAL_RESET" and not record.get("special_type"):
        raise CorpusValidationError("SPECIAL_RESET requires special_type")
    if not (record.get("time") or {}).get("start"):
        raise CorpusValidationError("event start time is required")


def validate_review_case_record(record: dict[str, Any]) -> None:
    if record.get("schema_version") != CORPUS_STANDARD_VERSION or record.get("record_type") != "review_case":
        raise CorpusValidationError("invalid review case schema identity")
    if record.get("sample_purpose") not in SAMPLE_PURPOSES:
        raise CorpusValidationError("invalid sample purpose")
    if record.get("review_status") not in REVIEW_STATUSES:
        raise CorpusValidationError("invalid review status")


def validate_review_result(record: dict[str, Any]) -> None:
    if record.get("schema_version") != CORPUS_STANDARD_VERSION or record.get("record_type") != "review_result":
        raise CorpusValidationError("invalid review result schema identity")
    if record.get("review_status") not in REVIEW_STATUSES - {"UNREVIEWED"}:
        raise CorpusValidationError("invalid review result status")
    if record.get("reviewer_kind") not in {"GPT_REFERENCE", "PRODUCT_PROGRAM", "HUMAN"}:
        raise CorpusValidationError("invalid reviewer kind")
    if not record.get("object_stable_id"):
        raise CorpusValidationError("review result requires object_stable_id")


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise CorpusValidationError(f"{path.name}:{line_number}: invalid JSON") from error
            if not isinstance(value, dict):
                raise CorpusValidationError(f"{path.name}:{line_number}: expected JSON object")
            yield value


def import_post_records(
    database: Database,
    records: Iterable[dict[str, Any]],
    *,
    ingestion_mode: str = "review_replay",
    preserve_translations: bool = False,
) -> list[dict[str, Any]]:
    """Load standard posts through the product ingest semantics into an isolated database."""
    results: list[dict[str, Any]] = []
    for record in records:
        validate_post_record(record)
        content = record["content"]
        relationships = record["relationships"]
        current = database.upsert_posts_detailed([{
            "tweet_id": record["tweet_id"],
            "text": content["original_text"],
            "posted_at": record["time"].get("published_at"),
            "url": record.get("url"),
            "is_reply": relationships.get("is_reply", False),
            "reply_to_tweet_id": relationships.get("reply_to_tweet_id"),
            "source": "standard_corpus_replay",
        }])[0]
        with database.connect() as connection:
            connection.execute(
                """UPDATE tibo_posts SET ingestion_mode=?,original_language=?,original_text_source=?,
                translated_text=?,translation_status=?,content_completeness=?,context_status=?,
                conflict_status=?,time_source=?,time_precision=?,verification_status=?,analysis_status='PENDING',
                processing_error=NULL WHERE id=?""",
                (
                    ingestion_mode,
                    content.get("original_language") or "unknown",
                    content.get("original_text_source") or "standard_corpus",
                    content.get("translation_zh") if preserve_translations else None,
                    "COMPLETED" if preserve_translations and content.get("translation_zh") else "PENDING",
                    record["completeness"].get("content_status") or "unknown",
                    record["completeness"].get("context_status") or "unknown",
                    record["completeness"].get("conflict_status") or "none",
                    record["time"].get("basis") or "unknown",
                    record["time"].get("precision") or "unknown",
                    "review_snapshot",
                    current["post_id"],
                ),
            )
        current["queue"] = True
        results.append(current)
    return results


def import_review_cases(database: Database, records: Iterable[dict[str, Any]], *, frozen_at: str) -> int:
    source_id = "unified-review-existing-cases"
    database.register_corpus_source({
        "source_id": source_id,
        "name": "Existing reviewed product cases",
        "entry_url": "local://unified-review/existing-cases",
        "accessed_at": frozen_at,
        "access_status": "local_snapshot",
        "acquisition_method": "standard_corpus_package",
        "provides_tweet_ids": True,
        "reuse_status": "local_review_only",
        "content_kind": "existing_product_case",
        "notes": "Pre-existing product cases only; no GPT reference results are loaded.",
    })
    count = 0
    for record in records:
        validate_review_case_record(record)
        primary = (record.get("input") or {}).get("post_stable_id")
        tweet_id = str(primary).removeprefix("post:x:") if primary else None
        related = [str(item).removeprefix("post:x:") for item in record.get("related_post_stable_ids") or []]
        outcome = record["known_outcome"]
        database.upsert_historical_case({
            "case_id": record["sample_id"],
            "tweet_id": tweet_id,
            "source_id": source_id,
            "source_record_key": (record.get("source_mapping") or {}).get("source_record_key") or record["sample_id"],
            "posted_at": record["input"]["posted_at"],
            "original_text": record["input"]["original_text"],
            "context_text": record["input"].get("context") or "",
            "outcome_type": outcome["type"],
            "outcome_at": outcome.get("occurred_at"),
            "outcome_time_precision": outcome.get("time_precision") or "unknown",
            "verification_status": record.get("verification_status") or "unverified",
            "coverage_limitations": outcome.get("coverage_limitations") or "",
            "pattern_tags": record.get("pattern_tags") or [],
            "related_tweet_ids": related,
            "corpus_version": record.get("corpus_version") or "unversioned-existing-case",
        })
        count += 1
    return count


@dataclass(frozen=True)
class PackageMetadata:
    package_id: str
    frozen_at: str
    generated_at: str
    source_database: str
    source_database_sha256: str
    git_head: str
    worktree_fingerprint: str
    app_version: str
    corpus_version: str | None
    model: str | None
    prompt_versions: dict[str, str]
    gpt_runtime: str


def export_package(database: Database, destination: Path, metadata: PackageMetadata) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    payloads = {
        "posts.jsonl": canonical_posts(database),
        "reset_events.jsonl": canonical_events(database),
        "review_cases.jsonl": canonical_review_cases(database),
    }
    counts = {name: write_jsonl(destination / name, records) for name, records in payloads.items()}
    for name in (
        "review_results.jsonl",
        "baseline_program_results.jsonl",
        "comparison.jsonl",
        "human_decisions.jsonl",
        "corrected_program_results.jsonl",
        "unresolved.jsonl",
    ):
        if not (destination / name).exists():
            write_jsonl(destination / name, [])
        counts[name] = sum(1 for _ in read_jsonl(destination / name))
    files = {
        name: {"records": counts[name], "sha256": file_sha256(destination / name)}
        for name in counts
    }
    manifest = {
        "schema_version": CORPUS_STANDARD_VERSION,
        "package_id": metadata.package_id,
        "frozen_at": metadata.frozen_at,
        "generated_at": metadata.generated_at,
        "source": {
            "database": metadata.source_database,
            "database_sha256": metadata.source_database_sha256,
            "git_head": metadata.git_head,
            "worktree_fingerprint": metadata.worktree_fingerprint,
            "app_version": metadata.app_version,
            "corpus_version": metadata.corpus_version,
        },
        "model_baseline": {"deepseek_model": metadata.model, "prompt_versions": metadata.prompt_versions},
        "gpt_reference_runtime": metadata.gpt_runtime,
        "files": files,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
