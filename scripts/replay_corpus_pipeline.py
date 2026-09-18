from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_settings  # noqa: E402
from app.corpus_standard import (  # noqa: E402
    CORPUS_STANDARD_VERSION,
    import_post_records,
    import_review_cases,
    read_jsonl,
    stable_record_hash,
    write_jsonl,
)
from app.db import Database  # noqa: E402
from app.deepseek import DeepSeekClient  # noqa: E402
from app.intelligence import ANALYSIS_PROMPT_VERSION, JUDGE_PROMPT_VERSION, TRANSLATION_PROMPT_VERSION  # noqa: E402
from app.logging_runtime import RuntimeLog  # noqa: E402
from app.pipeline import IntelligencePipeline  # noqa: E402


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def assert_isolated_path(path: Path) -> None:
    resolved = path.resolve()
    production = (REPOSITORY_ROOT / "runtime" / "data" / "codex-reset-radar-v2.db").resolve()
    review_root = (REPOSITORY_ROOT / "runtime" / "review").resolve()
    if resolved == production or review_root not in resolved.parents:
        raise ValueError(f"replay database must be below {review_root} and must not be the production database")


def result_rows(database: Database, *, run_id: str, frozen_at: str) -> list[dict[str, Any]]:
    with database.connect() as connection:
        posts = connection.execute(
            """SELECT p.*,(SELECT a.analysis_json FROM post_analysis a WHERE a.post_id=p.id
            AND a.analysis_type='post_semantics' ORDER BY a.id DESC LIMIT 1) analysis_json
            FROM tibo_posts p ORDER BY COALESCE(p.posted_at,p.collected_at),p.id"""
        ).fetchall()
        events = connection.execute("SELECT * FROM reset_events ORDER BY occurred_at,id").fetchall()
        candidates = database.list_candidates(10000)
        judgements = connection.execute("SELECT * FROM radar_judgements ORDER BY created_at,id").fetchall()
    results: list[dict[str, Any]] = []
    for row in posts:
        post = dict(row)
        analysis = json.loads(post.pop("analysis_json") or "null")
        status = "PROGRAM_REVIEWED" if analysis is not None else "INSUFFICIENT_INPUT"
        record = {
            "schema_version": CORPUS_STANDARD_VERSION,
            "record_type": "review_result",
            "result_id": f"program:{run_id}:post:{post['tweet_id']}",
            "object_stable_id": f"post:x:{post['tweet_id']}",
            "reviewer_kind": "PRODUCT_PROGRAM",
            "review_status": status,
            "run_id": run_id,
            "as_of": frozen_at,
            "input_content_hash": post.get("text_hash"),
            "program": {
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                "analysis_prompt_version": ANALYSIS_PROMPT_VERSION,
                "translation_prompt_version": TRANSLATION_PROMPT_VERSION,
            },
            "result": {
                "analysis": analysis,
                "translation_zh": post.get("translated_text"),
                "analysis_status": post.get("analysis_status"),
                "translation_status": post.get("translation_status"),
                "processing_error": post.get("processing_error"),
            },
        }
        record["result_hash"] = stable_record_hash(record["result"])
        results.append(record)
    for row in events:
        event = dict(row)
        event["evidence_post_ids"] = json.loads(event.get("evidence_post_ids") or "[]")
        event["provenance"] = json.loads(event.get("provenance") or "{}")
        results.append({
            "schema_version": CORPUS_STANDARD_VERSION,
            "record_type": "review_result",
            "result_id": f"program:{run_id}:event:{event.get('event_key') or event['id']}",
            "object_stable_id": f"program-event:{event.get('event_key') or event['id']}",
            "reviewer_kind": "PRODUCT_PROGRAM",
            "review_status": "PROGRAM_REVIEWED",
            "run_id": run_id,
            "as_of": frozen_at,
            "result": {"event": event},
        })
    for row in judgements:
        judgement = dict(row)
        judgement["evidence_post_ids"] = json.loads(judgement.get("evidence_post_ids") or "[]")
        judgement["special_event_ids"] = json.loads(judgement.get("special_event_ids") or "[]")
        judgement["historical_case_ids"] = json.loads(judgement.get("historical_case_ids") or "[]")
        judgement["raw"] = json.loads(judgement.pop("raw_json") or "{}")
        results.append({
            "schema_version": CORPUS_STANDARD_VERSION,
            "record_type": "review_result",
            "result_id": f"program:{run_id}:judge:{judgement['id']}",
            "object_stable_id": f"judge-window:{judgement['created_at']}",
            "reviewer_kind": "PRODUCT_PROGRAM",
            "review_status": "PROGRAM_REVIEWED",
            "run_id": run_id,
            "as_of": judgement["created_at"],
            "result": {"judgement": judgement},
        })
    for candidate in candidates:
        results.append({
            "schema_version": CORPUS_STANDARD_VERSION, "record_type": "review_result",
            "result_id": f"program:{run_id}:candidate:{candidate['candidate_key']}",
            "object_stable_id": f"program-candidate:{candidate['candidate_key']}",
            "reviewer_kind": "PRODUCT_PROGRAM", "review_status": "PROGRAM_REVIEWED",
            "run_id": run_id, "as_of": frozen_at, "result": {"candidate": candidate},
        })
    return results


