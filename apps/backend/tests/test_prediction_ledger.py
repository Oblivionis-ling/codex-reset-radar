from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from copy import deepcopy

import httpx
import pytest

from app.config import REPOSITORY_ROOT
from app.db import Database, utc_now
from app.deepseek import DeepSeekClient, DeepSeekError, build_request_payload
from app.intelligence import judge
from app.logging_runtime import RuntimeLog
from app.pipeline import IntelligencePipeline
from app.prediction_ledger import (
    LateInputRejected,
    PredictionLedger,
    active_attempt_tracker,
    AttemptTracker,
)
from app.review_common import canonical_bytes, sha256_json, utc_text
from app.review_reader import read_review


def _database(tmp_path: Path) -> tuple[Database, dict]:
    database = Database(tmp_path / "prediction-ledger-empty.sqlite")
    database.initialize()
    inserted = database.upsert_posts_detailed([{
        "tweet_id": "990000000000000101",
        "text": "Synthetic ledger test body; no network or provider call.",
        "posted_at": "2026-10-06T12:00:00Z",
        "source": "prediction-ledger-test",
    }])[0]
    analysis = {
        "category": "other",
        "summary": "Offline test analysis.",
        "context_sufficient": True,
        "_input_hash": inserted["content_hash"],
        "_text_hash": inserted["content_hash"],
        "_analysed_at": utc_now(),
    }
    database.save_analysis(
        inserted["post_id"], inserted["content_hash"], "offline-test",
        "offline-analysis-v1", analysis,
    )
    return database, inserted


def _frozen_input(database: Database, *, as_of: str | None = None) -> dict:
    context = database.judgement_context(as_of=as_of)
    context["pending_inputs"] = []
    database.refresh_input_snapshot(context)
    instant = as_of or utc_text()
    context["judged_at"] = instant
    context["data_health"] = "UNKNOWN"
    context["pending_inputs"] = []
    return {
        "forecast": {
            "target": "EXTRA_FULL",
            "scope": {"value": "unknown", "certainty": "not_established_by_ledger"},
            "question": "next_full_reset_start",
            "method": "model_inference",
            "basis": "frozen_judge_input",
        },
        "input_snapshot": database.input_snapshot(context),
        "input_cutoff_at": instant,
        "judgement_as_of": as_of,
        "selection_mode": "replay" if as_of is not None else "online",
        "context": context,
        "policy_versions": context.get("policy_versions") or {},
        "public_prompt": {"system": "offline test prompt", "user_prefix": "offline test prefix"},
        "judge_schema": {"action_level": "GREEN|YELLOW|ORANGE|RED|UNKNOWN"},
        "data_health": "UNKNOWN",
        "pending_inputs": [],
    }


def _start_run(database: Database, ledger: PredictionLedger, *, as_of: str | None = None):
    instant = as_of or utc_text()
    run = ledger.begin_run(
        _frozen_input(database, as_of=as_of),
        stage="radar_judge", runtime_id="offline-runtime",
        trigger="focused_test", record_kind="replay" if as_of is not None else "online", is_synthetic=True,
    )
    tracker = AttemptTracker(ledger, run.run_id, {
        "stage": "radar_judge",
        "judgement_as_of": instant,
        "input_frame_artifact_ref": run.input_frame_artifact_ref,
        "prompt_artifact_ref": run.prompt_artifact_ref,
        "schema_artifact_ref": run.schema_artifact_ref,
    }, {"runtime_id": "offline-runtime", "pid": 1, "platform": "test"})
    return run, tracker


def _result(level: str = "UNKNOWN", *, evidence: list[str] | None = None) -> dict:
    return {
        "created_at": utc_now(),
        "action_level": level,
        "horizon_24h": level,
        "horizon_48h": level,
        "horizon_72h": level,
        "data_health": "UNKNOWN",
        "reason_summary": "Offline synthetic ledger result.",
        "evidence_post_ids": list(evidence or []),
        "special_event_ids": [],
        "model": "offline-test-model",
        "prompt_version": "offline-test-prompt-v1",
        "estimated_start": None,
        "estimated_end": None,
        "estimate_basis": "No synthetic time estimate.",
        "valid_until": utc_now(),
        "raw": {"offline_fixture": True},
        "predictions": _unknown_targets(),
    }


def _unknown_targets():
    return {target: {
        "target": target, "status": "UNKNOWN", "method": "model_inference", "scope": "unknown",
        "predicted_start": None, "predicted_end": None, "prediction_form": "unknown",
        "source_timezone": None, "precision": "unknown", "time_basis": "unknown", "expression": None,
        "relative_anchor_at": None, "reason": "Explicit offline fixture has no future time evidence.",
        "unresolved_reason": "NO_INDEPENDENT_TIME_EVIDENCE", "evidence_post_ids": [], "evidence_refs": [], "lifecycle": "unknown",
    } for target in ("EXTRA_FULL", "BANKED")}


def _records(database: Database, kind: str) -> list[dict]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM prediction_ledger WHERE kind=? ORDER BY seq", (kind,),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        output.append(item)
    return output


