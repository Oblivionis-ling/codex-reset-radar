from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

import app.main as main_module
from app.db import utc_now
from app.deepseek import build_request_payload
from app.prediction_ledger import AttemptTracker
from app.prediction_contract import PREDICTION_CONTRACT_VERSION
from app.review_common import utc_text


def _judgement() -> dict:
    return {
        "id": 77,
        "action_level": "UNKNOWN",
        "horizon_24h": "UNKNOWN",
        "horizon_48h": "UNKNOWN",
        "horizon_72h": "UNKNOWN",
        "data_health": "HEALTHY",
        "reason_summary": "Synthetic API contract fixture.",
        "evidence_post_ids": [],
        "special_event_ids": [],
        "model": "synthetic-test-only",
        "prompt_version": "synthetic-test-only",
        "created_at": "2026-10-09T00:00:00Z",
        "valid_until": None,
        "estimated_start": None,
        "estimated_end": None,
        "estimate_basis": "synthetic-test-only",
        "corpus_version": 0,
        "historical_case_ids": [],
    }


def _line(state: str, *, form: str = "point", reason: str | None = None) -> dict:
    return {
        "state": state,
        "form": form,
        "expression": "2026-10-10" if form == "date" else None,
        "date_boundaries": "closed_conservative_local_day_envelope_not_execution_instants" if form == "date" else None,
        "predicted_start": "2026-10-10T00:00:00Z" if form == "date" else "2026-10-10T10:00:00Z",
        "predicted_end": "2026-10-11T00:00:00Z" if form == "date" else None,
        "method": "model_inference" if state != "baseline" else None,
        "basis": "user_full_plus_7d" if state == "baseline" else "synthetic-test-only",
        "scope": {"value": "all_paid", "certainty": "fixture-only"},
        "anchor_limitation": None,
        "anchor_time_basis": None,
        "reason": reason or "Synthetic API contract fixture.",
        "valid": state in {"ready", "current", "baseline"},
        "updated_at": "2026-10-09T00:00:00Z",
        "validity": {"state": "valid"},
        "health": {"state": "healthy"},
        "series_id": f"series-{state}",
        "revision": 1,
        "current_advice_eligible": True,
    }


def _install_healthy_projection(monkeypatch, client, *, validation=None) -> None:
    database = client.app.state.database
    judgement = _judgement()
    monkeypatch.setattr(database, "latest_judgement", lambda: judgement)
    monkeypatch.setattr(
        database,
        "validate_judgement",
        lambda _judgement: validation or {"valid": True, "reason": "VALID"},
    )
    monkeypatch.setattr(
        main_module,
        "collector_health",
        lambda _states: {
            "data_health": "HEALTHY",
            "collector": {
                "profile_monitor": {"state": "healthy", "reason": "FRESH"},
                "replies_monitor": {"state": "healthy", "reason": "FRESH"},
            },
        },
    )
    projection = {
        "state": "partial",
        "capabilities": {"normal_weekly": True, "extra_full": True, "banked": True},
        "health": {"state": "partial", "reason": "BANKED_TARGET_REJECTED"},
        "lines": {
            "NORMAL_WEEKLY": _line("baseline", form="date"),
            "EXTRA_FULL": _line("ready"),
            "BANKED": _line("rejected", reason="MISSING_TARGET"),
        },
    }
    ledger = client.app.state.prediction_ledger
    monkeypatch.setattr(ledger, "prediction_lines", lambda _judgement, *, as_of: projection, raising=False)


def _begin_synthetic_attempt(database, ledger):
    instant = utc_text()
    context = database.judgement_context(as_of=instant)
    context["pending_inputs"] = []
    database.refresh_input_snapshot(context)
    context["judged_at"] = instant
    context["data_health"] = "UNKNOWN"
    frozen_input = {
        "forecast": {
            "target": "EXTRA_FULL",
            "scope": {"value": "unknown", "certainty": "not_established_by_ledger"},
            "question": "next_full_reset_start",
            "method": "model_inference",
        },
        "input_snapshot": database.input_snapshot(context),
        "input_cutoff_at": instant,
        "judgement_as_of": instant,
        "selection_mode": "replay",
        "prediction_contract_version": PREDICTION_CONTRACT_VERSION,
        "context": context,
        "policy_versions": context.get("policy_versions") or {},
        "public_prompt": {"system": "synthetic API test only"},
        "judge_schema": {"kind": "synthetic API test only"},
        "data_health": "UNKNOWN",
        "pending_inputs": [],
    }
    run = ledger.begin_run(
        frozen_input, "radar_judge", "synthetic-api-test", "history-boundary-test", "replay", is_synthetic=True,
    )
    tracker = AttemptTracker(ledger, run.run_id, {
        "stage": "radar_judge",
        "judgement_as_of": instant,
        "input_frame_artifact_ref": run.input_frame_artifact_ref,
        "prompt_artifact_ref": run.prompt_artifact_ref,
        "schema_artifact_ref": run.schema_artifact_ref,
    }, {"runtime_id": "synthetic-api-test", "pid": 1, "platform": "test"})
    tracker.prepare_request(build_request_payload("offline-test", "synthetic", "no network request"))
    attempt = tracker.begin_attempt()
    return run, attempt


