from __future__ import annotations

import asyncio
import json
import time
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .db import Database, JudgementReferenceError, text_language, utc_now
from .deepseek import DeepSeekError, build_request_payload
from .intelligence import (
    ANALYSIS_PROMPT_VERSION,
    JUDGE_PROMPT_VERSION,
    TRANSLATION_PROMPT_VERSION,
    JsonModel,
    analyse_post,
    candidate_record,
    event_records,
    judge,
    ledger_processing_output,
    translate_post,
)
from .logging_runtime import RuntimeLog
from .collector_health import collector_health
from .prediction_ledger import (
    AttemptTracker,
    LateInputRejected,
    PredictionLedger,
    active_attempt_tracker,
)
from .review_common import utc_text
from .runtime_identity import capture_runtime_identity


class TranslationStageError(RuntimeError):
    pass


# Profile/Replies heartbeats are emitted every 60 seconds. Keep serving the
# previous judgement while startup waits for one complete collector cycle.
STARTUP_JUDGE_GRACE_SECONDS = 60
JUDGE_MAX_MERGE_WAIT_SECONDS = 60
JUDGE_DEBOUNCE_SECONDS = 3


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
        prediction_ledger: PredictionLedger | None = None,
        runtime_identity: dict[str, Any] | None = None,
        is_synthetic: bool = False,
    ) -> None:
        if not isinstance(is_synthetic, bool):
            raise TypeError("is_synthetic must be an explicit boolean")
        self.database = database
        self.client = client
        self.runtime_log = runtime_log
        self.collector_state = collector_state
        self.repository_root = repository_root
        self.judge_interval_seconds = judge_interval_seconds
        self.prediction_ledger = prediction_ledger or PredictionLedger(database)
        self.is_synthetic = is_synthetic
        self.runtime_identity = dict(runtime_identity) if runtime_identity else None
        self.runtime_id: str | None = str(self.runtime_identity["runtime_id"]) if self.runtime_identity else None
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopping = False
        self._judge_dirty = False
        self._judge_requested_at = 0.0
        self._judge_not_before = 0.0
        self._judge_lock = asyncio.Lock()
        self._judge_triggers: set[str] = set()
        self._last_data_health = self._data_health()
        self._last_hourly_request = time.monotonic()
        self._judge_failures = 0
        self._startup_judge_deadline: float | None = None

    def _ensure_runtime_identity(self) -> None:
        if self.runtime_identity is None:
            self.runtime_identity = capture_runtime_identity(None, self.client)
        if self.runtime_id is None:
            self.runtime_id = str(self.runtime_identity["runtime_id"])
        if not getattr(self, "_runtime_identity_recorded", False):
            self.prediction_ledger.record_runtime_identity(
                self.runtime_identity,
                is_synthetic=self.is_synthetic,
            )
            self._runtime_identity_recorded = True

    @property
    def model(self) -> str:
        return self.client.model

    def identity(self, post: dict[str, Any]) -> str:
        version = self.database.contexts.input(post)['input_hash']
        return f"{post['id']}:{version}:{ANALYSIS_PROMPT_VERSION}:{TRANSLATION_PROMPT_VERSION}:{self.model}"

    async def start(self) -> None:
        self._ensure_runtime_identity()
        recovered_ledger = self.prediction_ledger.recover_incomplete(current_runtime_id=self.runtime_id)
        recovered = self.database.recover_jobs()
        candidates_path = self.repository_root / "data" / "analysis" / "v1-reset-migration-candidates.json"
        candidate_ids: list[str] = []
        try:
            payload = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidate_ids = [str(item["tweet_id"]) for item in payload.get("candidates", [])]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            candidate_ids = []
        queued = 0
        bootstrap = self.database.bootstrap_posts(candidate_ids)
        with self.database.connect() as c:
            recent_replies = c.execute("SELECT id FROM tibo_posts WHERE is_reply=1 AND posted_at>=datetime('now','-7 days') AND ingestion_mode!='historical'").fetchall()
        bootstrap = list({p['id']:p for p in bootstrap+[self.database.get_post(row['id']) for row in recent_replies]}.values())
        for post in bootstrap:
            if post.get('is_reply'):
                self.database.contexts.ensure(post['tweet_id'])
            queued += int(self.database.enqueue_post(post["id"], self.identity(post), retry_failed=False))
        self.database.set_state("pipeline", {
            "status": "processing" if queued or recovered else "ready", "enabled": True,
            "model": self.model, "queued_at_start": queued, "recovered_jobs": recovered,
            "recovered_ledger_attempts": len(recovered_ledger),
            "last_error": None, "started_at": utc_now(),
        })
        self.runtime_log.write("app", "INTELLIGENCE_PIPELINE_STARTED", metadata={
            "model": self.model, "queued": queued, "recovered": recovered,
            "recovered_ledger_attempts": len(recovered_ledger),
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
            post = self.database.get_post(int(item['post_id']))
            if post and post.get('is_reply'):
                self.database.contexts.ensure(post['tweet_id'])
                identity=self.identity(post)
                queued += int(self.database.enqueue_post(post['id'],identity,retry_failed=False))
                continue
            if not item.get("queue"):
                continue
            post = self.database.get_post(int(item["post_id"]))
            if post and self.database.enqueue_post(post["id"], self.identity(post)):
                queued += 1
        if queued:
            self.database.set_state("pipeline", {"status": "processing", "enabled": True, "model": self.model, "last_error": None, "updated_at": utc_now()})
            self.request_judge('post_ingested')
        return queued

    def request_judge(self, trigger: str) -> None:
        self._judge_triggers.add(trigger)
        if not self._judge_dirty:
            self._judge_requested_at = time.monotonic()
        self._judge_dirty = True
        self.runtime_log.write("llm", "RADAR_JUDGE_REQUESTED", metadata={"trigger": trigger})

    async def _worker(self, worker_number: int) -> None:
        while not self._stopping:
            job = self.database.claim_post_job()
            if not job:
                await asyncio.sleep(1)
                continue
            post_id = int(job["payload"]["post_id"])
            try:
                waiting_post = self.database.get_post(post_id)
                if waiting_post and waiting_post.get('is_reply') and self.database.contexts.waiting(waiting_post):
                    with self.database.connect() as c:
                        c.execute("UPDATE processing_jobs SET status='PENDING',attempts=MAX(0,attempts-1),last_error='WAITING_FOR_REPLY_CONTEXT',next_attempt_at=? WHERE id=?",
                            ((datetime.now(UTC)+timedelta(seconds=5)).isoformat().replace('+00:00','Z'),job['id']))
                    continue
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
                self.request_judge('post_failed')
                self.runtime_log.write("llm", "POST_PROCESSING_FAILED", result="failure", metadata={
                    "post_id": post_id, "job_id": job["id"], "attempt": job["attempts"],
                    "retry_at": retry_at, "error_type": type(error).__name__,
                })

    async def _process_post(self, post_id: int) -> None:
        post = self.database.get_post(post_id)
        if not post:
            raise ValueError(f"post {post_id} no longer exists")
        if not str(post.get('original_text') or '').strip():
            self.database.mark_post_input_restricted(post_id,'BODY_UNAVAILABLE: no original body to analyse or translate')
            return
        post = self.database.contexts.input(post)
        self.database.contexts.archive_input(post)
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
        post_hash = str(post['input_hash'])
        analysis_identity = {"model": self.model, "prompt_version": ANALYSIS_PROMPT_VERSION}
        analysis = self.database.latest_analysis(post_id, post_hash, ANALYSIS_PROMPT_VERSION, self.model)
        if analysis is None:
            analysis = await analyse_post(
                self.client, post,
                request_scope=lambda request: self._processing_request_scope(
                    post, "post_analysis", post_hash, analysis_identity, request,
                ),
            )
            analysis.update({'_input_hash':post_hash,'_text_hash':post['text_hash'],'_analysed_at':utc_now()})
            if self.database.contexts.input(self.database.get_post(post_id))['input_hash'] != post_hash:
                self.database.enqueue_post(post_id, self.identity(self.database.get_post(post_id)))
                return
            analysis_id = self.database.save_analysis(post_id, post_hash, self.model, ANALYSIS_PROMPT_VERSION, analysis)
            self.runtime_log.write("llm", "POST_ANALYSIS_SAVED", metadata={"post_id": post_id, "tweet_id": post["tweet_id"], "analysis_id": analysis_id, "category": analysis["category"]})
        else:
            self._ensure_runtime_identity()
            self.prediction_ledger.record_cache_reused(
                stage="post_analysis", input_hash=post_hash,
                output=ledger_processing_output("post_analysis", analysis),
                runtime_id=str(self.runtime_id), processing_identity=analysis_identity,
                input_material=post,
                public_prompt={"operation": "post_analysis", "prompt_version": ANALYSIS_PROMPT_VERSION},
            )

        if self.database.content_use_allowed(post, "event_promotion") and analysis.get('context_sufficient', True):
            records=event_records(post, analysis)
            existing=[event for event in self.database.list_reset_events(200) if post['tweet_id'] in event.get('evidence_post_ids',[])]
            protected=[event for event in existing if
                event.get('provenance',{}).get('source')!='deepseek_semantic_analysis'
                or event.get('provenance',{}).get('human_adjudications')
                or event.get('provenance',{}).get('review_package')]
            if protected:
                self.database.set_state(f'reply_review:{post_id}', {'state':'NEEDS_HUMAN_REVIEW',
                    'input_hash':post_hash,'preserved_event_ids':[e['id'] for e in protected],
                    'proposed_effects':analysis.get('effects',[]),'reason':'Context reanalysis cannot overwrite reviewed event fields'})
                records=[]
            for disposition, record in records:
                record.setdefault('provenance',{})['input_hash']=post_hash
                if disposition == "confirmed":
                    saved = self.database.upsert_reset_event(record, is_synthetic=self.is_synthetic)
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

        translation_key = f'reply_translation:{post_id}'
        needs_translation = ((post.get('is_reply') and self.database.get_state(translation_key) != post_hash)
                             or post.get("translation_status") != "COMPLETED" or not post.get("translated_text"))
        translation_identity = {"model": self.model, "prompt_version": TRANSLATION_PROMPT_VERSION}
        if needs_translation:
            try:
                translated = await translate_post(
                    self.client, post,
                    request_scope=lambda request: self._processing_request_scope(
                        post, "post_translation", post_hash, translation_identity, request,
                    ),
                )
                if self.database.contexts.input(self.database.get_post(post_id))['input_hash'] != post_hash:
                    self.database.enqueue_post(post_id, self.identity(self.database.get_post(post_id)))
                    return
                self.database.save_translation(post_id, post['text_hash'], translated)
                self.database.set_state(translation_key, post_hash)
                self.runtime_log.write("llm", "POST_TRANSLATION_SAVED", metadata={"post_id": post_id, "tweet_id": post["tweet_id"]})
            except Exception as error:
                self.database.save_translation(post_id, post['text_hash'], None, f"{type(error).__name__}: {error}")
                raise TranslationStageError(f"{type(error).__name__}: {error}") from error
        elif text_language(str(post.get("original_text") or post.get("text") or "")) != "zh":
            self._ensure_runtime_identity()
            self.prediction_ledger.record_cache_reused(
                stage="post_translation", input_hash=post_hash,
                output=ledger_processing_output("post_translation", str(post.get("translated_text") or "")),
                runtime_id=str(self.runtime_id), processing_identity=translation_identity,
                input_material=post,
                public_prompt={"operation": "post_translation", "prompt_version": TRANSLATION_PROMPT_VERSION},
            )

    @contextmanager
    def _processing_request_scope(
        self,
        post: dict[str, Any],
        stage: str,
        input_hash: str,
        processing_identity: dict[str, Any],
        request: dict[str, Any],
    ):
        self._ensure_runtime_identity()
        synthetic = self.is_synthetic
        http_instrumented = bool(getattr(self.client, "ledger_attempts_enabled", False))
        run = self.prediction_ledger.begin_processing_run(
            {
                "input": post,
                "input_hash": input_hash,
                "processing_identity": processing_identity,
                "public_prompt": {
                    "operation": stage,
                    "system": request.get("system"),
                    "prompt_version": processing_identity.get("prompt_version"),
                },
                "schema": request.get("schema"),
            },
            stage=stage,
            runtime_id=str(self.runtime_id),
            trigger="post_processing",
            is_synthetic=synthetic,
        )
        tracker = AttemptTracker(
            self.prediction_ledger, run.run_id,
            {
                "stage": stage,
                "operation": stage,
                "input_hash": input_hash,
                "processing_identity": processing_identity,
                "input_artifact_refs": list(run.input_artifact_refs),
                "input_frame_artifact_ref": run.input_frame_artifact_ref,
                "prompt_artifact_ref": run.prompt_artifact_ref,
                "schema_artifact_ref": run.schema_artifact_ref,
            },
            dict((self.runtime_identity or {}).get("owner") or {}),
            is_synthetic=run.is_synthetic,
        )
        if synthetic and not http_instrumented:
            tracker.prepare_request(build_request_payload(
                self.model, str(request["system"]), str(request["user"]),
            ))
            tracker.begin_attempt()
        with active_attempt_tracker(tracker):
            try:
                yield tracker
            except asyncio.CancelledError:
                self._record_processing_failure(tracker, asyncio.CancelledError(), "cancelled")
                raise
            except Exception as error:
                event_type = "persistence_failure" if isinstance(error, sqlite3.Error) else (
                    "schema_failure" if isinstance(error, (ValueError, TypeError)) else "request_failure"
                )
                self._record_processing_failure(tracker, error, event_type)
                raise

    def _record_processing_failure(self, tracker: AttemptTracker, error: BaseException, event_type: str) -> None:
        attempt_id = tracker.latest_attempt_id
        if attempt_id and self.prediction_ledger.attempt_is_terminal(tracker.run_id, attempt_id):
            return
        payload = {
            "failure_terminal": True,
            "reason_code": event_type.upper(),
            "error_type": type(error).__name__,
            "attempt_finished_at": utc_text(),
        }
        if attempt_id:
            tracker.append_event(attempt_id, event_type, **payload)
        else:
            self.prediction_ledger.append_run_event(tracker.run_id, event_type, **payload)

    def _data_health(self) -> str:
        return collector_health(self.collector_state)['data_health']

    def judge_waiting(self) -> bool:
        elapsed = time.monotonic() - self._judge_requested_at
        return (time.monotonic() < self._judge_not_before or elapsed < JUDGE_DEBOUNCE_SECONDS
                or (elapsed < JUDGE_MAX_MERGE_WAIT_SECONDS and bool(self.database.judge_pending_inputs())))

    def _startup_collectors_ready(self) -> bool:
        return all(name in self.collector_state for name in ("profile_monitor", "replies_monitor"))

    async def _judge_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(1)
            health = self._data_health()
            if health != self._last_data_health:
                self._last_data_health = health
                self.request_judge('collector_freshness_transition')
            if time.monotonic() - self._last_hourly_request >= self.judge_interval_seconds:
                self._last_hourly_request = time.monotonic()
                self.request_judge("hourly")
            if not self._judge_dirty or self.judge_waiting():
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
                    self._judge_requested_at = time.monotonic()
                    self._judge_not_before = time.monotonic() + 30

    async def run_judge(
        self,
        *,
        as_of: str | datetime | None = None,
        data_health: str | None = None,
    ) -> int:
        async with self._judge_lock:
            return await self._run_judge(as_of=as_of, data_health=data_health)

    def _ledger_evidence_sources(self, context: dict[str, Any], as_of: str | datetime | None) -> list[dict[str, Any]]:
        tweet_ids = {
            str(tweet_id)
            for event in context.get("reset_events") or []
            for tweet_id in event.get("evidence_post_ids") or []
        }
        for case in context.get("historical_cases") or []:
            tweet_ids.update(str(tweet_id) for tweet_id in case.get("related_tweet_ids") or [])
        prompt_post_ids = {str(post.get("tweet_id")) for post in context.get("posts") or []}
        sources: list[dict[str, Any]] = []
        for tweet_id in sorted(tweet_ids):
            post = self.database.get_post_by_tweet_id(tweet_id)
            if post is None:
                sources.append({"tweet_id": tweet_id, "role": "event_source_post", "snapshot_status": "source_not_local"})
                continue
            policy = self.database.content_policy(int(post["id"]))
            if not self.database.content_use_allowed(post, "judge_evidence"):
                sources.append({
                    "post_id": int(post["id"]), "tweet_id": tweet_id, "role": "event_source_post",
                    "snapshot_status": "policy_restricted",
                    "policy_version": policy.get("policy_version") if policy else "content-policy-v1",
                })
                continue
            snapshot = self.database._post_input_at(post, as_of)
            if not snapshot:
                sources.append({
                    "post_id": int(post["id"]), "tweet_id": tweet_id, "role": "event_source_post",
                    "snapshot_status": "historical_version_unavailable",
                })
                continue
            body = str(snapshot.get("original_text") or snapshot.get("text") or "")
            source_policy = self.database.content_policy(int(post["id"]))
            reply_nodes = (snapshot.get("reply_context") or {}).get("nodes") or []
            sources.append({
                "post_id": int(post["id"]), "tweet_id": tweet_id,
                "author": snapshot.get("author_handle") or post.get("author_handle") or "thsottiaux",
                "role": "event_source_post" if tweet_id not in prompt_post_ids else "prompt_post_source",
                "relation_to_target": "formal_event_or_case_evidence",
                "parent_tweet_id": snapshot.get("reply_to_tweet_id") if snapshot.get("is_reply") else None,
                "relation_source": reply_nodes[0].get("relation_source") if reply_nodes else None,
                "source_version": snapshot.get("input_hash") or snapshot.get("text_hash"),
                "policy_version": source_policy.get("policy_version") if source_policy else "unreviewed-default",
                "snapshot_status": "frozen",
                "original_text": body,
                "reply_context": snapshot.get("reply_context"),
            })
        return sources

    def _record_judge_failure(self, request_state: dict[str, Any], error: BaseException) -> None:
        run = request_state.get("run")
        tracker = request_state.get("tracker")
        if run is None:
            return
        attempt_id = tracker.latest_attempt_id if tracker else None
        try:
            if attempt_id and self.prediction_ledger.attempt_is_terminal(run.run_id, attempt_id):
                return
            error_type = type(error).__name__
            if isinstance(error, sqlite3.Error):
                event_type = "persistence_failure"
                reason_code = "PERSISTENCE_FAILURE"
            elif isinstance(error, JudgementReferenceError):
                event_type = "reference_failure"
                reason_code = error.reason_code
            elif isinstance(error, DeepSeekError):
                event_type = "request_failure"
                reason_code = error.category.upper()
            elif isinstance(error, (ValueError, TypeError)):
                event_type = "schema_failure"
                reason_code = "INVALID_JUDGE_RESULT"
            else:
                event_type = "request_failure"
                reason_code = error_type.upper()
            event = {
                "failure_terminal": True,
                "reason_code": reason_code,
                "error_type": error_type,
                "attempt_finished_at": utc_text(),
            }
            if attempt_id:
                self.prediction_ledger.append_attempt_event(run.run_id, attempt_id, event_type, **event)
            else:
                self.prediction_ledger.append_run_event(run.run_id, event_type, **event)
        except Exception as persistence_error:
            self.runtime_log.write("app", "PREDICTION_LEDGER_FAILURE_RECORD_FAILED", result="failure", metadata={
                "error_type": type(persistence_error).__name__,
                "run_id": run.run_id,
            })

    async def _run_judge(self, *, as_of=None, data_health=None) -> int:
        self.database.set_state("judge", {"status": "processing", "started_at": utc_now(), "model": self.model})
        context = self.database.judgement_context(as_of=as_of)
        context['pending_inputs'] = self.database.judge_pending_inputs(include_deferred=True) if not as_of else []
        self.database.refresh_input_snapshot(context)
        if not context['posts']:
            self.database.set_state('judge', {'status':'insufficient_input', 'reason':'NO_USABLE_POSTS',
                'recovery':'Waiting for a valid analysis or next scheduled retry', 'updated_at':utc_now()})
            return 0
        triggers = sorted(self._judge_triggers)
        self._judge_triggers.clear()
        self.runtime_log.write('llm','RADAR_JUDGE_ATTEMPT',metadata={'triggers':triggers,'prompt_version':JUDGE_PROMPT_VERSION})
        self._ensure_runtime_identity()
        request_state: dict[str, Any] = {}
        synthetic = self.is_synthetic
        http_instrumented = bool(getattr(self.client, "ledger_attempts_enabled", False))

        @contextmanager
        def request_scope(request_context: dict[str, Any]):
            evidence_sources = self._ledger_evidence_sources(context, as_of)
            frozen_input = {
                "forecast": {
                    "target": "EXTRA_FULL",
                    "scope": {"value": "unknown", "certainty": "not_established_by_ledger"},
                    "question": "next_full_reset_start",
                    "method": "model_inference",
                    "basis": "frozen_judge_input",
                },
                "input_snapshot": self.database.input_snapshot(context),
                "input_cutoff_at": utc_text(),
                "judgement_as_of": request_context.get("judgement_as_of"),
                "selection_mode": "replay" if as_of is not None else "online",
                "context": request_context.get("context") or {},
                "semantic_facts": {
                    "context": request_context.get("context") or {},
                    "evidence_sources": evidence_sources,
                },
                "evidence_sources": evidence_sources,
                "policy_versions": context.get("policy_versions") or {},
                "public_prompt": {
                    "system": request_context["system"],
                    "user_prefix": request_context["user_prefix"],
                    "prompt_version": JUDGE_PROMPT_VERSION,
                },
                "judge_schema": request_context["schema"],
                "data_health": request_context.get("data_health"),
                "pending_inputs": context.get("pending_inputs") or [],
            }
            run = self.prediction_ledger.begin_run(
                frozen_input,
                stage="radar_judge",
                runtime_id=str(self.runtime_id),
                trigger=triggers,
                record_kind="replay" if as_of is not None else "online",
                is_synthetic=synthetic,
            )
            request_descriptor = {
                "stage": "radar_judge",
                "judgement_as_of": request_context.get("judgement_as_of"),
                "input_cutoff_at": run.input_cutoff_at,
                "input_snapshot_hash": run.input_hash,
                "forecast_semantic_hash": run.semantic_hash,
                "input_frame_artifact_ref": run.input_frame_artifact_ref,
                "prompt_artifact_ref": run.prompt_artifact_ref,
                "schema_artifact_ref": run.schema_artifact_ref,
            }
            tracker = AttemptTracker(
                self.prediction_ledger, run.run_id, request_descriptor,
                dict((self.runtime_identity or {}).get("owner") or {}),
                is_synthetic=run.is_synthetic,
            )
            request_state.update({"run": run, "tracker": tracker})
            with active_attempt_tracker(tracker):
                if synthetic and not http_instrumented:
                    tracker.prepare_request(build_request_payload(self.model, request_context["system"], request_context["user"]))
                    tracker.begin_attempt()
                yield

        try:
            result = await judge(
                self.client, context, data_health=data_health or self._data_health(), as_of=as_of,
                request_scope=request_scope,
            )
            current_cycle = context.get("current_cycle")
            result.update({"model": self.model, "prompt_version": JUDGE_PROMPT_VERSION,
                           "cycle_id": current_cycle["id"] if current_cycle else None,
                           "special_event_ids": [event["id"] for event in context["reset_events"] if event["event_type"] == "SPECIAL_RESET"],
                           "corpus_version": context.get("corpus_version"),
                           "historical_case_ids": [case["case_id"] for case in context.get("historical_cases") or []]})
            input_snapshot = self.database.input_snapshot(context)
            result["raw"]["corpus_version"] = result.get("corpus_version")
            result["raw"]["historical_case_ids"] = result.get("historical_case_ids")
            versions = input_snapshot.get('input_versions')
            result['raw']['input_versions'] = versions
            result['raw']['input_post_ids'] = list(versions)
            result['raw']['input_snapshot'] = input_snapshot
            result['raw']['input_snapshot_id'] = self.database._snapshot_digest(input_snapshot)
            result['raw']['triggers'] = triggers
            result['raw']['pending_inputs'] = context['pending_inputs']
            run = request_state["run"]
            tracker = request_state["tracker"]
            accepted_attempt_id = tracker.latest_attempt_id
            if accepted_attempt_id is None:
                raise RuntimeError("Judge result has no durable request attempt")
            output_ref = self.prediction_ledger.commit_judge(run.run_id, accepted_attempt_id, result)
        except asyncio.CancelledError as error:
            self._record_judge_failure(request_state, error)
            raise
        except LateInputRejected:
            self.request_judge('context_changed_during_judge')
            raise
        except Exception as error:
            self._record_judge_failure(request_state, error)
            raise

        observation = None
        observation_error = None
        try:
            observation = self.prediction_ledger.observe_output(output_ref)
        except Exception as error:
            observation_error = type(error).__name__
            self.runtime_log.write("app", "PREDICTION_OUTPUT_OBSERVATION_FAILED", result="failure", metadata={
                "judgement_id": output_ref.judgement_id,
                "error_type": observation_error,
            })
        judgement_id = output_ref.judgement_id
        self.database.set_state("judge", {"status": "ready", "judgement_id": judgement_id, "completed_at": utc_now(), "model": self.model, "last_error": None})
        self.database.set_state("pipeline", {"status": "ready", "enabled": True, "model": self.model, "last_error": None, "updated_at": utc_now(),
                                               "output_available_at": observation.get("observed_at") if observation else None,
                                               "output_observation_error": observation_error})
        self.runtime_log.write("llm", "RADAR_JUDGE_SAVED", metadata={"judgement_id": judgement_id, "action_level": result["action_level"], "evidence_count": len(result["evidence_post_ids"]), "corpus_version": result.get("corpus_version"), "historical_case_ids": result.get("historical_case_ids")})
        return judgement_id