def test_unknown_outputs_share_fact_forecast_but_each_run_and_output_persist(tmp_path):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    as_of_a = "2026-10-07T01:00:00Z"
    as_of_b = "2026-10-07T02:00:00Z"
    run_a, tracker_a = _start_run(database, ledger, as_of=as_of_a)
    run_b, tracker_b = _start_run(database, ledger, as_of=as_of_b)
    assert run_a.forecast_id == run_b.forecast_id
    assert run_a.revision == run_b.revision == 1
    assert run_a.semantic_hash == run_b.semantic_hash

    changed_request_identity = _frozen_input(database, as_of="2026-10-07T03:00:00Z")
    changed_request_identity["public_prompt"] = {"system": "different static prompt", "prompt_version": "other"}
    changed_request_identity["judge_schema"] = {"action_level": "different schema"}
    run_c = ledger.begin_run(
        changed_request_identity, "radar_judge", "offline-runtime", "focused_test", "replay", is_synthetic=True,
    )
    assert run_c.forecast_id == run_a.forecast_id
    changed_policy = _frozen_input(database, as_of="2026-10-07T04:00:00Z")
    changed_policy["policy_versions"] = {"fixture": {"policy_version": "policy-v2"}}
    run_d = ledger.begin_run(
        changed_policy, "radar_judge", "offline-runtime", "focused_test", "replay", is_synthetic=True,
    )
    assert run_d.forecast_id != run_a.forecast_id
    forecast_payload = _records(database, "forecast_version")[0]["payload"]
    assert isinstance(forecast_payload["facts_digest"], str) and len(forecast_payload["facts_digest"]) == 64
    assert "facts" not in forecast_payload
    assert "public_prompt_hash" not in forecast_payload
    assert "judge_schema_hash" not in forecast_payload

    body_a = build_request_payload("offline-model", "offline test prompt", "actual user message A")
    body_b = build_request_payload("offline-model", "offline test prompt", "actual user message B")
    tracker_a.prepare_request(body_a)
    tracker_b.prepare_request(body_b)
    attempt_a = tracker_a.begin_attempt()
    attempt_b = tracker_b.begin_attempt()
    assert attempt_a.request_hash == sha256_json(body_a)
    assert attempt_b.request_hash == sha256_json(body_b)
    assert attempt_a.request_hash != attempt_b.request_hash

    output_a = ledger.commit_judge(run_a.run_id, attempt_a.attempt_id, _result("UNKNOWN"))
    # The atomic result is visible before observation; availability remains pending.
    assert database.get_judgement(output_a.judgement_id)["action_level"] == "UNKNOWN"
    committed = _records(database, "output_committed")[0]
    assert committed["payload"]["output_available_at"] is None
    assert _records(database, "output_observed") == []
    observed = ledger.observe_output(output_a)
    assert observed["source"] == "formal_read_post_commit_upper_bound"
    assert _records(database, "output_observed")[0]["payload"]["observed_at"] == observed["observed_at"]

    output_b = ledger.commit_judge(run_b.run_id, attempt_b.attempt_id, _result("GREEN"))
    ledger.observe_output(output_b)
    assert output_a.forecast_id == output_b.forecast_id
    assert output_a.judgement_id != output_b.judgement_id
    assert len(_records(database, "forecast_version")) == 2
    assert len(_records(database, "run_started")) == 4
    assert len(_records(database, "attempt_started")) == 2
    assert len(_records(database, "output_committed")) == 2
    assert len(_records(database, "output_observed")) == 2

    schema_ref = committed["payload"]["schema"]["schema_artifact_ref"]
    assert schema_ref == run_a.schema_artifact_ref
    with database.connect() as connection:
        descriptor_rows = connection.execute(
            "SELECT payload_json FROM prediction_artifacts WHERE kind='request_descriptor'"
        ).fetchall()
    descriptors = [json.loads(row[0]) for row in descriptor_rows]
    assert all("messages" not in item and "actual user message" not in json.dumps(item) for item in descriptors)


def test_local_analysis_timestamp_keeps_one_forecast_version_but_preserves_runs_and_outputs(tmp_path):
    facts = PredictionLedger._semantic_facts({
        "posted_at": "2026-10-06T12:00:00Z",
        "occurred_at": "2026-10-06T13:00:00Z",
        "_analysed_at": "2026-10-06T14:00:00Z",
    })
    assert facts == {
        "posted_at": "2026-10-06T12:00:00Z",
        "occurred_at": "2026-10-06T13:00:00Z",
    }
    database, post = _database(tmp_path)
    ledger = PredictionLedger(database)
    run_refs = []
    outputs = []
    request_hashes = []
    for stamp, level in (("2026-10-06T12:01:00Z", "UNKNOWN"), ("2026-10-06T12:02:00Z", "GREEN")):
        database.save_analysis(
            post["post_id"], post["content_hash"], "offline-test", "offline-analysis-v1",
            {
                "category": "other", "summary": "Offline test analysis.",
                "context_sufficient": True, "_input_hash": post["content_hash"],
                "_text_hash": post["content_hash"], "_analysed_at": stamp,
            },
        )
        run, tracker = _start_run(database, ledger)
        request = build_request_payload("offline-model", "same system", f"request with local analysis timestamp {stamp}")
        tracker.prepare_request(request)
        attempt = tracker.begin_attempt()
        output = ledger.commit_judge(run.run_id, attempt.attempt_id, _result(level))
        ledger.observe_output(output)
        run_refs.append(run)
        outputs.append(output)
        request_hashes.append(attempt.request_hash)

    assert run_refs[0].input_hash != run_refs[1].input_hash
    assert run_refs[0].forecast_id == run_refs[1].forecast_id
    assert run_refs[0].semantic_hash == run_refs[1].semantic_hash
    assert request_hashes[0] != request_hashes[1]
    assert outputs[0].judgement_id != outputs[1].judgement_id
    assert len(_records(database, "run_started")) == 2
    assert len(_records(database, "attempt_started")) == 2
    assert len(_records(database, "output_committed")) == 2
    assert len(_records(database, "output_observed")) == 2
    assert len(_records(database, "forecast_version")) == 1


def test_late_input_rejection_is_committed_and_never_inserts_judge(tmp_path, monkeypatch):
    database, post = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, tracker = _start_run(database, ledger)
    tracker.prepare_request(build_request_payload("offline-model", "system", "user"))
    attempt = tracker.begin_attempt()
    with database.connect() as connection:
        connection.execute(
            "UPDATE tibo_posts SET text_hash=? WHERE id=?",
            ("f" * 64, post["post_id"]),
        )
    import app.prediction_ledger as ledger_module

    original_utc_text = ledger_module.utc_text
    monkeypatch.setattr(
        ledger_module, "utc_text",
        lambda value=None: "2000-01-01T00:00:00Z" if value is None else original_utc_text(value),
    )
    rejected_result = _result("UNKNOWN")
    with pytest.raises(LateInputRejected):
        ledger.commit_judge(run.run_id, attempt.attempt_id, rejected_result)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM radar_judgements").fetchone()[0] == 0
    events = _records(database, "attempt_event")
    assert [item["payload"]["event_type"] for item in events] == ["late_input_rejected"]
    rejection = events[0]["payload"]
    assert rejection["failure_terminal"] is True
    assert rejection["structured_output"] == PredictionLedger._structured_output(rejected_result)
    assert rejection["output_available_at"] is None
    assert rejection["publication_status"] == "rejected"
    assert rejection["clock_anomaly"] == "wall_clock_reversed"
    assert rejection["time_limitation"] == "timestamps_retained_without_ordering"
    assert any(
        item["class"] == "input_version" and item["entity"] == post["tweet_id"]
        and item["old_hash"] == post["content_hash"] and item["new_hash"] is None
        for item in rejection["input_version_delta"]
    )
    assert ledger.attempt_is_terminal(run.run_id, attempt.attempt_id)