def _append_synthetic_unknown_output(
    database, ledger, *, rejected_target=None, known_target=None, future_validity=False, expired_validity=False,
):
    known_evidence = None
    if known_target is not None:
        post = database.upsert_posts_detailed([{
            "tweet_id": "synthetic-api-valid-target-evidence",
            "text": "Synthetic API target evidence; no network or provider call.",
            "posted_at": utc_text(datetime.now(UTC) - timedelta(minutes=1)),
            "source": "synthetic-api-test",
        }])[0]
        database.save_analysis(post["post_id"], post["content_hash"], "offline-test", "offline-analysis-v1", {
            "category": "other", "summary": "Offline target evidence fixture.",
            "context_sufficient": True, "_input_hash": post["content_hash"],
            "_text_hash": post["content_hash"], "_analysed_at": utc_now(),
        })
        known_evidence = "synthetic-api-valid-target-evidence"
    run, attempt = _begin_synthetic_attempt(database, ledger)
    target_outputs = {
        target: {
            "target": target,
            "status": "UNKNOWN",
            "method": "model_inference",
            "scope": {"value": "unknown", "certainty": "not_established_by_ledger"},
            "predicted_start": None,
            "predicted_end": None,
            "prediction_form": "unknown",
            "source_timezone": None,
            "precision": "unknown",
            "time_basis": "unknown",
            "expression": None,
            "relative_anchor_at": None,
            "reason": "Synthetic fixture has no independent time evidence.",
            "unresolved_reason": "NO_INDEPENDENT_TIME_EVIDENCE",
            "evidence_post_ids": [],
            "evidence_refs": [],
            "lifecycle": "unknown",
        }
        for target in ("EXTRA_FULL", "BANKED")
    }
    if rejected_target is not None:
        rejected = target_outputs[rejected_target]
        rejected.update({
            "status": "KNOWN",
            "predicted_start": "2026-10-10T10:00:00Z",
            "prediction_form": "point",
            "precision": "second",
            "source_timezone": "UTC",
            "time_basis": "model_inference",
            "unresolved_reason": None,
            "lifecycle": "planned",
            "evidence_post_ids": ["not-exposed-to-this-run"],
        })
    if known_target is not None:
        target_outputs[known_target].update({
            "status": "KNOWN",
            "predicted_start": utc_text(datetime.now(UTC) + timedelta(hours=1)),
            "prediction_form": "point",
            "precision": "second",
            "source_timezone": "UTC",
            "time_basis": "model_inference",
            "reason": "Explicit offline fixture has no future time evidence.",
            "relative_offset_seconds": 3600,
            "unresolved_reason": None,
            "lifecycle": "planned",
            "evidence_post_ids": [known_evidence],
        })
    judged_at = utc_now()
    created_at = utc_text(datetime.now(UTC) - timedelta(hours=1)) if expired_validity else judged_at
    valid_until = (
        utc_text(datetime.now(UTC) - timedelta(minutes=30)) if expired_validity
        else utc_text(datetime.now(UTC) + timedelta(days=1)) if future_validity
        else judged_at
    )
    context = database.judgement_context(as_of=judged_at)
    context["pending_inputs"] = []
    database.refresh_input_snapshot(context)
    result = {
        "created_at": created_at,
        "action_level": "UNKNOWN",
        "horizon_24h": "UNKNOWN",
        "horizon_48h": "UNKNOWN",
        "horizon_72h": "UNKNOWN",
        "data_health": "UNKNOWN",
        "reason_summary": "Synthetic API history boundary test.",
        "evidence_post_ids": [],
        "special_event_ids": [],
        "model": "offline-test-model",
        "prompt_version": "offline-test-prompt-v1",
        "estimated_start": None,
        "estimated_end": None,
        "estimate_basis": "Synthetic fixture only.",
        "valid_until": valid_until,
        "raw": {
            "synthetic": True,
            "input_versions": context["input_versions"],
            "input_post_ids": list(context["input_versions"]),
            "input_snapshot": database.input_snapshot(context),
        },
        "cycle_id": (context.get("current_cycle") or {}).get("id"),
        "predictions": target_outputs,
    }
    output = ledger.commit_judge(run.run_id, attempt.attempt_id, result)
    ledger.observe_output(output)
    return run, output


def test_radar_adds_three_line_projection_without_changing_legacy_reset_fields(client):
    before = client.app.state.database.counts()
    payload = client.get("/api/v2/radar").json()

    assert payload["action_level"] == "UNKNOWN"
    assert payload["next_reset"]["status"] == "waiting_for_verified_history"
    assert "estimated_start" in payload
    assert "valid_until" in payload
    assert payload["prediction"]["state"] == "unknown"
    for target in ("EXTRA_FULL", "BANKED"):
        status_projection = payload["prediction"]["lines"][target]["status_projection"]
        assert status_projection["capability"] == {"implementation": "supported", "source": "ledger_v2"}
        assert status_projection["run"]["state"] == "not_started"
        assert status_projection["result"]["state"] == "not_attempted"
        assert payload["prediction"]["lines"][target]["state"] == "not_attempted"
    assert set(payload["prediction"]["lines"]) == {"NORMAL_WEEKLY", "EXTRA_FULL", "BANKED"}
    normal = payload["prediction"]["lines"]["NORMAL_WEEKLY"]
    assert normal["state"] == "unavailable"
    assert normal["status_projection"]["normal"]["calculation_status"] == "no_business_full_anchor"
    assert normal["status_projection"]["history_status"] == "not_applicable"
    assert payload["prediction"]["capabilities"]["history"] is True
    assert "NO_BUSINESS_FULL_ANCHOR" in normal["reason"]
    assert client.app.state.database.counts() == before
    assert client.app.state.pipeline is None


