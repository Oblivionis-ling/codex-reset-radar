from __future__ import annotations

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


def _append_synthetic_unknown_output(database, ledger):
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
    judged_at = utc_now()
    result = {
        "created_at": judged_at,
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
        "valid_until": judged_at,
        "raw": {"synthetic": True},
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
    assert payload["prediction"]["state"] == "not_implemented"
    assert set(payload["prediction"]["lines"]) == {"NORMAL_WEEKLY", "EXTRA_FULL", "BANKED"}
    assert payload["prediction"]["lines"]["NORMAL_WEEKLY"]["state"] == "not_backfilled"
    assert all(payload["prediction"]["lines"][target]["state"] == "not_implemented" for target in ("EXTRA_FULL", "BANKED"))
    assert payload["prediction"]["capabilities"]["history"] is True
    assert "NOT_BACKFILLED" in payload["prediction"]["lines"]["NORMAL_WEEKLY"]["reason"]
    assert client.app.state.database.counts() == before
    assert client.app.state.pipeline is None


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