def test_commit_revalidates_original_online_or_replay_selection_and_online_pending_inputs(tmp_path, monkeypatch):
    online_db, _ = _database(tmp_path / "online")
    online_ledger = PredictionLedger(online_db)
    online_run, online_tracker = _start_run(online_db, online_ledger)
    online_tracker.prepare_request(build_request_payload("offline-model", "system", "user"))
    online_attempt = online_tracker.begin_attempt()
    online_payload = _records(online_db, "run_started")[0]["payload"]
    assert online_payload["selection_mode"] == "online"
    calls = []
    original_context = online_db.judgement_context

    def online_context(*, as_of=None, **kwargs):
        calls.append(as_of)
        return original_context(as_of=as_of, **kwargs)

    monkeypatch.setattr(online_db, "judgement_context", online_context)
    monkeypatch.setattr(
        online_db, "judge_pending_inputs",
        lambda **_kwargs: [{"post_id": 999, "status": "PENDING", "input_hash": "new-version"}],
    )
    with pytest.raises(LateInputRejected):
        online_ledger.commit_judge(online_run.run_id, online_attempt.attempt_id, _result())
    assert calls == [None]
    assert _records(online_db, "output_committed") == []
    pending_rejection = _records(online_db, "attempt_event")[-1]["payload"]
    assert pending_rejection["event_type"] == "late_input_rejected"
    assert any(
        item["class"] == "pending_input" and item["entity"] == "999"
        and item["old_hash"] is None and item["new_hash"] == sha256_json(
            {"post_id": 999, "status": "PENDING", "input_hash": "new-version"}
        )
        for item in pending_rejection["input_version_delta"]
    )

    replay_db, _ = _database(tmp_path / "replay")
    replay_ledger = PredictionLedger(replay_db)
    cutoff = "2026-10-07T00:00:00Z"
    replay_run, replay_tracker = _start_run(replay_db, replay_ledger, as_of=cutoff)
    replay_tracker.prepare_request(build_request_payload("offline-model", "system", "user"))
    replay_attempt = replay_tracker.begin_attempt()
    replay_calls = []
    replay_original_context = replay_db.judgement_context

    def replay_context(*, as_of=None, **kwargs):
        replay_calls.append(as_of)
        return replay_original_context(as_of=as_of, **kwargs)

    monkeypatch.setattr(replay_db, "judgement_context", replay_context)
    monkeypatch.setattr(
        replay_db, "judge_pending_inputs",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("replay must not select current pending inputs")),
    )
    output = replay_ledger.commit_judge(replay_run.run_id, replay_attempt.attempt_id, _result())
    assert replay_calls == [cutoff]
    assert output.judgement_id > 0


def test_policy_recheck_preserves_historical_restriction_after_body_hash_changes(tmp_path):
    database = Database(tmp_path / "policy-empty.sqlite")
    database.initialize()
    post = database.upsert_posts_detailed([{
        "tweet_id": "990000000000000102", "text": "old restricted body",
        "posted_at": "2026-10-06T12:00:00Z", "source": "offline-policy-test",
    }])[0]
    database.upsert_content_policy({
        "tweet_id": "990000000000000102", "content_hash": post["content_hash"],
        "analysis_allowed": True, "event_promotion_allowed": False,
        "judge_evidence_allowed": False, "historical_case_allowed": False,
        "policy_version": "fixture-policy-v1", "policy_status": "RESTRICTED",
    })
    with database.connect() as connection:
        connection.execute("UPDATE tibo_posts SET text_hash=? WHERE id=?", ("e" * 64, post["post_id"]))
    with pytest.raises(ValueError, match="content-policy-ineligible"):
        database.add_judgement(_result("UNKNOWN", evidence=["990000000000000102"]))
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM radar_judgements").fetchone()[0] == 0

    database.upsert_content_policy({
        "tweet_id": "990000000000000102", "content_hash": "e" * 64,
        "analysis_allowed": True, "event_promotion_allowed": True,
        "judge_evidence_allowed": True, "historical_case_allowed": True,
        "policy_version": "fixture-policy-v2", "policy_status": "AGREED",
    })
    database.add_judgement(_result("UNKNOWN", evidence=["990000000000000102"]))


def test_reset_event_upserts_append_source_snapshots_without_changing_cycles_or_human_truth(tmp_path):
    database, post = _database(tmp_path)
    second = database.upsert_posts_detailed([{
        "tweet_id": "990000000000000103", "text": "Second evidence post body.",
        "posted_at": "2026-10-06T13:00:00Z", "source": "offline-truth-test",
    }])[0]
    event = {
        "event_key": "ledger-auto-truth-full-1",
        "event_type": "FULL_RESET", "special_type": None,
        "occurred_at": "2026-10-05T12:00:00Z", "occurred_at_end": None,
        "source_post_id": post["post_id"], "title": "Initial source event",
        "summary": "Initial machine-promoted event summary.",
        "provenance": {"source": "offline-truth-test", "identity_status": "not_independently_reviewed"},
        "time_basis": "post_time_proxy", "scope": "unknown", "execution_stage": "completed",
        "evidence_post_ids": [post["tweet_id"]],
    }
    saved = database.upsert_reset_event(event)
    initial_truth = _records(database, "truth_revision")
    assert len(initial_truth) == 1
    initial_payload = initial_truth[0]["payload"]
    assert initial_payload["true_fields"]["actual_start"] == event["occurred_at"]
    assert initial_payload["true_fields"]["actual_time_basis"] == "post_time_proxy"
    assert initial_payload["true_fields"]["actual_precision"] is None
    assert initial_payload["truth_status"] == "SOURCE_EVENT_UNADJUDICATED"
    assert initial_payload["is_synthetic"] is False
    assert initial_payload["source_event_snapshot_hash"]
    with database.connect() as connection:
        snapshot = connection.execute(
            "SELECT payload_json FROM prediction_artifacts WHERE id=?",
            (initial_payload["source_event_snapshot_ref"]["artifact_id"],),
        ).fetchone()
    assert json.loads(snapshot[0])["source_event_snapshot"]["title"] == "Initial source event"

    with database.connect() as connection:
        cycles_before = [tuple(row) for row in connection.execute("SELECT * FROM reset_cycles ORDER BY id")]
    updated = {
        **event,
        "title": "Revised source event",
        "summary": "Updated machine-promoted event summary.",
        "evidence_post_ids": [post["tweet_id"], second["tweet_id"]],
    }
    database.upsert_reset_event(updated)
    assert len(_records(database, "truth_revision")) == 2
    with database.connect() as connection:
        cycles_after_full_update = [tuple(row) for row in connection.execute("SELECT * FROM reset_cycles ORDER BY id")]
    assert cycles_after_full_update == cycles_before

    unchanged_count = len(_records(database, "truth_revision"))
    database.upsert_reset_event(updated)
    assert len(_records(database, "truth_revision")) == unchanged_count

    ledger = PredictionLedger(database)
    event_before_truth = database.list_reset_events(10)[0]
    cycle_before_truth = database.current_cycle()
    truth_ref = ledger.append_truth(
        saved["id"], expected_revision=2,
        facts={"truth_status": "HUMAN_REVIEW_PENDING"},
        evidence_refs=[], reason="Offline optimistic truth test.",
    )
    human_revision = _records(database, "truth_revision")[-1]
    assert human_revision["record_id"] == truth_ref
    assert human_revision["payload"]["true_fields"].get("actual_start") is None
    assert database.list_reset_events(10)[0] == event_before_truth
    assert database.current_cycle() == cycle_before_truth

    banked = {
        "event_key": "ledger-auto-truth-banked-1",
        "event_type": "SPECIAL_RESET", "special_type": "BANKED",
        "occurred_at": "2026-10-06T14:00:00Z", "source_post_id": post["post_id"],
        "title": "Banked card", "summary": "Does not start a full cycle.",
        "provenance": {"source": "offline-truth-test"}, "time_basis": "unknown",
        "scope": "unknown", "execution_stage": "announced",
        "evidence_post_ids": [second["tweet_id"]],
    }
    saved_banked = database.upsert_reset_event(banked, is_synthetic=True)
    banked_truth = next(
        row for row in _records(database, "truth_revision") if row["event_id"] == saved_banked["id"]
    )
    assert banked_truth["payload"]["is_synthetic"] is True
    with database.connect() as connection:
        cycles_after_banked = [tuple(row) for row in connection.execute("SELECT * FROM reset_cycles ORDER BY id")]
    assert cycles_after_banked == cycles_before
    database.upsert_reset_event({**banked, "title": "Banked card revised"}, is_synthetic=True)
    with database.connect() as connection:
        cycles_after_banked_revision = [tuple(row) for row in connection.execute("SELECT * FROM reset_cycles ORDER BY id")]
    assert cycles_after_banked_revision == cycles_before