def test_normal_calculable_helper_is_not_misclassified_as_unbackfilled(monkeypatch, client):
    database = client.app.state.database
    anchor_at = utc_text(datetime.now(UTC) - timedelta(hours=1))
    database.upsert_reset_event({
        "event_key": "synthetic-normal-helper-anchor",
        "event_type": "FULL_RESET",
        "occurred_at": anchor_at,
        "title": "Synthetic Full anchor for Normal helper test",
        "summary": "Offline test fixture only.",
        "time_basis": "explicit_text",
        "scope": "all_paid",
        "execution_stage": "completed",
        "evidence_post_ids": [],
        "provenance": {"time_form": "point", "time_precision": "second", "source_timezone": "UTC"},
    }, is_synthetic=True)
    monkeypatch.setattr(main_module, "collector_health", lambda _states: {
        "data_health": "HEALTHY",
        "collector": {
            "profile_monitor": {"state": "healthy", "reason": "FIXTURE"},
            "replies_monitor": {"state": "healthy", "reason": "FIXTURE"},
        },
    })
    before_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()

    normal = client.get("/api/v2/radar").json()["prediction"]["lines"]["NORMAL_WEEKLY"]

    after_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()
    assert normal["status_projection"]["normal"]["calculation_status"] == "calculated"
    assert normal["status_projection"]["history_status"] == "not_backfilled"
    assert normal["validation_reason"] == "NORMAL_VERSION_NOT_RECORDED"
    assert normal["state"] == "baseline"
    assert normal["predicted_start"] is not None
    assert normal["current_advice_eligible"] is True
    assert normal.get("forecast_id") is None and normal.get("record_id") is None
    assert after_hash == before_hash


def test_real_ledger_normal_baseline_without_output_observation_is_not_current_advice(monkeypatch, client):
    database = client.app.state.database
    ledger = client.app.state.prediction_ledger
    anchor = database.upsert_reset_event({
        "event_key": "synthetic-normal-unobserved-anchor",
        "event_type": "FULL_RESET",
        "occurred_at": utc_text(datetime.now(UTC) - timedelta(hours=1)),
        "title": "Synthetic Full anchor with unobserved Normal output",
        "summary": "Offline API protection fixture.",
        "time_basis": "explicit_text",
        "scope": "all_paid",
        "execution_stage": "completed",
        "evidence_post_ids": [],
        "provenance": {"time_form": "point", "time_precision": "second", "source_timezone": "UTC"},
    }, is_synthetic=True)
    original_read_connection = ledger._read_connection
    fail_observation_once = True

    def skip_first_read():
        nonlocal fail_observation_once
        if fail_observation_once:
            fail_observation_once = False
            raise RuntimeError("synthetic output observation failure")
        return original_read_connection()

    monkeypatch.setattr(ledger, "_read_connection", skip_first_read)
    record = ledger.record_normal_baseline(anchor, is_synthetic=True)
    assert record is not None
    monkeypatch.setattr(main_module, "collector_health", lambda _states: {
        "data_health": "HEALTHY",
        "collector": {
            "profile_monitor": {"state": "healthy", "reason": "FIXTURE"},
            "replies_monitor": {"state": "healthy", "reason": "FIXTURE"},
        },
    })

    normal = client.get("/api/v2/radar").json()["prediction"]["lines"]["NORMAL_WEEKLY"]

    assert normal["status_projection"]["history_status"] == "backfilled"
    assert normal["status_projection"]["normal"]["calculation_status"] == "calculated"
    assert normal["validation_reason"] == "OUTPUT_AVAILABILITY_PENDING"
    assert normal["output_available_at"] is None
    assert normal["current_advice_eligible"] is False


def test_real_ledger_normal_unknown_upper_bound_is_not_current_advice(monkeypatch, client):
    database = client.app.state.database
    ledger = client.app.state.prediction_ledger
    anchor = database.upsert_reset_event({
        "event_key": "synthetic-normal-unknown-upper-anchor",
        "event_type": "FULL_RESET",
        "occurred_at": utc_text(datetime.now(UTC) - timedelta(hours=1)),
        "title": "Synthetic Full anchor without an upper bound",
        "summary": "Offline API protection fixture.",
        "time_basis": "explicit_text",
        "scope": "all_paid",
        "execution_stage": "completed",
        "evidence_post_ids": [],
        "provenance": {"time_form": "start_only", "time_precision": "minute", "source_timezone": "UTC"},
    }, is_synthetic=True)
    record = ledger.record_normal_baseline(anchor, is_synthetic=True)
    assert record is not None
    monkeypatch.setattr(main_module, "collector_health", lambda _states: {
        "data_health": "HEALTHY",
        "collector": {
            "profile_monitor": {"state": "healthy", "reason": "FIXTURE"},
            "replies_monitor": {"state": "healthy", "reason": "FIXTURE"},
        },
    })

    normal = client.get("/api/v2/radar").json()["prediction"]["lines"]["NORMAL_WEEKLY"]

    assert normal["status_projection"]["history_status"] == "backfilled"
    assert normal["status_projection"]["normal"]["calculation_status"] == "calculated"
    assert normal["validation_reason"] == "ANCHOR_UPPER_BOUND_UNKNOWN"
    assert normal["anchor_limitation"] == "ANCHOR_UPPER_BOUND_UNKNOWN"
    assert normal["current_advice_eligible"] is False


