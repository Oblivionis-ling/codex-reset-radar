from __future__ import annotations

import asyncio
import json
import os
import socket
import smtplib
import sqlite3
import sys
import time
import zipfile
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.deepseek import DeepSeekClient, DeepSeekError
from app.logging_runtime import RuntimeLog
from app.main import create_app
from app.pipeline import IntelligencePipeline
from app.prediction_ledger import PredictionLedger, current_attempt_tracker
from app.prediction_contract import PREDICTION_TARGETS
from app.review_export import export_review, preview_review, verify_review
from app.review_reader import read_review


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLAN_TWEET_ID = "900000000000000101"
BANKED_TWEET_ID = "900000000000000102"
PARENT_TWEET_ID = "900000000000000103"
REPLY_TWEET_ID = "900000000000000104"
ONLINE_INPUT_TWEET_ID = "900000000000000105"
PLAN_BODY_V1 = "SYNTHETIC_PLAN_FIXTURE: a future full reset plan."
PLAN_BODY_V2 = "SYNTHETIC_PLAN_FIXTURE: a materially revised future full reset plan."
PLAN_BODY_V3 = "SYNTHETIC_PLAN_FIXTURE: a reviewed replacement input."
BANKED_BODY = "SYNTHETIC_BANKED_FIXTURE: a completed banked reset fixture."
REPLY_BODY = "SYNTHETIC_REPLY_FIXTURE: the author acknowledges the parent context."
ONLINE_INPUT_BODY = "SYNTHETIC_ONLINE_INPUT_FIXTURE: newly valid input discovered in flight."


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def hermetic_io_guard(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
):
    """Fail closed before any isolated DB/pipeline startup or fake HTTP request."""
    temp_root = tmp_path_factory.getbasetemp().resolve()
    assert _within(tmp_path, temp_root)
    # The fixture supplies a safe default for ordinary pytest/CI runs. The
    # focused command also sets this before collection so conftest's app.main
    # import is already isolated; this override protects every tested startup.
    default_database = temp_root / "prediction-review-import-guard.sqlite"
    monkeypatch.setenv("CRR_DATABASE_PATH", str(default_database))
    if default_database.exists():
        raise AssertionError("the pytest app.main import-guard database must be fresh and empty")

    original_connect = sqlite3.connect

    def isolated_sqlite_connect(database: Any, *args: Any, **kwargs: Any):
        value = os.fspath(database) if isinstance(database, os.PathLike) else str(database)
        if value == ":memory:":
            return original_connect(database, *args, **kwargs)
        if value.startswith("file:"):
            parsed = urlsplit(value)
            query = parse_qs(parsed.query)
            path_value = unquote(parsed.path)
            if os.name == "nt" and path_value.startswith("/") and len(path_value) > 2 and path_value[2] == ":":
                path_value = path_value[1:]
            target = Path(path_value).resolve()
            mode = query.get("mode", [None])[0]
            if mode == "ro" and not _within(target, temp_root):
                raise AssertionError("read-only SQLite access outside test basetemp is forbidden here")
        else:
            target = Path(value).resolve()
        if not _within(target, temp_root):
            raise AssertionError("SQLite access escaped the dedicated pytest basetemp")
        return original_connect(database, *args, **kwargs)

    original_socket_connect = socket.socket.connect

    def blocked_socket_connect(sock: socket.socket, address: Any):
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code.co_name == "_fallback_socketpair" and frame.f_globals.get("__name__") == "socket":
                # Windows asyncio's Proactor loop uses a local TCP socketpair
                # as its wakeup pipe; permit only that interpreter-internal call.
                return original_socket_connect(sock, address)
            frame = frame.f_back
        raise AssertionError("network access is disabled in prediction-review tests")

    def blocked_network(*_args: Any, **_kwargs: Any):
        raise AssertionError("network access is disabled in prediction-review tests")

    monkeypatch.setattr(sqlite3, "connect", isolated_sqlite_connect)
    monkeypatch.setattr(socket.socket, "connect", blocked_socket_connect)
    monkeypatch.setattr(socket, "create_connection", blocked_network)
    for smtp_name in ("SMTP", "SMTP_SSL", "LMTP"):
        monkeypatch.setattr(smtplib, smtp_name, blocked_network)


class FakeClock:
    """Synthetic wall clock; request duration continues to use real monotonic time."""

    def __init__(self, current: datetime) -> None:
        self.current = current.astimezone(UTC)

    def text(self, value: str | datetime | None = None) -> str:
        if value is None:
            current = self.current
        elif isinstance(value, datetime):
            current = value
        else:
            current = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def advance(self, amount: timedelta) -> None:
        self.current += amount


@contextmanager
def _fake_clock(monkeypatch: pytest.MonkeyPatch, clock: FakeClock):
    """Restore module clocks even when a scenario assertion aborts early."""
    with monkeypatch.context() as scoped:
        for name in ('app.prediction_ledger.utc_text', 'app.deepseek.utc_text', 'app.pipeline.utc_text',
                     'app.db.utc_now', 'app.reply_context.now'):
            scoped.setattr(name, clock.text)
        yield