def test_first_ledger_touch_snapshots_legacy_reset_event_before_overwrite(tmp_path):
    database = Database(tmp_path / "legacy-event.sqlite")
    database.initialize()
    post = database.upsert_posts_detailed([{
        "tweet_id": "990000000000000104", "text": "Legacy evidence body.",
        "posted_at": "2026-10-05T08:00:00Z", "source": "offline-legacy-test",
    }])[0]
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO reset_events(event_type,special_type,occurred_at,source_post_id,title,summary,
            provenance,created_at,event_key,occurred_at_end,time_basis,scope,execution_stage,evidence_post_ids,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("FULL_RESET", None, "2026-10-05T08:00:00Z", post["post_id"], "Legacy title", "Legacy summary",
             json.dumps({"source": "legacy"}), utc_now(), "legacy-ledger-touch", None,
             "post_time_proxy", "unknown", "completed", json.dumps([post["tweet_id"]]), utc_now()),
        )
    database.upsert_reset_event({
        "event_key": "legacy-ledger-touch", "event_type": "FULL_RESET", "special_type": None,
        "occurred_at": "2026-10-05T08:00:00Z", "source_post_id": post["post_id"],
        "title": "Replacement title", "summary": "Replacement summary",
        "provenance": {"source": "updated"}, "time_basis": "post_time_proxy",
        "scope": "unknown", "execution_stage": "completed", "evidence_post_ids": [post["tweet_id"]],
    })
    revisions = _records(database, "truth_revision")
    assert len(revisions) == 2
    assert revisions[0]["payload"]["revision"] == 1
    assert revisions[1]["payload"]["revision"] == 2
    prior_ref = revisions[0]["payload"]["source_event_snapshot_ref"]["artifact_id"]
    with database.connect() as connection:
        prior_payload = json.loads(connection.execute(
            "SELECT payload_json FROM prediction_artifacts WHERE id=?", (prior_ref,),
        ).fetchone()[0])
    assert prior_payload["source_event_snapshot"]["title"] == "Legacy title"


def test_pipeline_persists_synthetic_failure_and_observation_failure_does_not_retry_model(tmp_path, monkeypatch):
    database, _ = _database(tmp_path)
    fake = _FakeJudge()
    pipeline = IntelligencePipeline(
        database=database, client=fake,
        runtime_log=RuntimeLog(tmp_path / "logs", 5, 1_048_576),
        collector_state={}, repository_root=REPOSITORY_ROOT, is_synthetic=True,
    )

    def fail_insert(*args, **kwargs):
        raise sqlite3.OperationalError("isolated persistence fault")

    monkeypatch.setattr(database, "_insert_judgement", fail_insert)
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(pipeline._run_judge())
    run = _records(database, "run_started")[0]
    assert run["payload"]["is_synthetic"] is True
    assert _records(database, "attempt_event")[-1]["payload"]["event_type"] == "persistence_failure"
    assert _records(database, "output_committed") == []

    monkeypatch.undo()
    # A formal getter miss must leave availability unobserved and must not rerun the model.
    monkeypatch.setattr(database, "get_judgement", lambda _judgement_id: None)
    judgement_id = asyncio.run(pipeline._run_judge())
    assert judgement_id > 0
    assert fake.calls == 2
    assert len(_records(database, "run_started")) == 2
    assert len(_records(database, "output_committed")) == 1
    assert _records(database, "output_observed") == []
    assert database.get_state("pipeline")["output_available_at"] is None
    assert database.get_state("pipeline")["output_observation_error"] == "LookupError"