def test_real_ledger_partial_rejection_hides_question_id_as_current_output_and_keeps_legal_unknown(client):
    database = client.app.state.database
    ledger = client.app.state.prediction_ledger
    run, _ = _append_synthetic_unknown_output(
        database, ledger, rejected_target="EXTRA_FULL", future_validity=True,
    )
    before_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()

    radar = client.get("/api/v2/radar").json()["prediction"]
    full = radar["lines"]["EXTRA_FULL"]
    banked = radar["lines"]["BANKED"]
    assert full["state"] == "rejected"
    assert full["status_projection"]["result"]["state"] == "rejected"
    assert full["forecast_id"] is None
    assert full["form"] == "unknown"
    assert full["predicted_start"] is None and full["predicted_end"] is None
    assert full["origin_judgement_id"] is None
    assert "rejected_output" not in full
    assert full["evidence_post_ids"] is None and full["evidence_refs"] is None
    assert full["relative_offset_seconds"] is None and full["lifecycle"] is None
    assert full["reason"] == full["validation_reason"]
    assert full["question_version"] is not None and full["question_revision"] is not None
    assert full["run_id"] == run.run_id and full["attempt_id"] is not None
    assert full["series_id"] == run.target_refs["EXTRA_FULL"]["series_id"]

    assert banked["state"] == "unknown"
    assert banked["status"] == "UNKNOWN" and banked["valid"] is True
    assert banked["status_projection"]["result"]["state"] == "unknown_valid"
    assert banked["forecast_id"] is not None
    assert banked["question_version"] == banked["forecast_id"]
    assert banked["predicted_start"] is None and banked["predicted_end"] is None
    assert banked["run_id"] == full["run_id"] and banked["attempt_id"] == full["attempt_id"]

    history = client.get("/api/v2/predictions/history").json()
    run_items = {item["target"]: item for item in history["items"]}
    assert run_items["EXTRA_FULL"]["status_projection"]["result"]["state"] == "rejected"
    assert run_items["EXTRA_FULL"]["state"] == "rejected"
    assert "rejected_output" not in run_items["EXTRA_FULL"]
    assert run_items["EXTRA_FULL"]["reason"] == run_items["EXTRA_FULL"]["validation_reason"]
    assert run_items["BANKED"]["status_projection"]["result"]["state"] == "unknown_valid"
    assert run_items["BANKED"]["state"] == "historical"
    assert hashlib.sha256(database.path.read_bytes()).hexdigest() == before_hash


@pytest.mark.parametrize("target", ["EXTRA_FULL", "BANKED"])
def test_real_ledger_timeout_keeps_a_valid_prior_forecast_only_inside_last_known(client, target):
    database = client.app.state.database
    ledger = client.app.state.prediction_ledger
    prior_run, prior_output = _append_synthetic_unknown_output(
        database, ledger, known_target=target, future_validity=True,
    )
    failed_run, failed_attempt = _begin_synthetic_attempt(database, ledger)
    ledger.append_attempt_event(
        failed_run.run_id, failed_attempt.attempt_id, "timeout", failure_terminal=True,
        reason_code="TIMEOUT", attempt_finished_at=utc_text(), output_available_at=None,
    )
    before_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()

    radar = client.get("/api/v2/radar").json()["prediction"]["lines"]
    after_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()
    full = radar[target]

    assert full["state"] == "timeout"
    assert full["forecast_id"] is None and full["predicted_start"] is None
    assert full["question_version"] is not None and full["question_revision"] is not None
    assert full["origin_judgement_id"] is None
    assert full["reason"] == "TIMEOUT"
    assert full["evidence_post_ids"] is None and full["evidence_refs"] is None
    assert full["relative_offset_seconds"] is None and full["lifecycle"] is None
    assert full["record_id"] is None and full["ledger_seq"] is None
    assert full["input_snapshot"] in failed_run.input_artifact_refs
    assert full["runtime"] == {"runtime_id": "synthetic-api-test"}
    assert full["prompt_artifact_ref"] == failed_run.prompt_artifact_ref
    assert full["schema_artifact_ref"] == failed_run.schema_artifact_ref
    assert full["record_kind"] == "replay" and full["is_synthetic"] is True
    last_known = full["status_projection"]["last_known"]
    assert last_known["state"] == "valid"
    assert last_known["origin_judgement_id"] == prior_output.judgement_id
    assert last_known["forecast"]["status"] == "KNOWN"
    assert last_known["forecast"]["predicted_start"] is not None
    assert last_known["forecast"]["reason"] == "Explicit offline fixture has no future time evidence."
    assert last_known["forecast"]["evidence_post_ids"] == ["synthetic-api-valid-target-evidence"]
    assert last_known["forecast"]["relative_offset_seconds"] == 3600
    assert full["status_projection"]["run"]["run_id"] == failed_run.run_id
    assert full["status_projection"]["run"]["attempt_id"] == failed_attempt.attempt_id
    prior_history_line = next(
        item for item in client.get("/api/v2/predictions/history").json()["items"]
        if item["target"] == target and item["reason"] == "Explicit offline fixture has no future time evidence."
    )
    assert prior_history_line["reason"] == "Explicit offline fixture has no future time evidence."
    assert after_hash == before_hash


