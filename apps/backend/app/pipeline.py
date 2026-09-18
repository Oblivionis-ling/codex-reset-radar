from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .db import Database, utc_now
from .deepseek import DeepSeekError
from .intelligence import (
    ANALYSIS_PROMPT_VERSION,
    JUDGE_PROMPT_VERSION,
    TRANSLATION_PROMPT_VERSION,
    JsonModel,
    analyse_post,
    candidate_record,
    event_records,
    judge,
    translate_post,
)
from .logging_runtime import RuntimeLog


class TranslationStageError(RuntimeError):
    pass


# Profile/Replies heartbeats are emitted every 60 seconds. Keep serving the
# previous judgement while startup waits for one complete collector cycle.
STARTUP_JUDGE_GRACE_SECONDS = 70


class IntelligencePipeline:
    def __init__(
        self,
        *,
        database: Database,
        client: JsonModel,
        runtime_log: RuntimeLog,
        collector_state: dict[str, dict[str, Any]],
        repository_root: Path,
        judge_interval_seconds: int = 3600,
    ) -> None:
        self.database = database
        self.client = client
        self.runtime_log = runtime_log
        self.collector_state = collector_state
        self.repository_root = repository_root
        self.judge_interval_seconds = judge_interval_seconds
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopping = False
        self._judge_dirty = False
        self._judge_requested_at = 0.0
        self._last_hourly_request = time.monotonic()
        self._judge_failures = 0
        self._startup_judge_deadline: float | None = None

    @property
    def model(self) -> str:
        return self.client.model

    def identity(self, post: dict[str, Any]) -> str:
        return f"{post['id']}:{post['text_hash']}:{ANALYSIS_PROMPT_VERSION}:{TRANSLATION_PROMPT_VERSION}:{self.model}"

    async def start(self) -> None:
        recovered = self.database.recover_jobs()
        candidates_path = self.repository_root / "data" / "analysis" / "v1-reset-migration-candidates.json"
        candidate_ids: list[str] = []
        try:
            payload = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidate_ids = [str(item["tweet_id"]) for item in payload.get("candidates", [])]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            candidate_ids = []
        queued = 0
        for post in self.database.bootstrap_posts(candidate_ids):
            queued += int(self.database.enqueue_post(post["id"], self.identity(post)))
        self.database.set_state("pipeline", {
            "status": "processing" if queued or recovered else "ready", "enabled": True,
            "model": self.model, "queued_at_start": queued, "recovered_jobs": recovered,
            "last_error": None, "started_at": utc_now(),
        })
        self.runtime_log.write("app", "INTELLIGENCE_PIPELINE_STARTED", metadata={
            "model": self.model, "queued": queued, "recovered": recovered,
            "analysis_prompt_version": ANALYSIS_PROMPT_VERSION, "judge_prompt_version": JUDGE_PROMPT_VERSION,
        })
        self._startup_judge_deadline = time.monotonic() + STARTUP_JUDGE_GRACE_SECONDS
        self.request_judge("startup")
        self._tasks = [
            asyncio.create_task(self._worker(1), name="intelligence-worker-1"),
            asyncio.create_task(self._worker(2), name="intelligence-worker-2"),
            asyncio.create_task(self._judge_loop(), name="radar-judge-loop"),
        ]

    async def stop(self) -> None:
        self._stopping = True
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        close = getattr(self.client, "close", None)
        if close:
            await close()

    def enqueue_ingest(self, results: list[dict[str, Any]]) -> int:
        queued = 0
        for item in results:
            if not item.get("queue"):
                continue
            post = self.database.get_post(int(item["post_id"]))
            if post and self.database.enqueue_post(post["id"], self.identity(post)):
                queued += 1
        if queued:
            self.database.set_state("pipeline", {"status": "processing", "enabled": True, "model": self.model, "last_error": None, "updated_at": utc_now()})
        return queued

    def request_judge(self, trigger: str) -> None:
        self._judge_dirty = True
        self._judge_requested_at = time.monotonic()
        self.runtime_log.write("llm", "RADAR_JUDGE_REQUESTED", metadata={"trigger": trigger})

    async def _worker(self, worker_number: int) -> None:
        while not self._stopping:
            job = self.database.claim_post_job()
            if not job:
                await asyncio.sleep(1)
                continue
            post_id = int(job["payload"]["post_id"])
            try:
                await self._process_post(post_id)
                self.database.finish_job(int(job["id"]))
                self.request_judge("post_processed")
                self.runtime_log.write("llm", "POST_PROCESSING_COMPLETED", metadata={"post_id": post_id, "job_id": job["id"], "worker": worker_number})
            except asyncio.CancelledError:
                raise
            except Exception as error:
                retry_at = None
                if int(job["attempts"]) < 3:
                    retry_at = (datetime.now(UTC) + timedelta(seconds=30 * int(job["attempts"]))).isoformat().replace("+00:00", "Z")
                safe_error = f"{type(error).__name__}: {error}"[:1000]
                if not isinstance(error, TranslationStageError):
                    self.database.mark_post_failure(post_id, safe_error)
                self.database.fail_job(int(job["id"]), safe_error, retry_at)
                self.database.set_state("pipeline", {"status": "degraded", "enabled": True, "model": self.model, "last_error": safe_error, "updated_at": utc_now()})
                self.runtime_log.write("llm", "POST_PROCESSING_FAILED", result="failure", metadata={
                    "post_id": post_id, "job_id": job["id"], "attempt": job["attempts"],
                    "retry_at": retry_at, "error_type": type(error).__name__,
                })

    async def _process_post(self, post_id: int) -> None:
        post = self.database.get_post(post_id)
        if not post:
            raise ValueError(f"post {post_id} no longer exists")
        policy = self.database.content_policy(post_id)
        if policy is not None and not policy["analysis_allowed"]:
            self.database.mark_post_input_restricted(post_id, str(policy["reason"]))
            self.runtime_log.write("app", "POST_INPUT_RESTRICTED", metadata={
                "post_id": post_id,
                "tweet_id": post["tweet_id"],
                "policy_status": policy["policy_status"],
                "policy_version": policy["policy_version"],
            })
            return
        post_hash = str(post["text_hash"])
        analysis = self.database.latest_analysis(post_id, post_hash, ANALYSIS_PROMPT_VERSION, self.model)
        if analysis is None:
            analysis = await analyse_post(self.client, post)
            analysis_id = self.database.save_analysis(post_id, post_hash, self.model, ANALYSIS_PROMPT_VERSION, analysis)
            self.runtime_log.write("llm", "POST_ANALYSIS_SAVED", metadata={"post_id": post_id, "tweet_id": post["tweet_id"], "analysis_id": analysis_id, "category": analysis["category"]})

        if self.database.content_use_allowed(post, "event_promotion"):
            for disposition, record in event_records(post, analysis):
                if disposition == "confirmed":
                    saved = self.database.upsert_reset_event(record)
                    self.runtime_log.write("app", "RESET_EVENT_UPSERTED", metadata={"event_id": saved["id"], "event_type": saved["event_type"], "tweet_id": post["tweet_id"]})
                else:
                    candidate_id = self.database.upsert_candidate(record if disposition == "ambiguous" else candidate_record(post, analysis, record))
                    self.runtime_log.write("app", "RESET_CANDIDATE_UPSERTED", metadata={"candidate_id": candidate_id, "tweet_id": post["tweet_id"]})
        else:
            self.runtime_log.write("app", "POST_EVENT_PROMOTION_RESTRICTED", metadata={
                "post_id": post_id,
                "tweet_id": post["tweet_id"],
                "policy_status": policy["policy_status"] if policy else "restricted",
            })

        if post.get("translation_status") != "COMPLETED" or not post.get("translated_text"):
            try:
                translated = await translate_post(self.client, post)
                self.database.save_translation(post_id, post_hash, translated)
                self.runtime_log.write("llm", "POST_TRANSLATION_SAVED", metadata={"post_id": post_id, "tweet_id": post["tweet_id"]})
            except Exception as error:
                self.database.save_translation(post_id, post_hash, None, f"{type(error).__name__}: {error}")
                raise TranslationStageError(f"{type(error).__name__}: {error}") from error

    def _data_health(self) -> str:
        if not self.collector_state:
            return "STALE"
        now = datetime.now(UTC)
        required = ("profile_monitor", "replies_monitor")
        for name in required:
            state = self.collector_state.get(name)
            if not state or state.get("state") not in {"healthy", "warning"}:
                return "STALE"
            try:
                observed = datetime.fromisoformat(str(state["last_seen_at"]).replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                return "STALE"
            if (now - observed).total_seconds() > 15 * 60:
                return "STALE"
        return "HEALTHY"

    def _startup_collectors_ready(self) -> bool:
        return all(name in self.collector_state for name in ("profile_monitor", "replies_monitor"))

    async def _judge_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(1)
            if time.monotonic() - self._last_hourly_request >= self.judge_interval_seconds:
                self._last_hourly_request = time.monotonic()
                self.request_judge("hourly")
            if not self._judge_dirty or self.database.pending_job_count() > 0:
                continue
            if self._startup_judge_deadline is not None:
                now = time.monotonic()
                if not self._startup_collectors_ready() and now < self._startup_judge_deadline:
                    continue
                self.runtime_log.write("llm", "RADAR_JUDGE_STARTUP_GATE_RELEASED", metadata={
                    "collectors_ready": self._startup_collectors_ready(),
                    "reason": "collectors_ready" if self._startup_collectors_ready() else "grace_elapsed",
                })
                self._startup_judge_deadline = None
            if time.monotonic() - self._judge_requested_at < 3:
                continue
            self._judge_dirty = False
            try:
                await self.run_judge()
                self._judge_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._judge_failures += 1
                safe_error = f"{type(error).__name__}: {error}"[:1000]
                self.database.set_state("judge", {"status": "failed", "last_error": safe_error, "failed_at": utc_now(), "model": self.model})
                self.runtime_log.write("llm", "RADAR_JUDGE_FAILED", result="failure", metadata={"error_type": type(error).__name__, "attempt": self._judge_failures})
                if self._judge_failures < 3:
                    self._judge_dirty = True
                    self._judge_requested_at = time.monotonic() + 27

    async def run_judge(
        self,
        *,
        as_of: str | datetime | None = None,
        data_health: str | None = None,
    ) -> int:
        self.database.set_state("judge", {"status": "processing", "started_at": utc_now(), "model": self.model})
        context = self.database.judgement_context(as_of=as_of)
        result = await judge(self.client, context, data_health=data_health or self._data_health(), as_of=as_of)
        current_cycle = context.get("current_cycle")
        result.update({"model": self.model, "prompt_version": JUDGE_PROMPT_VERSION,
                       "cycle_id": current_cycle["id"] if current_cycle else None,
                       "special_event_ids": [event["id"] for event in context["reset_events"] if event["event_type"] == "SPECIAL_RESET"],
                       "corpus_version": context.get("corpus_version"),
                       "historical_case_ids": [case["case_id"] for case in context.get("historical_cases") or []]})
        result["raw"]["corpus_version"] = result.get("corpus_version")
        result["raw"]["historical_case_ids"] = result.get("historical_case_ids")
        judgement_id = self.database.add_judgement(result)
        self.database.set_state("judge", {"status": "ready", "judgement_id": judgement_id, "completed_at": utc_now(), "model": self.model, "last_error": None})
        self.database.set_state("pipeline", {"status": "ready", "enabled": True, "model": self.model, "last_error": None, "updated_at": utc_now()})
        self.runtime_log.write("llm", "RADAR_JUDGE_SAVED", metadata={"judgement_id": judgement_id, "action_level": result["action_level"], "evidence_count": len(result["evidence_post_ids"]), "corpus_version": result.get("corpus_version"), "historical_case_ids": result.get("historical_case_ids")})
        return judgement_id