def test_event_source_body_outside_recent_prompt_window_is_frozen_with_identity_and_parent(tmp_path):
    database = Database(tmp_path / "source-empty.sqlite")
    database.initialize()
    parent_id, source_id = "990000000000000110", "990000000000000111"
    database.upsert_posts_detailed([{
        "tweet_id": source_id, "text": "Full event-source body outside the recent prompt window.",
        "posted_at": "2026-10-01T10:00:00Z", "source": "offline-source-test",
        "is_reply": True, "reply_to_tweet_id": parent_id,
    }])
    captured = utc_now()
    database.contexts.record_observation({
        "tweet_id": source_id, "author": "thsottiaux",
        "text": "Full event-source body outside the recent prompt window.",
        "posted_at": "2026-10-01T10:00:00Z", "parent_id": parent_id,
        "relation_source": "x_replied_to_field", "language": "en", "completeness": "complete",
    }, captured)
    database.contexts.record_observation({
        "tweet_id": parent_id, "author": "thsottiaux", "text": "Frozen parent body.",
        "posted_at": "2026-10-01T09:00:00Z", "parent_id": None,
        "relation_source": "canonical_body_only", "language": "en", "completeness": "complete",
    }, captured)
    recent_window = [{"tweet_id": str(990000000000000200 + index), "text": f"recent {index}"} for index in range(24)]
    pipeline = IntelligencePipeline(
        database=database, client=_FakeJudge(),
        runtime_log=RuntimeLog(tmp_path / "logs", 5, 1_048_576),
        collector_state={}, repository_root=REPOSITORY_ROOT,
    )
    sources = pipeline._ledger_evidence_sources({
        "posts": recent_window,
        "reset_events": [{"evidence_post_ids": [source_id]}],
        "historical_cases": [],
    }, None)
    source = next(item for item in sources if item["tweet_id"] == source_id)
    assert source["snapshot_status"] == "frozen"
    assert source["original_text"].startswith("Full event-source body")
    assert source["reply_context"]["nodes"][0]["tweet_id"] == parent_id

    ledger = PredictionLedger(database)
    run = ledger.begin_run({
        "context": {"posts": recent_window},
        "evidence_sources": sources,
        "semantic_facts": {"evidence_sources": sources},
        "input_snapshot": {},
        "public_prompt": {"system": "source snapshot test"},
        "judge_schema": {"kind": "offline"},
    }, "radar_judge", "offline-runtime", "source_test", "online", is_synthetic=True)
    with database.connect() as connection:
        frame_json = connection.execute(
            "SELECT payload_json FROM prediction_artifacts WHERE id=?", (run.input_frame_artifact_ref["artifact_id"],),
        ).fetchone()[0]
    frame = json.loads(frame_json)
    source_value = frame["evidence_sources"][0]["original_text"]
    assert source_value["source_ref"]["post_id"] == source["post_id"]
    assert source_value["source_ref"]["tweet_id"] == source_id
    assert source_value["source_ref"]["parent_tweet_id"] == parent_id
    assert source_value["source_ref"]["role"] == "prompt_post_source" or source_value["source_ref"]["role"] == "event_source_post"
    assert source_value["artifact_ref"]["kind"] == "text_content"


def test_deepseek_http_retry_records_every_attempt_before_send_without_request_body_artifact(tmp_path, monkeypatch):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, tracker = _start_run(database, ledger)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"private_error_body": "not persisted"}, request=request)
        payload = {
            "model": "reported-offline-model",
            "choices": [{"message": {"content": json.dumps(_result("UNKNOWN"))}}],
            "usage": {
                "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                "total_cost": "must-not-be-derived-or-stored",
            },
        }
        return httpx.Response(200, json=payload, request=request)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.deepseek.asyncio.sleep", no_sleep)
    client = DeepSeekClient(
        api_key="offline-secret-never-persist-this", base_url="https://no-network.invalid",
        model="offline-deepseek", timeout_seconds=5, retries=1,
        runtime_log=RuntimeLog(tmp_path / "deepseek-logs", 5, 1_048_576),
    )
    asyncio.run(client._client.aclose())
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def call():
        with active_attempt_tracker(tracker):
            response = await client.complete_json(
                operation="radar_judge", system="static system prompt", user="actual user body not stored",
            )
        await client.close()
        return response

    response = asyncio.run(call())
    assert response["action_level"] == "UNKNOWN"
    assert len(calls) == 2
    attempts = _records(database, "attempt_started")
    assert len(attempts) == 2
    first_payload, second_payload = [item["payload"] for item in attempts]
    assert first_payload["retry_of"] is None
    assert second_payload["retry_of"] == attempts[0]["attempt_id"]
    assert first_payload["declared_model"] == second_payload["declared_model"] == "offline-deepseek"
    expected_body = build_request_payload("offline-deepseek", "static system prompt", "actual user body not stored")
    assert first_payload["request_hash"] == sha256_json(expected_body)
    event_types = [item["payload"]["event_type"] for item in _records(database, "attempt_event")]
    assert event_types == [
        "response_received", "http_failure", "response_received", "response_model_reported",
        "usage_reported", "response_json_decoded",
    ]
    reported = next(
        item["payload"] for item in _records(database, "attempt_event")
        if item["payload"]["event_type"] == "response_model_reported"
    )
    assert reported["declared_model"] == "offline-deepseek"
    assert reported["reported_model"] == "reported-offline-model"
    assert reported["reported_model_source"] == "deepseek_api_response.model"
    assert reported["reported_model_missing_reason"] is None
    serialized = json.dumps([item["payload"] for item in _records(database, "attempt_event")])
    assert "total_cost" not in serialized
    assert "offline-secret-never-persist-this" not in serialized
    with database.connect() as connection:
        descriptors = [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM prediction_artifacts WHERE kind='request_descriptor'"
        ).fetchall()]
    assert all("messages" not in item and "actual user body" not in json.dumps(item) for item in descriptors)


def test_explicit_synthetic_pipeline_marker_does_not_duplicate_instrumented_mock_http_attempt(tmp_path):
    database, _ = _database(tmp_path)
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={
            "model": "provider-returned-v2",
            "choices": [{"message": {"content": json.dumps(_result("UNKNOWN"))}}],
        }, request=request)

    client = DeepSeekClient(
        api_key="offline-mock-transport-key", base_url="https://offline.invalid",
        model="offline-declared-model", timeout_seconds=5, retries=0,
        runtime_log=RuntimeLog(tmp_path / "mock-pipeline-logs", 5, 1_048_576),
    )

    async def run_pipeline():
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)
        pipeline = IntelligencePipeline(
            database=database, client=client,
            runtime_log=RuntimeLog(tmp_path / "mock-pipeline-logs", 5, 1_048_576),
            collector_state={}, repository_root=REPOSITORY_ROOT, is_synthetic=True,
        )
        try:
            return await pipeline._run_judge()
        finally:
            await client.close()

    judgement_id = asyncio.run(run_pipeline())
    assert judgement_id > 0
    assert len(sent) == 1
    attempts = _records(database, "attempt_started")
    assert len(attempts) == 1
    assert attempts[0]["payload"]["is_synthetic"] is True
    assert attempts[0]["payload"]["declared_model"] == "offline-declared-model"
    run = _records(database, "run_started")[0]
    assert run["payload"]["is_synthetic"] is True
    assert _records(database, "forecast_version")[0]["payload"]["is_synthetic"] is True
    output = _records(database, "output_committed")[0]["payload"]
    assert output["is_synthetic"] is True
    assert "reported_model" not in output["structured_output"]
    observed = _records(database, "output_observed")[0]["payload"]
    assert observed["is_synthetic"] is True
    reported = next(
        row["payload"] for row in _records(database, "attempt_event")
        if row["payload"]["event_type"] == "response_model_reported"
    )
    assert reported["reported_model"] == "provider-returned-v2"
    assert reported["declared_model"] == "offline-declared-model"