@pytest.mark.parametrize("change", ["input", "cycle"])
def test_real_ledger_timeout_hides_prior_forecast_after_input_or_cycle_change(client, change):
    database = client.app.state.database
    ledger = client.app.state.prediction_ledger
    _append_synthetic_unknown_output(database, ledger, known_target="EXTRA_FULL", future_validity=True)
    if change == "input":
        database.upsert_posts_detailed([{
            "tweet_id": "synthetic-api-valid-target-evidence",
            "text": "Changed synthetic evidence invalidates the prior judgement.",
            "posted_at": utc_text(datetime.now(UTC) - timedelta(minutes=1)),
            "source": "synthetic-api-test",
        }])
        expected_reasons = {"INPUT_CHANGED", "INPUT_SNAPSHOT_CHANGED", "QUESTION_VERSION_CHANGED"}
    else:
        database.upsert_reset_event({
            "event_key": "synthetic-api-cycle-change-anchor",
            "event_type": "FULL_RESET",
            "occurred_at": utc_text(datetime.now(UTC) - timedelta(minutes=1)),
            "title": "Synthetic Full anchor changing the cycle",
            "summary": "Offline cycle-change fixture only.",
            "time_basis": "explicit_text",
            "scope": "all_paid",
            "execution_stage": "completed",
            "evidence_post_ids": [],
            "provenance": {"time_form": "point", "time_precision": "second", "source_timezone": "UTC"},
        }, is_synthetic=True)
        expected_reasons = {"CYCLE_CHANGED", "QUESTION_VERSION_CHANGED"}
    failed_run, failed_attempt = _begin_synthetic_attempt(database, ledger)
    ledger.append_attempt_event(
        failed_run.run_id, failed_attempt.attempt_id, "timeout", failure_terminal=True,
        reason_code="TIMEOUT", attempt_finished_at=utc_text(), output_available_at=None,
    )
    before_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()

    full = client.get("/api/v2/radar").json()["prediction"]["lines"]["EXTRA_FULL"]

    after_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()
    last_known = full["status_projection"]["last_known"]
    assert full["state"] == "timeout"
    assert full["forecast_id"] is None and full["predicted_start"] is None
    assert last_known["state"] != "valid"
    assert last_known["reason_code"] in expected_reasons
    assert "forecast" not in last_known
    assert full["status_projection"]["run"]["run_id"] == failed_run.run_id
    assert full["status_projection"]["run"]["attempt_id"] == failed_attempt.attempt_id
    assert after_hash == before_hash


def test_partial_projection_keeps_targets_independent_and_preserves_date_envelope(monkeypatch, client):
    _install_healthy_projection(monkeypatch, client)

    response = client.get("/api/v2/radar")
    assert response.status_code == 200
    prediction = response.json()["prediction"]

    assert prediction["state"] == "partial"
    assert prediction["lines"]["EXTRA_FULL"]["current_advice_eligible"] is True
    assert prediction["lines"]["BANKED"]["state"] == "rejected"
    assert prediction["lines"]["BANKED"]["current_advice_eligible"] is False
    assert prediction["lines"]["NORMAL_WEEKLY"]["date_boundaries"] == (
        "closed_conservative_local_day_envelope_not_execution_instants"
    )
    assert prediction["health"]["current_collector_health"]["profile_monitor"]["reason"] == "FRESH"
    assert prediction["health"]["generation_data_health"] == "HEALTHY"


def test_missing_prediction_capabilities_are_treated_as_empty_object(monkeypatch, client):
    _install_healthy_projection(monkeypatch, client)
    ledger = client.app.state.prediction_ledger
    raw = {
        "capabilities": None,
        "health": {"state": "partial", "reason": "OPTIONAL_CAPABILITIES_OMITTED"},
        "lines": {
            "NORMAL_WEEKLY": _line("baseline"),
            "EXTRA_FULL": _line("ready"),
            "BANKED": _line("rejected", reason="MISSING_TARGET"),
        },
    }
    monkeypatch.setattr(ledger, "prediction_lines", lambda _judgement, *, as_of: raw, raising=False)

    response = client.get("/api/v2/radar")

    assert response.status_code == 200
    prediction = response.json()["prediction"]
    assert prediction["capabilities"]["extra_full"] is True
    assert prediction["capabilities"]["banked"] is True
    assert prediction["capabilities"]["history"] is True
    assert prediction["lines"]["BANKED"]["state"] == "rejected"