async def run(args: argparse.Namespace) -> dict[str, Any]:
    assert_isolated_path(args.database)
    manifest = json.loads((args.package / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != CORPUS_STANDARD_VERSION:
        raise ValueError("package schema version is not supported")
    if args.database.exists() and not args.resume:
        raise FileExistsError(f"refusing to overwrite existing replay database: {args.database}")
    database = Database(args.database)
    database.initialize()
    post_records = list(read_jsonl(args.package / "posts.jsonl"))
    if args.tweet_id:
        selected = set(args.tweet_id)
        post_records = [p for p in post_records if p["tweet_id"] in selected]
        missing = selected - {p["tweet_id"] for p in post_records}
        if missing:
            raise ValueError(f"selected tweets missing from frozen package: {sorted(missing)}")
    if args.post_limit is not None:
        post_records = post_records[: args.post_limit]
    if database.counts()["tibo_posts"] == 0:
        ingest_results = import_post_records(database, post_records)
        imported_cases = 0 if args.no_existing_cases else import_review_cases(
            database,
            read_jsonl(args.package / "review_cases.jsonl"),
            frozen_at=manifest["frozen_at"],
        )
        database.set_state("corpus", {
            "version": manifest["source"].get("corpus_version"),
            "review_package": manifest["package_id"],
            "frozen_at": manifest["frozen_at"],
        })
    else:
        ingest_results = []
        imported_cases = database.corpus_inventory()["cases"]
        with database.connect() as connection:
            existing_posts = connection.execute(
                "SELECT id,tweet_id,text_hash,analysis_status FROM tibo_posts ORDER BY id"
            ).fetchall()
        ingest_results.extend({
            "tweet_id": row["tweet_id"], "post_id": row["id"], "status": "resume",
            "content_hash": row["text_hash"], "queue": row["analysis_status"] != "COMPLETED",
        } for row in existing_posts)

    settings = load_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError("DeepSeek API key is not configured; real product replay cannot run")
    runtime_log = RuntimeLog(args.log_dir, settings.log_retention_days, settings.log_max_bytes)
    client = DeepSeekClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        retries=settings.deepseek_retries,
        runtime_log=runtime_log,
        max_requests=args.max_requests,
    )
    observed_at = utc_now()
    collector_state = {
        "profile_monitor": {"state": "healthy", "last_seen_at": observed_at},
        "replies_monitor": {"state": "healthy", "last_seen_at": observed_at},
    }
    pipeline = IntelligencePipeline(
        database=database,
        client=client,
        runtime_log=runtime_log,
        collector_state=collector_state,
        repository_root=REPOSITORY_ROOT,
        judge_interval_seconds=24 * 60 * 60,
    )
    started_at = utc_now()
    started_monotonic = time.monotonic()
    await pipeline.start()
    queued = pipeline.enqueue_ingest(ingest_results)
    try:
        while database.pending_job_count() > 0:
            if time.monotonic() - started_monotonic > args.max_wait_seconds:
                raise TimeoutError("replay processing exceeded max wait")
            await asyncio.sleep(2)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = database.get_state("judge", {})
            latest = database.latest_judgement()
            if latest and latest["created_at"] >= started_at and state.get("status") == "ready":
                break
            await asyncio.sleep(1)
        else:
            raise TimeoutError("current replay Judge did not finish")
        historical_judgements: list[int] = []
        for as_of in args.judge_window:
            historical_judgements.append(await pipeline.run_judge(as_of=as_of, data_health="HEALTHY"))
    finally:
        await pipeline.stop()
        write_jsonl(args.output, result_rows(database, run_id=args.run_id, frozen_at=manifest["frozen_at"]))

    rows = result_rows(database, run_id=args.run_id, frozen_at=manifest["frozen_at"])
    write_jsonl(args.output, rows)
    with database.connect() as connection:
        job_counts = {row[0]: int(row[1]) for row in connection.execute(
            "SELECT status,COUNT(*) FROM processing_jobs GROUP BY status"
        )}
        post_counts = {row[0]: int(row[1]) for row in connection.execute(
            "SELECT analysis_status,COUNT(*) FROM tibo_posts GROUP BY analysis_status"
        )}
        translation_counts = {row[0]: int(row[1]) for row in connection.execute(
            "SELECT translation_status,COUNT(*) FROM tibo_posts GROUP BY translation_status"
        )}
    return {
        "run_id": args.run_id,
        "started_at": started_at,
        "finished_at": utc_now(),
        "database": str(args.database),
        "log_dir": str(args.log_dir),
        "package_id": manifest["package_id"],
        "posts_in_scope": len(post_records),
        "queued_after_start": queued,
        "existing_cases_loaded": imported_cases,
        "job_counts": job_counts,
        "post_counts": post_counts,
        "translation_counts": translation_counts,
        "historical_judgement_ids": historical_judgements,
        "result_records": len(rows),
        "result_path": str(args.output),
        "notifications_sent": 0,
        "requests_started": client.requests_started,
        "max_requests": args.max_requests,
    }


def parser() -> argparse.ArgumentParser:
    current = argparse.ArgumentParser(description="Replay a standard corpus through the real V2 product pipeline.")
    current.add_argument("--package", type=Path, required=True)
    current.add_argument("--database", type=Path, required=True)
    current.add_argument("--log-dir", type=Path, required=True)
    current.add_argument("--output", type=Path, required=True)
    current.add_argument("--run-id", required=True)
    current.add_argument("--resume", action="store_true")
    current.add_argument("--post-limit", type=int)
    current.add_argument("--tweet-id", action="append", default=[])
    current.add_argument("--no-existing-cases", action="store_true")
    current.add_argument("--max-requests", type=int, default=1000)
    current.add_argument("--max-wait-seconds", type=int, default=21600)
    current.add_argument("--judge-window", action="append", default=[])
    return current


def main() -> int:
    args = parser().parse_args()
    args.package = args.package.resolve()
    args.database = args.database.resolve()
    args.log_dir = args.log_dir.resolve()
    args.output = args.output.resolve()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary = asyncio.run(run(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