def test_deepseek_parse_and_cancel_events_are_distinct_and_network_free(tmp_path):
    async def run_parse():
        database, _ = _database(tmp_path / "parse")
        ledger = PredictionLedger(database)
        _, tracker = _start_run(database, ledger)

        def handler(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}, request=request)

        client = DeepSeekClient(
            api_key="offline-key", base_url="https://no-network.invalid", model="offline-model",
            timeout_seconds=5, retries=0, runtime_log=RuntimeLog(tmp_path / "parse-logs", 5, 1_048_576),
        )
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with active_attempt_tracker(tracker), pytest.raises(DeepSeekError):
                await client.complete_json(operation="radar_judge", system="s", user="u")
        finally:
            await client.close()
        return database

    parse_db = asyncio.run(run_parse())
    parse_records = _records(parse_db, "attempt_event")
    parse_events = [item["payload"]["event_type"] for item in parse_records]
    assert parse_events == ["response_received", "response_model_reported", "parse_failure"]
    missing_model = next(item["payload"] for item in parse_records if item["payload"]["event_type"] == "response_model_reported")
    assert missing_model["reported_model"] is None
    assert missing_model["reported_model_missing_reason"] == "model_field_missing"

    async def run_cancel():
        database, _ = _database(tmp_path / "cancel")
        ledger = PredictionLedger(database)
        _, tracker = _start_run(database, ledger)

        class BlockingTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                await asyncio.Future()

        client = DeepSeekClient(
            api_key="offline-key", base_url="https://no-network.invalid", model="offline-model",
            timeout_seconds=5, retries=0, runtime_log=RuntimeLog(tmp_path / "cancel-logs", 5, 1_048_576),
        )
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=BlockingTransport())
        try:
            with active_attempt_tracker(tracker):
                task = asyncio.create_task(client.complete_json(operation="radar_judge", system="s", user="u"))
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        finally:
            await client.close()
        return database

    cancel_db = asyncio.run(run_cancel())
    cancel_events = [item["payload"]["event_type"] for item in _records(cancel_db, "attempt_event")]
    assert cancel_events == ["cancelled"]


def test_recovery_only_marks_proven_inactive_owner_and_never_invents_finish_time(tmp_path, monkeypatch):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, tracker = _start_run(database, ledger)
    attempt = ledger.begin_send(run.run_id, {
        "stage": "radar_judge", "request_hash": "a" * 64,
    }, owner={"runtime_id": "old-runtime", "pid": 444, "process_start_token": "token"})
    import app.runtime_identity as identity

    monkeypatch.setattr(identity, "owner_status", lambda *_a, **_k: None)
    assert ledger.recover_incomplete(current_runtime_id="current-runtime") == []
    monkeypatch.setattr(identity, "owner_status", lambda *_a, **_k: False)
    recovered = ledger.recover_incomplete(current_runtime_id="current-runtime")
    assert len(recovered) == 1
    recovery = _records(database, "recovery_observed")[0]["payload"]
    assert recovery["owner_status"] == "inactive"
    assert recovery["terminal_status"] == "UNKNOWN"
    assert recovery["actual_finished_at"] is None
    assert recovery["observed_at"]


def test_canonical_serialization_and_worktree_root_are_stable():
    assert canonical_bytes({"b": 2, "a": "é"}) == '{"a":"é","b":2}\n'.encode("utf-8")
    assert sha256_json({"a": 1}) == sha256_json({"a": 1})
    assert REPOSITORY_ROOT == Path(__file__).resolve().parents[3]
    from app import config as config_module, prediction_ledger as ledger_module
    assert (REPOSITORY_ROOT / 'apps/backend/app/config.py').resolve() == Path(config_module.__file__).resolve()
    assert (REPOSITORY_ROOT / 'apps/backend/app/prediction_ledger.py').resolve() == Path(ledger_module.__file__).resolve()
    for marker in ('README.md', 'apps/backend/requirements.txt', 'apps/web/package.json', 'scripts/export_prediction_review.py'):
        assert (REPOSITORY_ROOT / marker).is_file(), marker


def test_normal_legacy_scalar_reference_expires_without_upgrading_execution_precision():
    from app.db import next_reset_baseline
    anchor = {'occurred_at': '2026-01-01T00:00:00Z'}
    original = deepcopy(anchor)
    for as_of in ('2026-01-09T00:00:00Z', '2027-01-01T00:00:00Z'):
        value = next_reset_baseline(anchor, as_of=as_of)
        assert value['status'] == 'expired'
        assert value['estimated_at'] == value['predicted_start'] == '2026-01-08T00:00:00Z'
        assert value['predicted_end'] is None
        assert value['prediction_form'] == 'start_only' and value['precision'] == 'unknown'
        assert value['expiry_basis'] == 'legacy_scalar_reference_only'
        assert value['anchor_limitation'] == 'LEGACY_SCALAR_REFERENCE_NOT_ACTUAL_START_BOUND'
    assert anchor == original
    explicit_lower_bound = {**anchor, 'provenance': {'time_form': 'start_only', 'time_precision': 'minute'}}
    value = next_reset_baseline(explicit_lower_bound, as_of='2027-01-01T00:00:00Z')
    assert value['status'] == 'baseline'  # no execution upper bound is invented
    assert value['predicted_end'] is None and value['expiry_basis'] == 'upper_bound_unknown'


def test_normal_explicit_single_bound_is_not_unlimited_current_advice(tmp_path):
    database, post = _database(tmp_path)
    ledger = PredictionLedger(database)
    anchor = database.upsert_reset_event({'event_key': 'explicit-single-bound-full', 'event_type': 'FULL_RESET',
        'occurred_at': '2026-01-01T00:00:00Z', 'time_basis': 'explicit_text', 'scope': 'all_paid',
        'execution_stage': 'completed', 'source_post_id': post['post_id'], 'evidence_post_ids': [post['tweet_id']],
        'title': 'Offline lower bound', 'summary': 'No upper bound is proved.',
        'provenance': {'time_form': 'start_only', 'time_precision': 'minute'}}, is_synthetic=True)
    ledger.record_normal_baseline(anchor, is_synthetic=True)
    line = ledger.prediction_lines(None)['lines']['NORMAL_WEEKLY']
    assert line['baseline_status'] == 'baseline' and line['predicted_end'] is None
    assert line['valid'] is False and line['validation_reason'] == 'ANCHOR_UPPER_BOUND_UNKNOWN'


class _FakeJudge:
    model = "offline-synthetic-judge"

    def __init__(self):
        self.calls = 0

    async def complete_json(self, *, operation: str, system: str, user: str):
        assert operation == "radar_judge"
        self.calls += 1
        return _result("UNKNOWN")