def test_maps_prediction_ledger_line_fields_at_the_api_boundary(monkeypatch, client):
    _install_healthy_projection(monkeypatch, client)
    ledger = client.app.state.prediction_ledger
    raw = {
        "capabilities": {"model_targets": ["EXTRA_FULL", "BANKED"], "normal_history": True, "history_lines": True,
                         "output_availability": "observed_upper_bound_or_null", "writes_on_read": False},
        "lines": {
            "NORMAL_WEEKLY": {"status": "KNOWN", "baseline_status": "baseline", "valid": True,
                              "validation_reason": "VALID", "prediction_form": "date", "expression": "2026-10-10",
                              "date_boundaries": "closed_conservative_local_day_envelope_not_execution_instants",
                              "predicted_start": "2026-10-10T00:00:00Z", "predicted_end": "2026-10-11T00:00:00Z",
                              "anchor_limitation": "POST_TIME_PROXY_NOT_ACTUAL_START", "anchor_time_basis": "post_time_proxy",
                              "scope": {"value": "unknown", "certainty": "not_established_by_ledger"}},
            "EXTRA_FULL": {"status": "KNOWN", "valid": True, "validation_reason": "VALID",
                           "current_or_last_known": "current", "prediction_form": "start_only",
                           "resolved_prediction_form": "point",
                           "predicted_start": "2026-10-10T10:00:00Z", "predicted_end": None,
                           "output_available_at": "2026-10-09T08:15:00Z",
                           "output_available_at_source": "ledger_observed_after_commit", "method": "model_inference",
                           "origin_judgement_id": 77},
            "BANKED": {"status": "UNKNOWN", "valid": False, "validation_reason": "UNKNOWN_REASON_MISSING",
                       "current_or_last_known": "unavailable", "prediction_form": "unknown",
                       "unresolved_reason": "没有独立前瞻依据。"},
        },
    }
    monkeypatch.setattr(ledger, "prediction_lines", lambda _judgement, *, as_of: raw, raising=False)

    prediction = client.get("/api/v2/radar").json()["prediction"]

    assert prediction["lines"]["EXTRA_FULL"]["state"] == "current"
    assert prediction["lines"]["EXTRA_FULL"]["current_advice_eligible"] is True
    assert prediction["lines"]["EXTRA_FULL"]["form"] == "point"
    assert prediction["lines"]["EXTRA_FULL"]["predicted_end"] is None
    assert prediction["lines"]["EXTRA_FULL"]["output_availability_kind"] == "ledger_observed_after_commit"
    assert prediction["lines"]["EXTRA_FULL"]["updated_at"] == "2026-10-09T00:00:00Z"
    assert prediction["lines"]["EXTRA_FULL"]["updated_at_source"] == "judgement_time"
    assert prediction["lines"]["NORMAL_WEEKLY"]["anchor_limitation"] == "POST_TIME_PROXY_NOT_ACTUAL_START"
    assert prediction["lines"]["NORMAL_WEEKLY"]["scope"]["value"] == "unknown"
    assert prediction["lines"]["BANKED"]["state"] == "rejected"
    assert prediction["capabilities"]["history"] is True
    assert prediction["capabilities"]["extra_full"] is True


def test_expiry_and_missing_target_precede_unknown_but_valid_model_unknown_survives(monkeypatch, client):
    _install_healthy_projection(monkeypatch, client)
    ledger = client.app.state.prediction_ledger
    raw = {
        "capabilities": {"model_targets": ["EXTRA_FULL", "BANKED"]},
        "lines": {
            "NORMAL_WEEKLY": {"status": "KNOWN", "baseline_status": "expired", "valid": False,
                              "validation_reason": "EXPIRED", "prediction_form": "proxy"},
            "EXTRA_FULL": {"state": "ready", "status": "UNKNOWN", "valid": False, "validation_reason": "EXPIRED",
                           "current_or_last_known": "current", "prediction_form": "unknown"},
            "BANKED": {"status": "UNKNOWN", "valid": False, "validation_reason": "MISSING_TARGET",
                       "current_or_last_known": "unavailable", "prediction_form": "unknown"},
        },
    }
    monkeypatch.setattr(ledger, "prediction_lines", lambda _judgement, *, as_of: raw, raising=False)

    lines = client.get("/api/v2/radar").json()["prediction"]["lines"]

    assert lines["NORMAL_WEEKLY"]["state"] == "expired"
    assert lines["EXTRA_FULL"]["state"] == "expired"
    assert lines["BANKED"]["state"] == "rejected"

    raw["lines"]["EXTRA_FULL"].update(
        valid=True, validation_reason="VALID", current_or_last_known="current", state="ready",
        validity={"state": "valid"},
    )
    lines = client.get("/api/v2/radar").json()["prediction"]["lines"]
    assert lines["EXTRA_FULL"]["state"] == "unknown"
    assert lines["EXTRA_FULL"]["current_advice_eligible"] is False


def test_expired_global_judgement_does_not_make_old_full_forecast_current(monkeypatch, client):
    _install_healthy_projection(monkeypatch, client, validation={"valid": False, "reason": "EXPIRED"})

    prediction = client.get("/api/v2/radar").json()["prediction"]

    assert prediction["lines"]["EXTRA_FULL"]["state"] == "stale"
    assert prediction["lines"]["EXTRA_FULL"]["current_advice_eligible"] is False
    # Normal is a non-official reference and does not inherit Judge validation failure.
    assert prediction["lines"]["NORMAL_WEEKLY"]["state"] == "baseline"
    assert prediction["lines"]["NORMAL_WEEKLY"]["current_advice_eligible"] is True