def _parse_json_tail(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise AssertionError("synthetic request did not contain a JSON object")
    value = json.loads(text[start:])
    if not isinstance(value, dict):
        raise AssertionError("synthetic request JSON was not an object")
    return value


def _judge_result(
    estimated_start: str | None,
    *,
    reason: str = "Synthetic fixture result.",
    levels: tuple[str, str, str, str] = ("YELLOW", "YELLOW", "ORANGE", "RED"),
) -> dict[str, Any]:
    action, horizon_24, horizon_48, horizon_72 = levels
    return {
        "action_level": action,
        "horizon_24h": horizon_24,
        "horizon_48h": horizon_48,
        "horizon_72h": horizon_72,
        "estimated_start": estimated_start,
        "estimated_end": None,
        "estimate_basis": "synthetic isolated fixture only",
        "reason_summary": reason,
        "evidence_post_ids": [PLAN_TWEET_ID],
        # The new formal Judge contract requires both targets. These old Full
        # alert regression fixtures have no independent date evidence for the
        # target contract, so they explicitly say UNKNOWN instead of inventing
        # a Banked prediction from legacy estimated_start.
        "predictions": {
            target: {"target": target, "status": "UNKNOWN", "method": "model_inference",
                     "scope": {"value": "unknown", "certainty": "not_established"},
                     "predicted_start": None, "predicted_end": None, "prediction_form": "unknown",
                     "source_timezone": None, "precision": "unknown", "time_basis": "unknown",
                     "expression": None, "relative_anchor_at": None, "relative_offset_seconds": None,
                     "reason": "Legacy Full-alert fixture has no independent prospective target date.",
                     "unresolved_reason": "NO_INDEPENDENT_TIME_BASIS", "evidence_post_ids": [],
                     "evidence_refs": [], "lifecycle": "unknown"}
            for target in ("EXTRA_FULL", "BANKED")
        },
    }


@dataclass
class JudgeAction:
    result: dict[str, Any] | None = None
    status: int = 200
    invalid_json: bool = False
    timeout: bool = False
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None
    before_response: Callable[[], None] | None = None
    advance_after: timedelta = timedelta(0)


class FakeDeepSeekTransport:
    """httpx MockTransport: all judge attempts are inspected before a fake send."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.database: Database | None = None
        self.judge_actions: deque[JudgeAction] = deque()
        self.all_attempt_ids: list[str] = []
        self.attempt_ids_by_operation: dict[str, list[str]] = {}
        self.judge_attempt_ids: list[str] = []
        self.send_persistence_checks = 0
        self.analysis_payloads: list[dict[str, Any]] = []
        self.judge_payloads: list[dict[str, Any]] = []

    def queue_judge(self, action: JudgeAction) -> None:
        self.judge_actions.append(action)

    @staticmethod
    def _operation(system: str) -> str:
        if "reply_context 是分作者的真实上下文" in system:
            return "radar_judge"
        if "你还负责忠实中文翻译" in system:
            return "post_translation"
        return "post_analysis"

    def _assert_attempt_is_durable_before_send(self) -> str:
        tracker = current_attempt_tracker()
        assert tracker is not None, "formal DeepSeek request must establish durable request scope"
        assert tracker.attempts, "attempt must be persisted before MockTransport receives HTTP"
        attempt = tracker.attempts[-1]
        assert self.database is not None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM prediction_ledger WHERE kind='attempt_started' AND attempt_id=?",
                (attempt.attempt_id,),
            ).fetchone()
            assert row is not None, "attempt_started must commit before HTTP send"
            start_payload = json.loads(row["payload_json"])
            descriptor = start_payload["request_artifact_ref"]
            artifact = connection.execute(
                "SELECT kind FROM prediction_artifacts WHERE id=?",
                (descriptor["artifact_id"],),
            ).fetchone()
            assert artifact is not None and artifact["kind"] == "request_descriptor"
            retry_of = start_payload.get("retry_of")
            if retry_of:
                terminal = connection.execute(
                    "SELECT payload_json FROM prediction_ledger WHERE kind='attempt_event' AND attempt_id=?",
                    (retry_of,),
                ).fetchall()
                assert any(
                    json.loads(item["payload_json"]).get("failure_terminal") is True
                    for item in terminal
                ), "previous failure must be durable before retry HTTP send"
        self.send_persistence_checks += 1
        self.all_attempt_ids.append(attempt.attempt_id)
        return attempt.attempt_id

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        envelope = json.loads(request.content)
        messages = envelope["messages"]
        system = str(messages[0]["content"])
        user = str(messages[1]["content"])
        operation = self._operation(system)
        attempt_id = self._assert_attempt_is_durable_before_send()
        self.attempt_ids_by_operation.setdefault(operation, []).append(attempt_id)

        if operation == "post_translation":
            result: dict[str, Any] = {"translation_zh": "合成隔离夹具译文。"}
            return self._json_response(result)
        if operation == "post_analysis":
            request_data = _parse_json_tail(user)
            self.analysis_payloads.append(request_data)
            result = self._analysis_result(str(request_data["post"]["tweet_id"]))
            return self._json_response(result)

        self.judge_payloads.append(_parse_json_tail(user))
        self.judge_attempt_ids.append(attempt_id)
        if not self.judge_actions:
            raise AssertionError("unexpected Judge HTTP request without a synthetic response script")
        action = self.judge_actions.popleft()
        if action.entered is not None:
            action.entered.set()
        if action.release is not None:
            await action.release.wait()
        if action.before_response is not None:
            action.before_response()
        if action.advance_after:
            self.clock.advance(action.advance_after)
        if action.timeout:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if action.invalid_json:
            return httpx.Response(200, text="not-json-synthetic-response")
        if action.status >= 400:
            return httpx.Response(action.status, json={"error": "synthetic transport failure"})
        if action.result is None:
            raise AssertionError(f"missing synthetic result for persisted attempt {attempt_id}")
        return self._json_response(action.result)

    @staticmethod
    def _json_response(result: dict[str, Any]) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "synthetic-supplier-reported-model",
                "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26},
            },
        )

    @staticmethod
    def _analysis_result(tweet_id: str) -> dict[str, Any]:
        relevant_fixture = {
            PLAN_TWEET_ID: {
                "category": "reset_announcement",
                "temporal_mode": "future",
                "explicit_announcement": True,
                "execution_stage": "announced",
                "summary": "合成夹具中的未来计划；没有声称重置已经发生。",
            },
            REPLY_TWEET_ID: {
                "category": "codex_related",
                "temporal_mode": "unclear",
                "summary": "合成夹具中的相关回复；只延续父帖语境，不确认事件发生。",
            },
            ONLINE_INPUT_TWEET_ID: {
                "category": "codex_related",
                "temporal_mode": "unclear",
                "summary": "合成夹具中的新相关输入；不确认额度事件发生。",
            },
        }.get(tweet_id, {})
        return {
            "tweet_id": tweet_id,
            "category": relevant_fixture.get("category", "other"),
            "codex_relevant": bool(relevant_fixture),
            "temporal_mode": relevant_fixture.get("temporal_mode", "present"),
            "explicit_announcement": relevant_fixture.get("explicit_announcement", False),
            "event_status": "none",
            "event_type": "NONE",
            "special_type": None,
            "canonical_eligible": False,
            "scope": "unknown",
            "execution_stage": relevant_fixture.get("execution_stage", "unknown"),
            "event_time_start": None,
            "event_time_end": None,
            "time_basis": "unknown",
            "evidence_quote": "Synthetic fixture response; no source-content inference.",
            "summary": relevant_fixture.get("summary", "Synthetic unrelated/other decoy fixture."),
            "event_title": "",
            "effects": [],
            "context_sufficient": True,
        }


@dataclass
class PipelineHarness:
    database: Database
    pipeline: IntelligencePipeline
    transport: FakeDeepSeekTransport
    model: DeepSeekClient
    runtime_log: RuntimeLog

    async def close(self) -> None:
        await asyncio.wait_for(self.pipeline.stop(), timeout=5)


async def _start_harness(
    settings: Settings,
    clock: FakeClock,
) -> PipelineHarness:
    database = Database(settings.database_path)
    database.initialize()
    runtime_log = RuntimeLog(settings.log_dir, settings.log_retention_days, settings.log_max_bytes)
    transport = FakeDeepSeekTransport(clock)
    model = DeepSeekClient(
        api_key="synthetic-test-only",
        base_url="https://mock.invalid",
        model="fake-deepseek-prediction-review",
        timeout_seconds=5,
        retries=1,
        runtime_log=runtime_log,
    )
    await asyncio.wait_for(model._client.aclose(), timeout=5)
    model._client = httpx.AsyncClient(transport=httpx.MockTransport(transport), timeout=5)
    transport.database = database
    pipeline = IntelligencePipeline(
        database=database,
        client=model,
        runtime_log=runtime_log,
        collector_state={},
        repository_root=REPOSITORY_ROOT,
        judge_interval_seconds=3600,
        is_synthetic=True,
    )
    await asyncio.wait_for(pipeline.start(), timeout=10)
    # This test drives the public formal run_judge method explicitly; the normal
    # scheduler remains idle because it has no collector heartbeats.
    pipeline._judge_dirty = False
    return PipelineHarness(database, pipeline, transport, model, runtime_log)


def _post_record(tweet_id: str, body: str, posted_at: str) -> dict[str, Any]:
    return {
        "tweet_id": tweet_id,
        "text": body,
        "posted_at": posted_at,
        "url": f"https://example.invalid/synthetic/{tweet_id}",
        "source": "synthetic_fixture",
    }


async def _process_fixture_post(harness: PipelineHarness, tweet_id: str, body: str, posted_at: str) -> int:
    result = harness.database.upsert_posts_detailed([_post_record(tweet_id, body, posted_at)])[0]
    post_id = int(result["post_id"])
    await harness.pipeline._process_post(post_id)
    post = harness.database.get_post(post_id)
    assert post is not None and post["analysis_status"] == "COMPLETED"
    assert post["translation_status"] == "COMPLETED"
    return post_id


def _reply_context_node(
    tweet_id: str,
    author: str,
    text: str,
    posted_at: str,
    parent_id: str | None = None,
) -> dict[str, Any]:
    return {
        "tweet_id": tweet_id,
        "author": author,
        "text": text,
        "posted_at": posted_at,
        "parent_id": parent_id,
        "relation_source": "x_replied_to_field",
        "language": "en",
        "completeness": "complete",
    }


async def _process_fixture_reply(harness: PipelineHarness, posted_at: str) -> int:
    database = harness.database
    reply = _post_record(REPLY_TWEET_ID, REPLY_BODY, posted_at)
    reply.update({"is_reply": True, "reply_to_tweet_id": PARENT_TWEET_ID})
    post_id = int(database.upsert_posts_detailed([reply])[0]["post_id"])
    parent_at = _datetime(posted_at) - timedelta(minutes=1)
    observed_at = harness.transport.clock.text()
    database.contexts.record_observation(
        _reply_context_node(PARENT_TWEET_ID, "community_member", "What is the release window?", harness.transport.clock.text(parent_at)),
        observed_at,
    )
    database.contexts.record_observation(
        _reply_context_node(REPLY_TWEET_ID, "thsottiaux", REPLY_BODY, posted_at, PARENT_TWEET_ID),
        observed_at,
    )
    await harness.pipeline._process_post(post_id)
    processed = database.get_post(post_id)
    assert processed is not None and processed["analysis_status"] == "COMPLETED"
    assert processed["translation_status"] == "COMPLETED"
    return post_id


def _read_radar_api(database: Database, settings: Settings, tmp_path: Path) -> dict[str, Any]:
    api_settings = replace(
        settings,
        database_path=database.path,
        log_dir=tmp_path / "radar-api-logs",
        deepseek_api_key="",
    )
    with TestClient(create_app(api_settings)) as client:
        for component in ("profile_monitor", "replies_monitor", "search_backfill"):
            response = client.post("/api/v2/collector/heartbeat", json={
                "component": component, "instance_id": f"{component}-synthetic-fixture", "sequence": 1,
            })
            assert response.status_code == 200
        response = client.get("/api/v2/radar")
        assert response.status_code == 200
        return response.json()


def _allow_policy(tweet_id: str, content_hash: str, version: str) -> dict[str, Any]:
    return {
        "tweet_id": tweet_id,
        "content_hash": content_hash,
        "policy_status": "SYNTHETIC_REVIEWED_ALLOWED",
        "analysis_allowed": True,
        "event_promotion_allowed": True,
        "judge_evidence_allowed": True,
        "historical_case_allowed": True,
        "reason": "Synthetic test fixture policy; never a production decision.",
        "policy_version": version,
        "decision_ids": [f"synthetic-{version}"],
    }


def _ledger_rows(database: Database, kind: str) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT seq,record_id,kind,series_id,forecast_id,run_id,attempt_id,revision,judgement_id,event_id,occurred_at,recorded_at,payload_json "
            "FROM prediction_ledger WHERE kind=? ORDER BY seq",
            (kind,),
        ).fetchall()
    return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]


def _attempt_events(database: Database, attempt_id: str) -> list[dict[str, Any]]:
    return [row for row in _ledger_rows(database, "attempt_event") if row["attempt_id"] == attempt_id]


def _forecast_chains(database: Database) -> dict[str, list[dict[str, Any]]]:
    rows = _ledger_rows(database, 'forecast_version')
    assert {row['payload']['target'] for row in rows} == set(PREDICTION_TARGETS)
    chains = {target: [row for row in rows if row['payload']['target'] == target] for target in PREDICTION_TARGETS}
    assert len({row['forecast_id'] for row in rows}) == len(rows)
    for target, chain in chains.items():
        for index, row in enumerate(chain):
            assert row['series_id'] == chain[0]['series_id']
            assert row['revision'] == index + 1
            assert row['payload']['previous_id'] == (chain[index - 1]['forecast_id'] if index else None)
            assert row['payload']['version_role'] == 'question_version' and row['payload']['method'] is None
    return chains


def _record_banked_marker(
    database: Database,
    occurred_at: str,
    label: str,
    *,
    source_post_id: int | None = None,
    evidence_post_ids: list[str] | None = None,
    time_basis: str = "explicit_text",
) -> dict[str, Any]:
    return database.record_reset_event({
        "event_type": "SPECIAL_RESET",
        "special_type": "BANKED",
        "occurred_at": occurred_at,
        "time_basis": time_basis,
        "scope": "banked_only",
        "execution_stage": "completed",
        "source_post_id": source_post_id,
        "evidence_post_ids": evidence_post_ids or [],
        "title": f"Synthetic Banked marker {label}",
        "summary": "Synthetic test-only event; does not open a Full cycle.",
        "provenance": {"is_synthetic": True, "source": "pipeline-isolation-fixture", "fixture": label},
    }, is_synthetic=True)


def _latest_judgement_id(database: Database) -> int | None:
    judgement = database.latest_judgement()
    return int(judgement["id"]) if judgement else None


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_formal_pipeline_synthetic_timeline_and_verified_export(
    settings: Settings,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
):
    temp_root = tmp_path_factory.getbasetemp().resolve()
    assert _within(settings.database_path, temp_root)
    assert _within(settings.log_dir, temp_root)
    assert not settings.database_path.exists(), "timeline migration is allowed only on a fresh isolated DB"

    clock = FakeClock(datetime.now(UTC) - timedelta(minutes=1))

    async def scenario() -> None:
        harness = await _start_harness(settings, clock)
        database, pipeline, transport = harness.database, harness.pipeline, harness.transport
        try:
            assert pipeline.is_synthetic is True
            assert harness.model.ledger_attempts_enabled is True
            posted = "2026-10-06T00:00:00Z"
            plan_id = await _process_fixture_post(harness, PLAN_TWEET_ID, PLAN_BODY_V1, posted)
            banked_id = await _process_fixture_post(harness, BANKED_TWEET_ID, BANKED_BODY, posted)
            reply_id = await _process_fixture_reply(harness, posted)
            proxy_event = _record_banked_marker(
                database,
                posted,
                "eventproxy-explicit-fixture",
                source_post_id=banked_id,
                evidence_post_ids=[BANKED_TWEET_ID],
                time_basis="post_time_proxy",
            )
            assert proxy_event["time_basis"] == "post_time_proxy"
            assert proxy_event["occurred_at"] == posted
            assert proxy_event["source_post_id"] == banked_id
            assert proxy_event["provenance"]["is_synthetic"] is True
            assert database.last_full_reset() is None
            proxy_source_truth = [
                row for row in _ledger_rows(database, "truth_revision")
                if row["event_id"] == int(proxy_event["id"])
            ]
            assert len(proxy_source_truth) == 1
            assert proxy_source_truth[0]["revision"] == 1
            assert proxy_source_truth[0]["payload"]["truth_status"] == "SOURCE_EVENT_UNADJUDICATED"
            assert proxy_source_truth[0]["payload"]["source_event_snapshot_ref"]
            assert proxy_source_truth[0]["payload"]["is_synthetic"] is True

            reply_analysis = next(
                item for item in transport.analysis_payloads
                if item["post"]["tweet_id"] == REPLY_TWEET_ID
            )["post"]
            assert reply_analysis["reply_context"]["state"] == "READY"
            assert reply_analysis["reply_context"]["nodes"][0]["author"] == "community_member"
            assert reply_analysis["reply_context"]["nodes"][0]["text"] == "What is the release window?"

            # Move the synthetic wall clock only after all initial inputs and
            # reply-context snapshots have been durably acquired. The cutoff is
            # therefore later than their collected/created timestamps while
            # remaining historical for API validation; monotonic request
            # duration remains independent.
            t0 = datetime.now(UTC) - timedelta(seconds=1)
            clock.current = t0
            selection = {
                "start": clock.text(t0 - timedelta(days=2)),
                "end": clock.text(t0 + timedelta(days=2)),
            }
            freeze_at = clock.text(t0 + timedelta(days=7))

            # A Banked event is inserted while the first Judge request is in flight.
            # Its event time is after request start but before formal output availability.
            event_stamp = t0 + timedelta(minutes=2)
            during_request: dict[str, Any] = {}

            def add_in_flight_event() -> None:
                during_request["event"] = _record_banked_marker(
                    database, clock.text(event_stamp), "in-flight-time-boundary"
                )

            first_forecast_time = clock.text(t0 + timedelta(days=5))
            transport.queue_judge(JudgeAction(
                result=_judge_result(first_forecast_time, reason="Synthetic future plan."),
                before_response=add_in_flight_event,
                advance_after=timedelta(minutes=3),
            ))
            await pipeline.run_judge(as_of=clock.text(t0), data_health="HEALTHY")
            assert "event" in during_request, {
                "queued_judge_actions": len(transport.judge_actions),
                "judge_payload_count": len(transport.judge_payloads),
                "attempts_by_operation": {key: len(value) for key, value in transport.attempt_ids_by_operation.items()},
            }
            assert during_request["event"]["id"]
            assert _latest_judgement_id(database) is not None

            judge_context = transport.judge_payloads[0]["context"]
            judged_reply = next(item for item in judge_context["posts"] if item["tweet_id"] == REPLY_TWEET_ID)
            first_judgement = database.get_judgement(_latest_judgement_id(database))
            assert first_judgement is not None
            assert judged_reply["reply_context"]["nodes"][0]["text"] == "What is the release window?"
            assert first_judgement["raw"]["input_versions"][REPLY_TWEET_ID] == judged_reply["input_hash"]
            assert first_judgement["raw"]["input_snapshot"]["input_versions"][REPLY_TWEET_ID] == judged_reply["input_hash"]
            historical_validation = database.validate_judgement(first_judgement, at=clock.text(t0))
            assert historical_validation["valid"] is True, historical_validation
            radar_api = _read_radar_api(database, settings, tmp_path)
            assert radar_api["judgement_id"] == first_judgement["id"]
            assert radar_api["validation"]["valid"] is False
            assert radar_api["validation"]["reason"] == "INPUT_SNAPSHOT_CHANGED"
            assert radar_api["judgement_state"] == "invalid"
            assert radar_api["display_mode"] == "unavailable"
            assert radar_api["action_level"] == "UNKNOWN"
            assert radar_api["last_known_result"]["action_level"] == first_judgement["action_level"]

            run = _ledger_rows(database, "run_started")[-1]
            assert run["payload"]["is_synthetic"] is True
            first_attempt = next(
                row for row in _ledger_rows(database, "attempt_started") if row["run_id"] == run["run_id"]
            )
            first_attempt_events = _attempt_events(database, first_attempt["attempt_id"])
            committed = next(
                row for row in _ledger_rows(database, "output_committed") if row["run_id"] == run["run_id"]
            )
            observed = next(
                row for row in _ledger_rows(database, "output_observed") if row["run_id"] == run["run_id"]
            )
            assert _datetime(first_attempt["payload"]["attempt_started_at"]) < event_stamp
            assert event_stamp < _datetime(observed["payload"]["observed_at"])
            assert committed["payload"]["output_available_at"] is None
            monotonic_durations = [
                item["payload"]["duration_ms"] for item in first_attempt_events
                if item["payload"].get("event_type") == "response_json_decoded"
            ]
            assert monotonic_durations and 0 <= monotonic_durations[-1] < 30_000
            assert len(transport.judge_attempt_ids) == 1
            assert transport.send_persistence_checks == len(transport.all_attempt_ids)
            assert len(transport.all_attempt_ids) == harness.model.requests_started
            assert len(_ledger_rows(database, "attempt_started")) == harness.model.requests_started
            initial_forecasts = _forecast_chains(database)
            assert all(len(chain) == 1 for chain in initial_forecasts.values())
            for target, chain in initial_forecasts.items():
                assert run['payload']['target_refs'][target]['forecast_id'] == chain[0]['forecast_id']
                assert committed['payload']['target_refs'][target] == run['payload']['target_refs'][target]
                assert committed['payload']['accepted_attempt_id'] == first_attempt['attempt_id']
                assert committed['payload']['target_outputs'][target]['output_revision'] == 1

            # Repeated collector sighting is a duplicate and cannot generate a new forecast.
            repeated = database.upsert_posts_detailed([_post_record(PLAN_TWEET_ID, PLAN_BODY_V1, posted)])
            assert repeated[0]["status"] == "duplicate"
            assert pipeline.enqueue_ingest(repeated) == 0
            assert _forecast_chains(database) == initial_forecasts
            judge_sends_before_cache = len(transport.judge_attempt_ids)
            await pipeline._process_post(plan_id)
            assert len(transport.judge_attempt_ids) == judge_sends_before_cache
            cache_events = [
                row for row in _ledger_rows(database, "attempt_event")
                if row["payload"].get("event_type") == "cache_reused"
                and row["payload"].get("operation") in {"post_analysis", "post_translation"}
            ]
            assert {row["payload"]["operation"] for row in cache_events} == {"post_analysis", "post_translation"}
            assert all(
                row["payload"].get("source_status") == "KNOWN"
                and row["payload"].get("source_run_id")
                and row["payload"].get("source_attempt_id")
                for row in cache_events
            ), "cache reuse must point to real formal processing attempts, not an invented source"
            assert _forecast_chains(database) == initial_forecasts

            # A real body revision is processed by the same production pipeline and
            # yields a distinct semantic forecast revision.
            changed = database.upsert_posts_detailed([_post_record(PLAN_TWEET_ID, PLAN_BODY_V2, posted)])
            assert changed[0]["status"] == "updated" and changed[0]["queue"] is True
            await pipeline._process_post(plan_id)
            plan_v2 = database.get_post(plan_id)
            assert plan_v2 is not None
            database.upsert_content_policy(_allow_policy(PLAN_TWEET_ID, plan_v2["text_hash"], "fixture-v2-a"))
            second_forecast_time = clock.text(t0 + timedelta(days=6))
            transport.queue_judge(JudgeAction(
                result=_judge_result(second_forecast_time, reason="Synthetic revised input forecast.")
            ))
            sends_before_revision = len(transport.judge_attempt_ids)
            await pipeline.run_judge(as_of=clock.text(t0 + timedelta(minutes=4)), data_health="HEALTHY")
            assert len(transport.judge_attempt_ids) == sends_before_revision + 1
            forecasts_after_revision = _forecast_chains(database)
            assert all(len(chain) == 2 for chain in forecasts_after_revision.values())
            latest_forecasts = {target: chain[-1] for target, chain in forecasts_after_revision.items()}
            for target, chain in forecasts_after_revision.items():
                assert chain[0] == initial_forecasts[target][0]
                assert chain[-1]['payload']['semantic_hash'] != chain[0]['payload']['semantic_hash']

            # Same forecast facts at a later as-of with different non-forecast Judge
            # fields remain the same forecast revision.
            output_before_same_facts = database.latest_judgement()
            assert output_before_same_facts is not None
            same_facts_prediction_time = clock.text(t0 + timedelta(days=6, hours=12))
            same_facts_result = _judge_result(
                same_facts_prediction_time,
                reason="Different synthetic explanation and date, same frozen forecast identity.",
            )
            transport.queue_judge(JudgeAction(result=same_facts_result))
            sends_before_same_facts = len(transport.judge_attempt_ids)
            await pipeline.run_judge(as_of=clock.text(t0 + timedelta(minutes=5)), data_health="HEALTHY")
            assert len(transport.judge_attempt_ids) == sends_before_same_facts + 1
            output_after_same_facts = database.latest_judgement()
            assert output_after_same_facts is not None
            assert output_after_same_facts["id"] != output_before_same_facts["id"]
            assert output_after_same_facts["reason_summary"] != output_before_same_facts["reason_summary"]
            assert output_after_same_facts["estimated_start"] != output_before_same_facts["estimated_start"]
            assert _forecast_chains(database) == forecasts_after_revision
            same_fact_outputs = [
                row for row in _ledger_rows(database, "output_committed")
                if row["judgement_id"] in {output_before_same_facts["id"], output_after_same_facts["id"]}
            ]
            assert len(same_fact_outputs) == 2
            assert len({row["judgement_id"] for row in same_fact_outputs}) == 2
            assert len({row["run_id"] for row in same_fact_outputs}) == 2
            for target in PREDICTION_TARGETS:
                assert all(row['payload']['target_refs'][target]['forecast_id'] == latest_forecasts[target]['forecast_id'] for row in same_fact_outputs)
                target_outputs = [row['payload']['target_outputs'][target] for row in same_fact_outputs]
                assert len({item['target_output_id'] for item in target_outputs}) == 2
                assert target_outputs[1]['output_revision'] == target_outputs[0]['output_revision'] + 1
            assert all(row["payload"]["output_id"] for row in same_fact_outputs)
            same_fact_run_ids = {row["run_id"] for row in same_fact_outputs}
            same_fact_runs = [
                row for row in _ledger_rows(database, "run_started")
                if row["run_id"] in same_fact_run_ids
            ]
            assert len(same_fact_runs) == 2
            assert same_fact_runs[0]["payload"]["judgement_as_of"] != same_fact_runs[1]["payload"]["judgement_as_of"]
            for shared_run in same_fact_runs:
                assert len([attempt for attempt in _ledger_rows(database, 'attempt_started') if attempt['run_id'] == shared_run['run_id']]) == 1
                assert set(shared_run['payload']['target_refs']) == set(PREDICTION_TARGETS)

            # Policy version belongs to the frozen input identity even when body
            # bytes are unchanged; it must not be silently absent from the run hash.
            before_policy_run = _ledger_rows(database, "run_started")[-1]["payload"]["semantic_input_hash"]
            plan_v2 = database.get_post(plan_id)
            assert plan_v2 is not None
            database.upsert_content_policy(_allow_policy(PLAN_TWEET_ID, plan_v2["text_hash"], "fixture-v2-b"))
            transport.queue_judge(JudgeAction(result=same_facts_result))
            await pipeline.run_judge(as_of=clock.text(t0 + timedelta(minutes=6)), data_health="HEALTHY")
            after_policy_run = _ledger_rows(database, "run_started")[-1]["payload"]["semantic_input_hash"]
            assert before_policy_run != after_policy_run
            policy_forecasts = _forecast_chains(database)
            assert all(len(chain) == 3 for chain in policy_forecasts.values())
            for target, chain in policy_forecasts.items():
                assert chain[:2] == forecasts_after_revision[target]
                assert chain[-1]['payload']['semantic_hash'] != latest_forecasts[target]['payload']['semantic_hash']

            # A legal UNKNOWN is a successful output with no invented date; the
            # subsequent HTTP failure is a separate failed run, not that output.
            unknown_before = _latest_judgement_id(database)
            transport.queue_judge(JudgeAction(
                result=_judge_result(
                    None,
                    reason="Synthetic fixture has no supported date.",
                    levels=("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN"),
                )
            ))
            await pipeline.run_judge(as_of=clock.text(t0 + timedelta(minutes=7)), data_health="HEALTHY")
            unknown = database.latest_judgement()
            assert unknown is not None and unknown["id"] != unknown_before
            assert unknown["action_level"] == "UNKNOWN"
            assert unknown["estimated_start"] is None and unknown["estimated_end"] is None
            unknown_output_id = int(unknown["id"])

            failed_run_count = len(_ledger_rows(database, "run_started"))
            output_count_before_failure = len(_ledger_rows(database, "output_committed"))
            transport.queue_judge(JudgeAction(status=503))
            transport.queue_judge(JudgeAction(status=503))
            with pytest.raises(DeepSeekError):
                await pipeline.run_judge(as_of=clock.text(t0 + timedelta(minutes=8)), data_health="HEALTHY")
            assert len(_ledger_rows(database, "run_started")) == failed_run_count + 1
            assert len(_ledger_rows(database, "output_committed")) == output_count_before_failure
            assert _latest_judgement_id(database) == unknown_output_id
            failed_run = _ledger_rows(database, "run_started")[-1]["run_id"]
            failed_attempts = [
                row for row in _ledger_rows(database, "attempt_started") if row["run_id"] == failed_run
            ]
            assert len(failed_attempts) == 2
            assert failed_attempts[1]["payload"]["retry_of"] == failed_attempts[0]["attempt_id"]
            assert any(
                event["payload"].get("event_type") == "http_failure"
                and event["payload"].get("failure_terminal") is True
                for event in _attempt_events(database, failed_attempts[0]["attempt_id"])
            )

            # An old allowed policy exists for v2. The new body is therefore
            # quarantined until its own policy is explicitly reviewed. The old
            # in-flight output must be rejected and its audit event must persist.
            database.upsert_content_policy(_allow_policy(PLAN_TWEET_ID, plan_v2["text_hash"], "fixture-v2-canonical"))
            entered, release = asyncio.Event(), asyncio.Event()
            transport.queue_judge(JudgeAction(
                result=_judge_result(clock.text(t0 + timedelta(days=7)), reason="Must be rejected as late."),
                entered=entered,
                release=release,
            ))
            output_count_before_late = len(_ledger_rows(database, "output_committed"))
            latest_before_late = _latest_judgement_id(database)
            late_task = asyncio.create_task(
                pipeline.run_judge(as_of=clock.text(t0 + timedelta(minutes=9)), data_health="HEALTHY")
            )
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                changed_again = database.upsert_posts_detailed([_post_record(PLAN_TWEET_ID, PLAN_BODY_V3, posted)])
                assert changed_again[0]["status"] == "updated"
                assert database.content_policy(plan_id)["policy_status"] == "CONTENT_VERSION_CHANGED_REVIEW_REQUIRED"
                database.contexts.record_observation(
                    _reply_context_node(
                        PARENT_TWEET_ID,
                        "community_member",
                        "A synthetic in-flight parent-context revision.",
                        clock.text(t0 + timedelta(minutes=7)),
                    ),
                    clock.text(t0 + timedelta(minutes=8)),
                )
            finally:
                release.set()
            with pytest.raises(ValueError, match="(?i)(input|snapshot).*(changed|rejected)|late_input_rejected"):
                await late_task
            assert len(_ledger_rows(database, "output_committed")) == output_count_before_late
            assert _latest_judgement_id(database) == latest_before_late
            late_run = _ledger_rows(database, "run_started")[-1]["run_id"]
            late_attempt = next(
                row for row in _ledger_rows(database, "attempt_started") if row["run_id"] == late_run
            )
            late_events = _attempt_events(database, late_attempt["attempt_id"])
            assert any(
                event["payload"].get("event_type") == "late_input_rejected"
                and event["payload"].get("failure_terminal") is True
                for event in late_events
            ), "late_input_rejected must survive the same transaction that rejects the output"

            # Explicitly reviewing the replacement content makes a later version
            # available through the formal pipeline.
            post_v3 = database.get_post(plan_id)
            assert post_v3 is not None
            database.upsert_content_policy(_allow_policy(PLAN_TWEET_ID, post_v3["text_hash"], "fixture-v3-reviewed"))
            await pipeline._process_post(plan_id)
            third_forecast_time = clock.text(t0 + timedelta(days=7))
            transport.queue_judge(JudgeAction(
                result=_judge_result(third_forecast_time, reason="Synthetic normal available output.")
            ))
            await pipeline.run_judge(as_of=clock.text(t0 + timedelta(minutes=10)), data_health="HEALTHY")
            available = database.latest_judgement()
            assert available is not None and database.get_judgement(int(available["id"])) is not None
            available_run = next(
                row for row in reversed(_ledger_rows(database, "run_started"))
                if any(item["run_id"] == row["run_id"] for item in _ledger_rows(database, "output_observed"))
            )
            assert available_run["payload"]["is_synthetic"] is True

            # Online selection has no historical cutoff. A newly valid, fully
            # processed input arriving while the formal request is in flight
            # invalidates that frozen snapshot and cannot publish stale output.
            online_entered, online_release = asyncio.Event(), asyncio.Event()
            transport.queue_judge(JudgeAction(
                result=_judge_result(third_forecast_time, reason="Must reject the stale online snapshot."),
                entered=online_entered,
                release=online_release,
            ))
            online_output_count = len(_ledger_rows(database, "output_committed"))
            online_latest_before = _latest_judgement_id(database)
            online_task = asyncio.create_task(
                pipeline.run_judge(as_of=None, data_health="HEALTHY")
            )
            try:
                await asyncio.wait_for(online_entered.wait(), timeout=5)
                online_post = database.upsert_posts_detailed([_post_record(
                    ONLINE_INPUT_TWEET_ID, ONLINE_INPUT_BODY, posted,
                )])[0]
                assert online_post["status"] == "new"
                await asyncio.wait_for(pipeline._process_post(int(online_post["post_id"])), timeout=10)
                processed_online_post = database.get_post(int(online_post["post_id"]))
                assert processed_online_post is not None
                assert processed_online_post["analysis_status"] == "COMPLETED"
            finally:
                online_release.set()
            with pytest.raises(ValueError, match="(?i)(input|snapshot).*(changed|rejected)|late_input_rejected"):
                await asyncio.wait_for(online_task, timeout=10)
            assert len(_ledger_rows(database, "output_committed")) == online_output_count
            assert _latest_judgement_id(database) == online_latest_before
            online_rejection = next(
                row for row in reversed(_ledger_rows(database, "attempt_event"))
                if row["payload"].get("event_type") == "late_input_rejected"
            )
            online_run = next(
                row for row in _ledger_rows(database, "run_started")
                if row["run_id"] == online_rejection["run_id"]
            )
            assert online_run["payload"]["record_kind"] == "online"
            assert online_run["payload"]["selection_mode"] == "online"
            online_judgement_as_of = online_run["payload"]["judgement_as_of"]
            assert online_judgement_as_of == transport.judge_payloads[-1]["context"]["judged_at"]
            assert _datetime(online_judgement_as_of).utcoffset() == timedelta(0)
            frozen_artifact_ref = online_run["payload"]["input_snapshot_artifact_ref"]
            frozen_payload = PredictionLedger(database)._load_artifact(frozen_artifact_ref["artifact_id"])
            assert ONLINE_INPUT_TWEET_ID not in frozen_payload["input_snapshot"].get("input_versions", {})
            current_context = database.judgement_context(as_of=None)
            database.refresh_input_snapshot(current_context)
            assert ONLINE_INPUT_TWEET_ID in database.input_snapshot(current_context).get("input_versions", {})

            # A later event outside the latest-24 list still receives a trusted,
            # append-only synthetic truth revision and remains export-linked.
            decoy_start = _datetime(proxy_event["occurred_at"]) + timedelta(hours=1)
            for index in range(25):
                _record_banked_marker(
                    database,
                    clock.text(decoy_start + timedelta(minutes=index)),
                    f"outside-24-{index}",
                )
            assert int(proxy_event["id"]) not in {int(item["id"]) for item in database.list_reset_events(24)}
            proxy_before = next(
                row for row in database.list_reset_events(200) if int(row["id"]) == int(proxy_event["id"])
            )
            forecasts_before_truth = [
                (row["forecast_id"], row["revision"], row["payload"]["semantic_hash"])
                for row in _ledger_rows(database, "forecast_version")
            ]
            full_before_truth = database.last_full_reset()
            ledger = PredictionLedger(database)
            # Record the human fixture after the event-selection window closes,
            # but before the review's independent freeze cutoff.
            clock.current = t0 + timedelta(days=3)
            ledger.append_truth(
                int(proxy_event["id"]),
                expected_revision=1,
                facts={
                    "actual_start": "2026-10-06T00:15:00Z",
                    "actual_time_basis": "synthetic_trusted_fixture",
                    "actual_precision": "minute",
                    "truth_status": "fixture_adjudicated",
                    "adjudication_version": "synthetic-truth-v1",
                    "actual_event_type": "SPECIAL_RESET",
                    "special_type": "BANKED",
                    "scope": "banked_only",
                    "execution_stage": "completed",
                    "association_status": "fixture_event_identity",
                },
                evidence_refs=[{
                    "source": "synthetic_test_fixture",
                    "text": "Synthetic trusted truth fixture; not a real-world event claim.",
                    "url": "https://example.invalid/synthetic-truth",
                    "time_precision": "minute",
                }],
                reason="Synthetic test-only adjudication fixture.",
                is_synthetic=True,
            )
            proxy_after = next(
                row for row in database.list_reset_events(200) if int(row["id"]) == int(proxy_event["id"])
            )
            assert proxy_after == proxy_before, "truth append must not rewrite the old Banked event"
            assert full_before_truth is None and database.last_full_reset() is None
            assert [
                (row["forecast_id"], row["revision"], row["payload"]["semantic_hash"])
                for row in _ledger_rows(database, "forecast_version")
            ] == forecasts_before_truth
            proxy_truth_chain = [
                row for row in _ledger_rows(database, "truth_revision")
                if row["event_id"] == int(proxy_event["id"])
            ]
            assert [row["revision"] for row in proxy_truth_chain] == [1, 2]
            assert [row["payload"]["truth_status"] for row in proxy_truth_chain] == [
                "SOURCE_EVENT_UNADJUDICATED", "fixture_adjudicated",
            ]
            assert proxy_truth_chain[-1]["payload"]["is_synthetic"] is True
            assert _datetime(proxy_truth_chain[-1]["recorded_at"]) > _datetime(selection["end"])
            assert _datetime(proxy_truth_chain[-1]["recorded_at"]) <= _datetime(freeze_at)

            # Five-day pruning is exercised only against this test's own log dir.
            old_log = settings.log_dir / "synthetic-old-diagnostic.jsonl"
            fresh_log = settings.log_dir / "synthetic-retained-diagnostic.jsonl"
            settings.log_dir.mkdir(parents=True, exist_ok=True)
            old_log.write_text('{"synthetic":true}\n', encoding="utf-8")
            fresh_log.write_text('{"synthetic":true}\n', encoding="utf-8")
            old_time = time.time() - 6 * 24 * 60 * 60
            os.utime(old_log, (old_time, old_time))
            RuntimeLog(settings.log_dir, retention_days=5, max_bytes=settings.log_max_bytes).write(
                "app", "SYNTHETIC_RETENTION_TEST"
            )
            assert not old_log.exists()
            assert fresh_log.exists()
            assert len(_ledger_rows(database, "forecast_version")) == len(forecasts_before_truth)

            # Failure before durable schema storage must stop before any HTTP send.
            original_put_artifact = PredictionLedger._put_artifact
            schema_failure_seen = False

            def fail_schema_artifact(self, connection, kind, payload):
                nonlocal schema_failure_seen
                if kind == "judge_schema":
                    schema_failure_seen = True
                    raise RuntimeError("synthetic judge schema persistence failure")
                return original_put_artifact(self, connection, kind, payload)

            sends_before_schema_failure = len(transport.judge_attempt_ids)
            all_http_sends_before_schema_failure = transport.send_persistence_checks
            monkeypatch.setattr(PredictionLedger, "_put_artifact", fail_schema_artifact)
            transport.queue_judge(JudgeAction(result=_judge_result(third_forecast_time)))
            with pytest.raises(RuntimeError, match="synthetic judge schema persistence failure"):
                await pipeline.run_judge(as_of=clock.text(t0 + timedelta(minutes=11)), data_health="HEALTHY")
            monkeypatch.setattr(PredictionLedger, "_put_artifact", original_put_artifact)
            assert schema_failure_seen
            assert len(transport.judge_attempt_ids) == sends_before_schema_failure
            assert transport.send_persistence_checks == all_http_sends_before_schema_failure, (
                "schema persistence failure must occur before every HTTP transport send"
            )

            # Read/export selects the full isolated time range. The late rejection,
            # output availability, truth revision and old event dependency must all
            # be linked by the real validator; no validator is patched or bypassed.
            normal_anchor = database.upsert_reset_event({
                "event_type": "FULL_RESET",
                "occurred_at": clock.text(t0),
                "time_basis": "post_time_proxy",
                "scope": "global",
                "execution_stage": "completed",
                "source_post_id": None,
                "evidence_post_ids": [],
                "title": "Synthetic Full anchor for Normal compatibility projection",
                "summary": "Synthetic test-only anchor; not a production event claim.",
                "provenance": {"is_synthetic": True, "source": "pipeline-isolation-fixture"},
            }, is_synthetic=True)
            assert normal_anchor["event_type"] == "FULL_RESET"
            normal_selection = {**selection, "series_id": "normal-weekly-compatibility"}
            with database.connect() as connection:
                normal_before_expiry = read_review(
                    connection, normal_selection, clock.text(t0 + timedelta(days=6)),
                )
            with database.connect() as connection:
                normal_after_expiry = read_review(
                    connection, normal_selection, clock.text(t0 + timedelta(days=9)),
                )
            normal_forecast = next(
                item for item in normal_before_expiry["forecasts"]
                if item.get("target") == "NORMAL_WEEKLY"
            )
            expired_normal_forecast = next(
                item for item in normal_after_expiry["forecasts"]
                if item.get("target") == "NORMAL_WEEKLY"
            )
            assert normal_forecast["source_kind"] == "normal_baseline_compatibility_view"
            assert normal_forecast["version_history_complete"] is False
            assert normal_forecast["precision"] == "proxy"
            assert normal_forecast["predicted_start"] == clock.text(t0 + timedelta(days=7))
            assert normal_forecast["status"] == "baseline"
            assert expired_normal_forecast["predicted_start"] == normal_forecast["predicted_start"]
            assert expired_normal_forecast["status"] == "expired"
            for normal_review in (normal_before_expiry, normal_after_expiry):
                assert normal_review["metadata"]["capabilities"]["normal_baseline"] == "COMPATIBILITY_VIEW_ONLY"
                assert normal_review["metadata"]["capabilities"]["normal_baseline_history"] == "NOT_BACKFILLED"
                assert "normal_baseline_compatibility_view" in normal_review["metadata"]["source_modes"]
            with database.connect() as connection:
                preview = preview_review(connection, selection, freeze_at)
            assert preview["ready"] is True
            with database.connect() as connection:
                before_post_freeze_append = read_review(connection, selection, freeze_at)
            before_frozen_truths = [
                item for item in before_post_freeze_append["truth_revisions"]
                if str(item.get("event_id")) == str(proxy_event["id"])
            ]
            assert {item.get("truth_revision") for item in before_frozen_truths} == {1, 2}
            clock.current = t0 + timedelta(days=8)
            ledger.append_truth(
                int(proxy_event["id"]),
                expected_revision=2,
                facts={
                    "actual_start": "2026-10-06T00:16:00Z",
                    "actual_time_basis": "synthetic_trusted_fixture",
                    "actual_precision": "minute",
                    "truth_status": "fixture_after_freeze",
                    "adjudication_version": "synthetic-truth-after-freeze-v1",
                    "actual_event_type": "SPECIAL_RESET",
                    "special_type": "BANKED",
                    "scope": "banked_only",
                    "execution_stage": "completed",
                    "association_status": "fixture_event_identity",
                },
                evidence_refs=[{
                    "source": "synthetic_test_fixture",
                    "text": "Synthetic truth recorded after the frozen review cutoff.",
                    "url": "https://example.invalid/synthetic-truth-after-freeze",
                    "time_precision": "minute",
                }],
                reason="Synthetic test-only post-freeze adjudication fixture.",
                is_synthetic=True,
            )
            proxy_truth_chain_after_freeze = [
                row for row in _ledger_rows(database, "truth_revision")
                if row["event_id"] == int(proxy_event["id"])
            ]
            assert [row["revision"] for row in proxy_truth_chain_after_freeze] == [1, 2, 3]
            assert _datetime(proxy_truth_chain_after_freeze[-1]["recorded_at"]) > _datetime(freeze_at)
            with database.connect() as connection:
                after_post_freeze_append = read_review(connection, selection, freeze_at)
            after_frozen_truths = [
                item for item in after_post_freeze_append["truth_revisions"]
                if str(item.get("event_id")) == str(proxy_event["id"])
            ]
            assert {item.get("truth_revision") for item in after_frozen_truths} == {1, 2}
            staging = tmp_path / "review-staging"
            staging.mkdir()
            package = tmp_path / "synthetic-prediction-review.zip"
            with database.connect() as connection:
                exported = export_review(
                    connection,
                    selection,
                    freeze_at,
                    package,
                    staging,
                    generated_at=clock.text(),
                )
            verified = verify_review(package)
            assert exported["verification"]["valid"] is True
            assert verified["valid"] is True and verified["references_verified"] is True
            assert exported["manifest"]["capabilities"]["normal_baseline"] == "COMPATIBILITY_VIEW_ONLY"
            assert exported["manifest"]["capabilities"]["normal_baseline_history"] == "NOT_BACKFILLED"
            assert "normal_baseline_compatibility_view" in exported["manifest"]["source_modes"]
            with zipfile.ZipFile(package) as archive:
                attempts = [
                    json.loads(line)
                    for line in archive.read("attempts.jsonl").decode("utf-8").splitlines()
                ]
                outputs = [
                    json.loads(line)
                    for line in archive.read("outputs.jsonl").decode("utf-8").splitlines()
                ]
                forecasts = [
                    json.loads(line)
                    for line in archive.read("forecasts.jsonl").decode("utf-8").splitlines()
                ]
                truths = [
                    json.loads(line)
                    for line in archive.read("truth-revisions.jsonl").decode("utf-8").splitlines()
                ]
                public_evidence = [
                    json.loads(line)
                    for line in archive.read("public-evidence.jsonl").decode("utf-8").splitlines()
                ]
            packaged_events = [event for item in attempts for event in item.get("events", [])]
            packaged_event_types = {event.get("event_type") for event in packaged_events}
            assert {
                "late_input_rejected", "cache_reused", "response_json_decoded", "response_model_reported",
            } <= packaged_event_types
            late_rejections = [
                event for event in packaged_events if event.get("event_type") == "late_input_rejected"
            ]
            assert len(late_rejections) == 2
            for event in late_rejections:
                assert event.get("status") == "late_input_rejected"
                assert event.get("failure_terminal") is True
                assert event.get("publication_status") == "rejected"
                assert "output_available_at" in event and event["output_available_at"] is None
                assert isinstance(event.get("structured_output"), dict)
                assert "action_level" in event["structured_output"]
                delta = event.get("input_version_delta")
                assert isinstance(delta, list) and delta
                assert any(item.get("class") == "input_version" for item in delta)
                assert all(
                    {"class", "entity", "old_hash", "new_hash"} <= set(item)
                    for item in delta
                )
            modern_outputs = [item for item in outputs if not item.get("legacy_judgement_id")]
            assert modern_outputs and all(item.get("is_synthetic") is True for item in modern_outputs)
            modern_forecasts = [
                item for item in forecasts
                if item.get("source_kind") != "normal_baseline_compatibility_view"
            ]
            assert modern_forecasts and all(item.get("is_synthetic") is True for item in modern_forecasts)
            first_output = next(item for item in modern_outputs if item.get("run_id") == run["run_id"])
            assert _datetime(first_output["output_available_at"]) > event_stamp
            linked_truths = [item for item in truths if str(item.get("event_id")) == str(proxy_event["id"])]
            assert len(linked_truths) == 2, "export must preserve both source snapshot and adjudicated revisions"
            assert [item.get("truth_revision") for item in linked_truths] == [1, 2]
            assert all(item.get("is_synthetic") is True for item in linked_truths)
            assert [item.get("truth_status") for item in linked_truths] == [
                "SOURCE_EVENT_UNADJUDICATED", "fixture_adjudicated",
            ], "legacy adapters must not duplicate or erase either modern truth revision"
            evidence_refs = linked_truths[-1].get("references", {}).get("artifacts", [])
            included_evidence_ids = {
                item["id"] for item in evidence_refs
                if item.get("target") == "public_evidence" and item.get("status") == "included"
            }
            assert included_evidence_ids
            assert any(item.get("id") in included_evidence_ids for item in public_evidence)
            supplier_model_events = [
                event
                for attempt in attempts
                for event in attempt.get("events", [])
                if event.get("event_type") == "response_model_reported"
            ]
            assert supplier_model_events
            assert all(
                event.get("reported_model") == "synthetic-supplier-reported-model"
                and event.get("reported_model_source") == "deepseek_api_response.model"
                for event in supplier_model_events
            ), "supplier-reported model identity must remain distinct from the declared request model"
            declared_models = {
                row["payload"].get("declared_model")
                for row in _ledger_rows(database, "attempt_started")
            }
            assert declared_models == {harness.model.model}
            source_modes = exported["manifest"]["source_modes"]
            assert "prediction_ledger_readonly" in source_modes
            provenance = exported["manifest"]["synthetic_provenance"]
            assert provenance["status"] == "SYNTHETIC"
            assert provenance["counts"]["declared_synthetic"] > 0
            assert provenance["counts"]["declared_real"] == 0
            assert provenance["counts"]["legacy_undeclared"] == 0
            assert provenance["counts"]["undeclared"] == 0, (
                "fixture provenance must reach every exported dependency"
            )
            assert all(
                "reported_model" not in item and "reported_model_source" not in item
                for item in modern_outputs + modern_forecasts
            ), "supplier-reported model identity must remain attempt provenance, not business output"
            assert banked_id != plan_id
        finally:
            await harness.close()

    with _fake_clock(monkeypatch, clock):
        asyncio.run(asyncio.wait_for(scenario(), timeout=90))


def test_transport_failure_modes_recovery_and_commit_observation_gap(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    assert not settings.database_path.exists()
    clock = FakeClock(datetime.now(UTC) - timedelta(minutes=1))

    async def scenario() -> None:
        harness = await _start_harness(settings, clock)
        database, pipeline, transport = harness.database, harness.pipeline, harness.transport
        try:
            posted = "2026-10-06T00:00:00Z"
            plan_id = await _process_fixture_post(
                harness, PLAN_TWEET_ID, PLAN_BODY_V1, posted
            )
            reply_id = await _process_fixture_reply(harness, posted)
            # Processing timestamps use the earlier synthetic clock value;
            # establish the as-of only after the input is durable.
            clock.current = datetime.now(UTC) - timedelta(seconds=1)
            baseline = clock.text(clock.current + timedelta(days=5))
            transport.queue_judge(JudgeAction(result=_judge_result(baseline, reason="Synthetic baseline.")))
            await pipeline.run_judge(as_of=clock.text(clock.current), data_health="HEALTHY")
            baseline_judgement = database.latest_judgement()
            assert baseline_judgement is not None
            baseline_id = int(baseline_judgement["id"])
            baseline_payload = transport.judge_payloads[-1]["context"]
            baseline_reply = next(
                item for item in baseline_payload["posts"] if item["tweet_id"] == REPLY_TWEET_ID
            )
            assert baseline_reply["reply_context"]["state"] == "READY"
            assert baseline_reply["reply_context"]["nodes"][0]["text"] == "What is the release window?"
            assert baseline_judgement["raw"]["input_versions"][REPLY_TWEET_ID] == baseline_reply["input_hash"]
            assert database.get_post(reply_id)["analysis_status"] == "COMPLETED"
            baseline_api = _read_radar_api(database, settings, tmp_path)
            assert baseline_api["judgement_id"] == baseline_id
            assert baseline_api["validation"]["valid"] is True, baseline_api["validation"]
            assert baseline_api["display_mode"] == "current"
            assert baseline_api["action_level"] == baseline_judgement["action_level"]
            assert baseline_api["last_known_result"]["action_level"] == baseline_judgement["action_level"]

            # Malformed JSON and timeout each create a separate persisted attempt
            # before the fake transport is called, then succeed on the real retry path.
            for failure in (
                JudgeAction(invalid_json=True),
                JudgeAction(timeout=True),
            ):
                transport.queue_judge(failure)
                transport.queue_judge(JudgeAction(
                    result=_judge_result(baseline, reason="Synthetic retry success.")
                ))
                await pipeline.run_judge(as_of=clock.text(clock.current + timedelta(minutes=1)), data_health="HEALTHY")

            retry_runs = _ledger_rows(database, "run_started")[-2:]
            for run in retry_runs:
                attempts = [row for row in _ledger_rows(database, "attempt_started") if row["run_id"] == run["run_id"]]
                assert len(attempts) == 2
                assert attempts[1]["payload"]["retry_of"] == attempts[0]["attempt_id"]
                events = _attempt_events(database, attempts[0]["attempt_id"])
                assert any(
                    item["payload"].get("event_type") in {"parse_failure", "timeout"}
                    and item["payload"].get("failure_terminal") is True
                    and item["payload"].get("attempt_finished_at")
                    for item in events
                )
            assert transport.send_persistence_checks == len(transport.all_attempt_ids)
            assert len(transport.all_attempt_ids) == harness.model.requests_started

            # Cancellation is also terminal and cannot overwrite the previous success.
            entered, release = asyncio.Event(), asyncio.Event()
            transport.queue_judge(JudgeAction(
                result=_judge_result(baseline), entered=entered, release=release
            ))
            cancel_task = asyncio.create_task(
                pipeline.run_judge(as_of=clock.text(clock.current + timedelta(minutes=2)), data_health="HEALTHY")
            )
            await asyncio.wait_for(entered.wait(), timeout=5)
            cancel_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(cancel_task, timeout=5)
            assert database.latest_judgement() is not None
            assert int(database.latest_judgement()["id"]) != baseline_id
            cancelled_attempt_id = transport.judge_attempt_ids[-1]
            assert any(
                item["payload"].get("event_type") == "cancelled"
                and item["payload"].get("failure_terminal") is True
                and item["payload"].get("actual_finished_at", item["payload"].get("attempt_finished_at"))
                for item in _attempt_events(database, cancelled_attempt_id)
            )
            release.set()

            # A failed formal getter after commit leaves an associated output with
            # unknown availability time, rather than inventing the commit time.
            original_get = database.get_judgement
            fail_observation = True

            def fail_first_observation(judgement_id: int):
                nonlocal fail_observation
                if fail_observation:
                    fail_observation = False
                    raise RuntimeError("synthetic formal getter observation failure")
                return original_get(judgement_id)

            monkeypatch.setattr(database, "get_judgement", fail_first_observation)
            output_count = len(_ledger_rows(database, "output_committed"))
            sends_before_observation_failure = len(transport.judge_attempt_ids)
            transport.queue_judge(JudgeAction(
                result=_judge_result(baseline, reason="Committed, observation deliberately unavailable.")
            ))
            await pipeline.run_judge(as_of=clock.text(clock.current + timedelta(minutes=3)), data_health="HEALTHY")
            monkeypatch.setattr(database, "get_judgement", original_get)
            committed_rows = _ledger_rows(database, "output_committed")
            assert len(committed_rows) == output_count + 1
            uncertain = committed_rows[-1]
            assert uncertain["run_id"] and uncertain["attempt_id"] and uncertain["judgement_id"]
            assert uncertain["payload"]["output_available_at"] is None
            assert fail_observation is False
            assert database.get_judgement(int(uncertain["judgement_id"])) is not None
            assert len(transport.judge_attempt_ids) == sends_before_observation_failure + 1
            assert not any(
                item["run_id"] == uncertain["run_id"] for item in _ledger_rows(database, "output_observed")
            )
            observation_failure = next(
                row for row in _ledger_rows(database, "attempt_event")
                if row["run_id"] == uncertain["run_id"]
                and row["payload"].get("event_type") == "output_observation_failed"
            )
            assert observation_failure["payload"]["reason_code"] == "FORMAL_GETTER_FAILURE"
            assert observation_failure["payload"]["error_type"] == "RuntimeError"
            assert observation_failure["payload"]["output_available_at"] is None
            visible_pipeline_state = database.get_state("pipeline")
            assert visible_pipeline_state["status"] == "ready"
            assert visible_pipeline_state["output_available_at"] is None
            assert visible_pipeline_state["output_observation_error"] == "RuntimeError"

            # Owner-aware recovery preserves a proven-alive owner and only marks
            # the dead owner's unterminated attempt as end-time unknown.
            runtime_rows = _ledger_rows(database, "runtime_identity")
            runtime_id = runtime_rows[-1]["payload"]["runtime_id"]
            ledger = PredictionLedger(database, owner={"runtime_id": runtime_id})
            frozen = {
                "input_cutoff_at": clock.text(),
                "judgement_as_of": clock.text(),
                "input_snapshot": {"fixture": "synthetic-recovery-only"},
                "forecast": {
                    "target": "EXTRA_FULL",
                    "scope": {"value": "global", "certainty": "fixture"},
                    "question": "synthetic_recovery_fixture",
                },
            }
            alive_run = ledger.begin_run(
                frozen, "radar_judge", runtime_id, "synthetic_recovery", "replay", is_synthetic=True
            )
            alive_attempt = ledger.begin_send(
                alive_run.run_id,
                {"stage": "radar_judge", "request_hash": "synthetic-alive-owner"},
                owner={"runtime_id": runtime_id, "pid": os.getpid()},
            )
            dead_run = ledger.begin_run(
                frozen, "radar_judge", "synthetic-dead-runtime", "synthetic_recovery", "replay", is_synthetic=True
            )
            dead_attempt = ledger.begin_send(
                dead_run.run_id,
                {"stage": "radar_judge", "request_hash": "synthetic-dead-owner"},
                owner={"runtime_id": "synthetic-dead-runtime", "pid": 2_147_483_647},
            )
            recovered = ledger.recover_incomplete(current_runtime_id=runtime_id)
            assert len(recovered) == 1
            recovery_rows = [
                row for row in _ledger_rows(database, "recovery_observed")
                if row["attempt_id"] in {alive_attempt.attempt_id, dead_attempt.attempt_id}
            ]
            assert [row["attempt_id"] for row in recovery_rows] == [dead_attempt.attempt_id]
            recovery_payload = recovery_rows[0]["payload"]
            assert recovery_payload["terminal_status"] == "UNKNOWN"
            assert recovery_payload["actual_finished_at"] is None
            assert recovery_rows[0]["occurred_at"] is None
            assert ledger.recover_incomplete(current_runtime_id=runtime_id) == []
            assert not any(
                row["attempt_id"] == alive_attempt.attempt_id for row in _ledger_rows(database, "recovery_observed")
            )

            # The synthetic post itself remains in the fresh test database only.
            assert database.get_post(plan_id)["tweet_id"] == PLAN_TWEET_ID
        finally:
            await harness.close()

    with _fake_clock(monkeypatch, clock):
        asyncio.run(asyncio.wait_for(scenario(), timeout=90))


def test_fake_clock_is_restored_when_a_fixture_assertion_fails(monkeypatch):
    import app.prediction_ledger as ledger_module
    import app.deepseek as deepseek_module
    import app.pipeline as pipeline_module
    import app.db as db_module
    import app.reply_context as context_module
    originals = [(module, name, getattr(module, name)) for module, name in (
        (ledger_module, 'utc_text'), (deepseek_module, 'utc_text'), (pipeline_module, 'utc_text'),
        (db_module, 'utc_now'), (context_module, 'now'))]
    clock = FakeClock(datetime(2099, 1, 1, tzinfo=UTC))
    with pytest.raises(AssertionError, match='intentional fixture abort'):
        with _fake_clock(monkeypatch, clock):
            assert all(getattr(module, name)() == clock.text() for module, name, _ in originals)
            raise AssertionError('intentional fixture abort')
    assert all(getattr(module, name) is original for module, name, original in originals)


def test_legacy_partial_judgement_body_is_placeholder_not_proof(
    settings: Settings,
    tmp_path_factory: pytest.TempPathFactory,
):
    temp_root = tmp_path_factory.getbasetemp().resolve()
    assert _within(settings.database_path, temp_root)
    assert not settings.database_path.exists()
    database = Database(settings.database_path)
    database.initialize()
    tweet_id = "900000000000000199"
    post = database.upsert_posts_detailed([_post_record(
        tweet_id, "Synthetic legacy body deliberately not archived with this judgement.", "2099-01-01T00:00:00Z"
    )])[0]
    database.add_judgement({
        "created_at": "2099-01-01T01:00:00Z",
        "action_level": "GREEN",
        "horizon_24h": "GREEN",
        "horizon_48h": "YELLOW",
        "horizon_72h": "ORANGE",
        "data_health": "HEALTHY",
        "reason_summary": "Synthetic legacy compatibility fixture.",
        "evidence_post_ids": [tweet_id],
        "special_event_ids": [],
        "model": "synthetic-legacy-model",
        "prompt_version": "synthetic-legacy-prompt",
        "valid_until": "2099-01-01T03:00:00Z",
        "status": "COMPLETED",
        "raw": {
            "input_post_ids": [tweet_id],
            "input_versions": {tweet_id: "a" * 64},
            # Deliberately no raw body or exact input snapshot.
        },
    })
    assert post["status"] == "new"

    review = None
    with database.connect() as connection:
        review = read_review(
            connection,
            {"start": "2099-01-01T00:00:00Z", "end": "2099-01-02T00:00:00Z"},
            "2099-01-02T00:00:00Z",
        )
    placeholders = [item for item in review["public_evidence"] if item.get("placeholder")]
    assert placeholders
    assert all(item.get("text") is None for item in placeholders)
    assert any(
        item.get("omission_reason") == "exact_historical_input_body_unavailable"
        for item in placeholders
    )
    legacy_outputs = [item for item in review["outputs"] if item.get("legacy_judgement_id")]
    assert len(legacy_outputs) == 1
    assert legacy_outputs[0]["output_available_at"] is None
    assert legacy_outputs[0]["time_gap_reason"] == "legacy_attempt_and_output_available_times_not_recorded"
    assert legacy_outputs[0]["forecast_ref"]["status"] == "missing"