def test_pipeline_synthetic_marker_defaults_false_independent_of_http_instrumentation_flag(tmp_path):
    database, _ = _database(tmp_path)
    fake = _FakeJudge()
    fake.ledger_attempts_enabled = False
    pipeline = IntelligencePipeline(
        database=database, client=fake,
        runtime_log=RuntimeLog(tmp_path / "marker-default-logs", 5, 1_048_576),
        collector_state={}, repository_root=REPOSITORY_ROOT,
        runtime_identity={"runtime_id": "pipeline-real-runtime", "owner": {"source": "explicit-test"}},
    )
    assert pipeline.is_synthetic is False
    pipeline._ensure_runtime_identity()

    synthetic_pipeline = IntelligencePipeline(
        database=database, client=fake,
        runtime_log=RuntimeLog(tmp_path / "marker-synthetic-logs", 5, 1_048_576),
        collector_state={}, repository_root=REPOSITORY_ROOT,
        runtime_identity={"runtime_id": "pipeline-synthetic-runtime", "owner": {"source": "explicit-test"}},
        is_synthetic=True,
    )
    synthetic_pipeline._ensure_runtime_identity()

    direct_identity = {"runtime_id": "direct-unmarked-runtime", "owner": {"source": "direct-test"}}
    ledger = PredictionLedger(database)
    assert ledger.record_runtime_identity(direct_identity) == direct_identity["runtime_id"]
    assert "is_synthetic" not in direct_identity
    assert ledger.record_runtime_identity(direct_identity) == direct_identity["runtime_id"]
    events_before_conflict = len(_records(database, "runtime_identity"))
    with database.connect() as connection:
        artifacts_before_conflict = connection.execute(
            "SELECT payload_json FROM prediction_artifacts WHERE kind='runtime_identity'",
        ).fetchall()
    with pytest.raises(ValueError, match="runtime identity conflict"):
        ledger.record_runtime_identity(direct_identity, is_synthetic=False)
    assert len(_records(database, "runtime_identity")) == events_before_conflict
    with database.connect() as connection:
        artifacts_after_conflict = connection.execute(
            "SELECT payload_json FROM prediction_artifacts WHERE kind='runtime_identity'",
        ).fetchall()
    assert sorted(row[0] for row in artifacts_after_conflict) == sorted(
        row[0] for row in artifacts_before_conflict
    )

    events = {row["payload"]["runtime_id"]: row["payload"] for row in _records(database, "runtime_identity")}
    with database.connect() as connection:
        artifact_rows = connection.execute(
            "SELECT payload_json FROM prediction_artifacts WHERE kind='runtime_identity'",
        ).fetchall()
    artifacts = {payload["runtime_id"]: payload for payload in (json.loads(row[0]) for row in artifact_rows)}
    for runtime_id, expected in (
        ("pipeline-real-runtime", False),
        ("pipeline-synthetic-runtime", True),
        ("direct-unmarked-runtime", None),
    ):
        assert events[runtime_id]["is_synthetic"] is expected
        assert artifacts[runtime_id]["is_synthetic"] is expected


class _RecordingJudge:
    model = "offline-request-material"

    def __init__(self):
        self.requests = []

    async def complete_json(self, *, operation: str, system: str, user: str):
        self.requests.append({"operation": operation, "system": system, "user": user})
        return {
            "action_level": "UNKNOWN",
            "horizon_24h": "UNKNOWN",
            "horizon_48h": "UNKNOWN",
            "horizon_72h": "UNKNOWN",
            "estimated_start": "2026-10-09",
            "estimated_end": None,
            "estimate_basis": "日期粒度的离线回归样本。",
            "reason_summary": "仅用于验证模型输入与原始时间表达。",
            "evidence_post_ids": [],
            "predictions": _unknown_targets(),
        }


def test_judge_model_input_excludes_only_additive_ledger_audit_metadata():
    fixed_as_of = "2026-10-07T04:00:00Z"
    previous_judgement = {
        "id": 17,
        "created_at": "2026-10-07T03:00:00Z",
        "action_level": "YELLOW",
        "horizon_24h": "GREEN",
        "horizon_48h": "YELLOW",
        "horizon_72h": "YELLOW",
        "estimated_start": None,
        "estimated_end": None,
        "estimate_basis": "旧业务依据保留。",
        "reason_summary": "旧业务理由保留。",
        "evidence_post_ids": ["990000000000000101"],
        "raw": {
            "legacy_business_field": "keep-this-field",
            "input_versions": {"990000000000000101": "a" * 64},
            "input_snapshot": {"input_versions": {"990000000000000101": "a" * 64}},
        },
    }
    legacy_context = {
        "posts": [{"tweet_id": "990000000000000101", "text": "Offline prior context."}],
        "reset_events": [],
        "last_full_reset": None,
        "current_cycle": None,
        "previous_judgement": previous_judgement,
        "corpus_version": "offline-corpus-v1",
        "historical_cases": [],
    }
    audited_context = deepcopy(legacy_context)
    audited_context["previous_judgement"].update({
        "ledger_attempt_id": "ledger-attempt-only",
        "ledger_run_id": "ledger-run-only",
        "attempt_started_at": "audit-start-only",
        "attempt_finished_at": "audit-finish-only",
        "output_available_at": "audit-available-only",
    })
    audited_context["previous_judgement"]["raw"].update({
        "ledger_attempt_id": "raw-ledger-attempt-only",
        "request_hash": "audit-request-hash-only",
        "received_at": "audit-received-only",
        "duration_ms": 123456,
        "output_observation_error": "audit-observation-only",
        "estimated_start_expression": "audit-expression-only",
        "estimated_start_time_metadata": {"precision": "audit-only"},
    })
    audited_before = deepcopy(audited_context)

    legacy_client = _RecordingJudge()
    audited_client = _RecordingJudge()
    legacy_material = []
    audited_material = []

    async def run(client, context, material):
        @contextmanager
        def request_scope(value):
            material.append(value)
            yield None
        return await judge(
            client, context, data_health="UNKNOWN", as_of=fixed_as_of,
            request_scope=request_scope,
        )

    legacy_result = asyncio.run(run(legacy_client, legacy_context, legacy_material))
    audited_result = asyncio.run(run(audited_client, audited_context, audited_material))

    assert legacy_client.requests == audited_client.requests
    assert legacy_material[0]["system"] == audited_material[0]["system"]
    assert legacy_material[0]["user_prefix"] == audited_material[0]["user_prefix"]
    assert legacy_material[0]["schema"] == audited_material[0]["schema"]
    assert legacy_client.requests[0]["user"].startswith(legacy_material[0]["user_prefix"])
    assert legacy_context["previous_judgement"]["raw"]["input_versions"] == {
        "990000000000000101": "a" * 64,
    }
    assert legacy_context["previous_judgement"]["raw"]["legacy_business_field"] == "keep-this-field"
    assert audited_context == audited_before
    request_text = audited_client.requests[0]["user"]
    for marker in (
        "ledger-attempt-only", "ledger-run-only", "audit-start-only", "audit-finish-only",
        "audit-available-only", "audit-request-hash-only", "audit-received-only",
        "audit-observation-only", "audit-expression-only",
    ):
        assert marker not in request_text
    body = json.loads(request_text[len(audited_material[0]["user_prefix"]):])
    assert body["required_schema"] == audited_material[0]["schema"]
    assert body["context"]["previous_judgement"]["raw"]["input_versions"] == {
        "990000000000000101": "a" * 64,
    }
    assert legacy_result["estimated_start"] == audited_result["estimated_start"] == "2026-10-09T00:00:00Z"
    assert legacy_result["estimated_start_expression"] == "2026-10-09"
    assert legacy_result["estimated_start_time_metadata"] == {
        "precision": "day", "source_timezone": None, "timezone_status": "not_stated",
    }
    assert legacy_result["estimated_end"] is None
    assert legacy_result["estimated_end_expression"] is None
    assert legacy_result["estimated_end_time_metadata"] is None
    structured = PredictionLedger._structured_output(legacy_result)
    assert structured["estimated_start_expression"] == "2026-10-09"
    assert structured["estimated_start_time_metadata"]["precision"] == "day"