def test_history_is_read_only_preserves_ledger_order_and_reports_truncation(monkeypatch, client):
    calls: list[dict] = []
    rows = [
        {"target": "EXTRA_FULL", "series_id": "series-a", "revision": 4,
         "question_version": "question-4", "question_revision": 4,
         "output_revision": output_revision, "target_output_id": f"judgement-{10 + output_revision}:EXTRA_FULL",
         "forecast_id": "question-4", "state": "current", "status": "KNOWN", "valid": True,
         "current_or_last_known": "current", "form": form, "method": method,
         "predicted_start": predicted_start, "prompt_text": "must not leak"}
        for output_revision, form, method, predicted_start in (
            (1, "point", "model_inference", "2026-10-11T10:00:00Z"),
            (2, "range", "official_time_extraction", "2026-10-12T10:00:00Z"),
        )
    ]

    def history(*, target, series_id, limit):
        calls.append({"target": target, "series_id": series_id, "limit": limit})
        return {
            "state": "ready",
            "target": target,
            "series_id": series_id,
            "items": rows,
            "total_count": 12,
            "truncated": True,
            "attempts": [{"target": target, "series_id": series_id, "attempt_number": 2,
                          "state": "rejected", "reason_code": "MISSING_TARGET", "reason": "target output missing",
                          "run_context": "must not leak"}],
        }

    ledger = client.app.state.prediction_ledger
    monkeypatch.setattr(ledger, "prediction_history", history, raising=False)
    before = client.app.state.database.counts()

    response = client.get("/api/v2/predictions/history?target=EXTRA_FULL&series_id=series-a&limit=2")

    assert response.status_code == 200
    assert [row["question_revision"] for row in response.json()["items"]] == [4, 4]
    assert [row["question_version"] for row in response.json()["items"]] == ["question-4", "question-4"]
    assert [row["output_revision"] for row in response.json()["items"]] == [1, 2]
    assert [row["target_output_id"] for row in response.json()["items"]] == [
        "judgement-11:EXTRA_FULL", "judgement-12:EXTRA_FULL"
    ]
    assert [row["form"] for row in response.json()["items"]] == ["point", "range"]
    assert [row["method"] for row in response.json()["items"]] == ["model_inference", "official_time_extraction"]
    assert all("prompt_text" not in row for row in response.json()["items"])
    assert response.json()["total_count"] == 12
    assert response.json()["truncated"] is True
    assert [row["output_revision"] for row in response.json()["items"]] == [1, 2]
    assert response.json()["attempts"][0]["reason_code"] == "MISSING_TARGET"
    assert all(item["status_projection"]["result"]["state"] == "accepted" for item in response.json()["items"])
    assert all(item["state"] == "current" for item in response.json()["items"])
    assert "run_context" not in response.text
    assert calls == [{"target": "EXTRA_FULL", "series_id": "series-a", "limit": 2}]
    assert client.app.state.database.counts() == before
    assert client.app.state.pipeline is None


def test_history_rejects_unknown_target(client):
    response = client.get("/api/v2/predictions/history?target=UNRELATED&series_id=series-a")

    assert response.status_code == 422


def test_history_api_does_not_decode_or_expose_raw_ledger_rows(monkeypatch, client):
    ledger = client.app.state.prediction_ledger
    monkeypatch.setattr(
        ledger,
        "prediction_history",
        lambda **_kwargs: {"items": [{"seq": 9, "kind": "output_committed", "payload": {"private": "not rendered"}}]},
        raising=False,
    )

    response = client.get("/api/v2/predictions/history?target=EXTRA_FULL&series_id=series-a")

    assert response.status_code == 200
    assert response.json()["state"] == "not_implemented"
    assert response.json()["items"] == []
    assert response.json()["attempts"] == []
    assert "payload" not in response.text