def test_unknown_judge_evidence_is_a_durable_exportable_reference_failure(tmp_path):
    database, _ = _database(tmp_path)

    class UnknownEvidenceJudge(_FakeJudge):
        async def complete_json(self, *, operation: str, system: str, user: str):
            assert operation == "radar_judge"
            self.calls += 1
            result = _result("UNKNOWN")
            result["evidence_post_ids"] = ["990000000000000999"]
            return result

    client = UnknownEvidenceJudge()
    pipeline = IntelligencePipeline(
        database=database, client=client,
        runtime_log=RuntimeLog(tmp_path / "reference-failure-logs", 5, 1_048_576),
        collector_state={}, repository_root=REPOSITORY_ROOT, is_synthetic=True,
    )
    with pytest.raises(ValueError):
        asyncio.run(pipeline._run_judge())

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM radar_judgements").fetchone()[0] == 0
    assert _records(database, "output_committed") == []
    assert _records(database, "output_observed") == []
    failure = _records(database, "attempt_event")[-1]["payload"]
    assert failure["event_type"] == "reference_failure"
    assert failure["reason_code"] == "UNKNOWN_EVIDENCE_REFERENCE"
    assert failure["failure_terminal"] is True
    assert failure["output_available_at"] is None
    assert failure["publication_status"] == "rejected"
    # The rejected, allowlisted return keeps the invalid reference for audit;
    # no raw response or exception text is retained outside that structure.
    assert failure['structured_output']['evidence_post_ids'] == ['990000000000000999']
    assert "990000000000000999" not in json.dumps({key: value for key, value in failure.items() if key != 'structured_output'})

    run = _records(database, "run_started")[0]
    with database.connect() as connection:
        review = read_review(
            connection, {"series_id": run["series_id"]}, freeze_at=utc_text(),
        )
    assert review["outputs"] == []
    exported_attempt = next(
        event for attempt in review["attempts"] for event in attempt["events"]
        if event.get("event_type") == "reference_failure"
    )
    assert exported_attempt["reason_code"] == "UNKNOWN_EVIDENCE_REFERENCE"
    assert exported_attempt["reason_summary"] == "Judge evidence reference was unresolved or ineligible."
    assert exported_attempt["output_available_at"] is None


def test_observation_insert_failure_keeps_availability_null_and_does_not_retry(tmp_path):
    database, _ = _database(tmp_path)
    client = _FakeJudge()
    pipeline = IntelligencePipeline(
        database=database, client=client,
        runtime_log=RuntimeLog(tmp_path / "observe-insert-failure-logs", 5, 1_048_576),
        collector_state={}, repository_root=REPOSITORY_ROOT, is_synthetic=True,
    )
    with database.connect() as connection:
        connection.execute("""CREATE TRIGGER fail_output_observed_insert
            BEFORE INSERT ON prediction_ledger WHEN NEW.kind='output_observed'
            BEGIN SELECT RAISE(ABORT, 'isolated output observation insert fault'); END""")

    judgement_id = asyncio.run(pipeline._run_judge())
    assert judgement_id > 0
    assert client.calls == 1
    assert len(_records(database, "output_committed")) == 1
    assert _records(database, "output_committed")[0]["payload"]["output_available_at"] is None
    assert _records(database, "output_observed") == []
    failure = next(
        item["payload"] for item in _records(database, "attempt_event")
        if item["payload"]["event_type"] == "output_observation_failed"
    )
    assert failure["reason_code"] == "OBSERVATION_PERSISTENCE_FAILURE"
    assert failure["output_available_at"] is None
    assert database.get_state("pipeline")["output_available_at"] is None


def test_reversed_wall_clock_times_are_kept_and_annotated(tmp_path, monkeypatch):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, tracker = _start_run(database, ledger)
    tracker.prepare_request(build_request_payload("offline-model", "system", "user"))
    attempt = tracker.begin_attempt()
    reversed_finish = "2000-01-01T00:00:00Z"
    ledger.append_attempt_event(
        run.run_id, attempt.attempt_id, "timeout", failure_terminal=True,
        attempt_finished_at=reversed_finish, reason_code="TEST_TIMEOUT",
    )
    terminal = _records(database, "attempt_event")[-1]
    assert terminal["occurred_at"] == reversed_finish
    assert terminal["payload"]["attempt_finished_at"] == reversed_finish
    assert terminal["payload"]["clock_anomaly"] == "wall_clock_reversed"
    assert terminal["payload"]["time_limitation"] == "timestamps_retained_without_ordering"

    run_b, tracker_b = _start_run(database, ledger)
    tracker_b.prepare_request(build_request_payload("offline-model", "system", "user"))
    attempt_b = tracker_b.begin_attempt()
    output = ledger.commit_judge(run_b.run_id, attempt_b.attempt_id, _result("UNKNOWN"))
    import app.prediction_ledger as ledger_module

    original_utc_text = ledger_module.utc_text

    def reversed_observation(value=None):
        return "2000-01-01T00:00:00Z" if value is None else original_utc_text(value)

    monkeypatch.setattr(ledger_module, "utc_text", reversed_observation)
    observed = ledger.observe_output(output)
    assert observed["observed_at"] == reversed_finish
    assert observed["clock_anomaly"] == "wall_clock_reversed"
    assert observed["time_limitation"] == "timestamps_retained_without_ordering"
    row = _records(database, "output_observed")[-1]
    assert row["occurred_at"] == reversed_finish