def test_truncated_history_uses_real_ledger_boundary_dtos(client):
    database = client.app.state.database
    ledger = client.app.state.prediction_ledger
    outputs = [_append_synthetic_unknown_output(database, ledger) for _ in range(3)]
    series_id = outputs[0][0].target_refs["EXTRA_FULL"]["series_id"]

    response = client.get(
        f"/api/v2/predictions/history?target=EXTRA_FULL&series_id={series_id}&limit=2"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count_known"] is True
    assert body["total_count"] == 3
    assert body["truncated"] is True
    assert [item["output_revision"] for item in body["items"]] == [2, 3]
    assert [item["output_revision"] for item in body["first_items"]] == [1]
    assert [item["output_revision"] for item in body["last_items"]] == [3]
    assert body["first_items"][0]["question_revision"] == body["last_items"][0]["question_revision"]
    assert body["first_items"][0]["target_output_id"] == f"{outputs[0][1].judgement_id}:EXTRA_FULL"
    assert body["last_items"][0]["target_output_id"] == f"{outputs[-1][1].judgement_id}:EXTRA_FULL"
    assert all(item["is_synthetic"] is True for item in [*body["first_items"], *body["last_items"]])
    assert all("payload" not in item and "payload_json" not in item for item in [*body["items"], *body["first_items"], *body["last_items"]])


def test_malformed_status_projection_fails_closed_at_radar_boundary(monkeypatch, client):
    _install_healthy_projection(monkeypatch, client)
    ledger = client.app.state.prediction_ledger
    malformed = {
        "target": "EXTRA_FULL", "state": "current", "status": "KNOWN", "valid": True,
        "form": "point", "predicted_start": "2026-10-10T10:00:00Z",
        "status_projection": {
            "capability": {"implementation": "supported", "source": "ledger_v2"},
            "run": {"state": "failed", "run_id": "run-x", "attempt_id": "attempt-x", "finished_at": None},
            "result": {"state": "accepted", "reason_code": "VALID", "summary": None},
            "history_status": "backfilled", "last_known": None,
        },
    }
    raw = ledger.prediction_lines

    def broken_projection(_judgement, *, as_of):
        value = raw(None, as_of=as_of)
        return {
            **value,
            "lines": {"NORMAL_WEEKLY": {}, "EXTRA_FULL": malformed, "BANKED": {}},
            "capabilities": {"model_targets": ["EXTRA_FULL", "BANKED"]},
        }

    monkeypatch.setattr(ledger, "prediction_lines", broken_projection, raising=False)
    line = client.get("/api/v2/radar").json()["prediction"]["lines"]["EXTRA_FULL"]

    assert line["state"] == "unavailable"
    assert line["status_projection"]["capability"]["source"] == "contract_error"
    assert line["status_projection"]["result"]["state"] == "unavailable"
    assert line["predicted_start"] is None and line["form"] == "unknown"
    assert line["origin_judgement_id"] is None


def test_malformed_status_projection_fails_closed_at_history_boundary(monkeypatch, client):
    ledger = client.app.state.prediction_ledger
    item = {
        "target": "EXTRA_FULL", "series_id": "series-a", "forecast_id": "question-a",
        "question_version": "question-a", "question_revision": 1, "revision": 1,
        "origin_judgement_id": 7, "state": "current", "status": "KNOWN", "valid": True,
        "form": "point", "predicted_start": "2026-10-10T10:00:00Z",
        "status_projection": {
            "capability": {"implementation": "supported", "source": "ledger_v2"},
            "run": {"state": "failed", "run_id": "run-a", "attempt_id": "attempt-a", "finished_at": None},
            "result": {"state": "accepted", "reason_code": "VALID", "summary": None},
            "history_status": "backfilled", "last_known": None,
        },
    }
    monkeypatch.setattr(ledger, "prediction_history", lambda **_kwargs: {
        "state": "ready", "target": "EXTRA_FULL", "series_id": "series-a",
        "item_schema": "prediction-history-line-v1", "capabilities": {"history_lines": True},
        "items": [item], "attempts": [], "total_count": 1, "truncated": False,
    }, raising=False)

    response = client.get("/api/v2/predictions/history?target=EXTRA_FULL&series_id=series-a")

    line = response.json()["items"][0]
    assert line["state"] == "unavailable"
    assert line["status_projection"]["capability"]["source"] == "contract_error"
    assert line["status_projection"]["result"]["state"] == "unavailable"
    assert line["forecast_id"] is None and line["predicted_start"] is None
    assert line["origin_judgement_id"] is None and line["form"] == "unknown"


@pytest.mark.parametrize(("event_type", "expected_state", "reason_code"), [
    ("timeout", "timeout", "TIMEOUT"),
    ("cancelled", "cancelled", "CANCELLED"),
    ("http_failure", "failed", "HTTP_FAILURE"),
    ("recovered_terminal_unknown", "unknown_terminal", "TERMINAL_UNKNOWN"),
])
def test_real_ledger_terminal_states_reach_radar_and_history_without_get_writes(
    client, event_type, expected_state, reason_code,
):
    database = client.app.state.database
    ledger = client.app.state.prediction_ledger
    _append_synthetic_unknown_output(database, ledger, expired_validity=True)
    failed_run, failed_attempt = _begin_synthetic_attempt(database, ledger)
    ledger.append_attempt_event(
        failed_run.run_id, failed_attempt.attempt_id, event_type, failure_terminal=True,
        reason_code=reason_code, attempt_finished_at=utc_text(), output_available_at=None,
    )
    before_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()
    with database.connect() as connection:
        before_rows = connection.execute("SELECT count(*) FROM prediction_ledger").fetchone()[0]

    radar = client.get("/api/v2/radar").json()["prediction"]
    history = client.get("/api/v2/predictions/history").json()

    with database.connect() as connection:
        after_rows = connection.execute("SELECT count(*) FROM prediction_ledger").fetchone()[0]
    after_hash = hashlib.sha256(database.path.read_bytes()).hexdigest()
    assert after_rows == before_rows and after_hash == before_hash
    for target in ("EXTRA_FULL", "BANKED"):
        line = radar["lines"][target]
        status_projection = line["status_projection"]
        assert line["state"] == expected_state
        assert status_projection["run"]["state"] == expected_state
        assert status_projection["run"]["run_id"] == failed_run.run_id
        assert status_projection["run"]["attempt_id"] == failed_attempt.attempt_id
        assert status_projection["result"]["state"] == "not_returned"
        assert line["predicted_start"] is None and line["origin_judgement_id"] is None
        assert status_projection["last_known"] is not None
        assert status_projection["last_known"]["state"] == "expired"
        assert "forecast" not in status_projection["last_known"]
    failed_history_attempts = [item for item in history["attempts"] if item["run_id"] == failed_run.run_id]
    assert {item["target"] for item in failed_history_attempts} == {"EXTRA_FULL", "BANKED"}
    assert {item["attempt_id"] for item in failed_history_attempts} == {failed_attempt.attempt_id}
    assert {item["state"] for item in failed_history_attempts} == {event_type}
    assert {item["reason_code"] for item in failed_history_attempts} == {reason_code}
    assert history["attempt_count"] == len(history["attempts"])
    assert history["attempt_count_basis"] == "target_projection_not_http_count"
    assert all("status_projection" in item for item in history["items"])
