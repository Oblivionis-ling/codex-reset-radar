from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.db import Database, SCHEMA_SQL
from app.prediction_ledger import PredictionLedger, _safe_last_known, normalize_prediction_status_projection


def _schema7_legacy_database(tmp_path):
    path = tmp_path / "legacy-schema7.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_SQL)
        connection.execute("PRAGMA user_version=7")
        connection.execute(
            """INSERT INTO radar_judgements(
                created_at,action_level,horizon_24h,horizon_48h,horizon_72h,
                data_health,reason_summary,evidence_post_ids,special_event_ids,model,prompt_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "2026-10-09T00:00:00Z", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN",
                "UNKNOWN", "legacy schema-7 row", "[]", "[]", "legacy", "v2-legacy",
            ),
        )
    return Database(path), {
        "id": 1,
        "created_at": "2026-10-09T00:00:00Z",
        "prompt_version": "v2-legacy",
        "valid_until": None,
    }


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_schema7_legacy_row_is_not_used_to_infer_modern_banked_result_or_write_on_get(tmp_path):
    database, judgement = _schema7_legacy_database(tmp_path)
    ledger = PredictionLedger(database)
    before = _sha256(database.path)

    projection = ledger.prediction_lines(judgement, as_of="2026-10-09T00:01:00Z")

    assert projection["lines"]["BANKED"]["validation_reason"] != "LEGACY_TARGET_NOT_IMPLEMENTED"
    assert projection["lines"]["BANKED"]["status_projection"]["capability"]["source"] == "legacy_undeclared"
    assert projection["lines"]["BANKED"]["status_projection"]["result"]["state"] == "legacy_missing"
    assert projection["lines"]["BANKED"]["status_projection"]["run"]["state"] == "not_started"
    assert _sha256(database.path) == before


def test_modern_capability_is_not_inferred_from_accepted_output_presence(tmp_path):
    from test_prediction_ledger import _database

    database, _ = _database(tmp_path)
    projection = PredictionLedger(database).prediction_lines(None)

    assert projection["capabilities"]["model_targets"] == ["EXTRA_FULL", "BANKED"]
    for target in ("EXTRA_FULL", "BANKED"):
        status = projection["lines"][target]["status_projection"]
        assert status["capability"]["implementation"] == "supported"
        assert status["run"]["state"] == "not_started"
        assert status["result"]["state"] == "not_attempted"


def _status_projection(**overrides):
    projection = {
        "capability": {"implementation": "supported", "source": "ledger_v2"},
        "run": {
            "state": "succeeded", "run_id": "run-current", "attempt_id": "attempt-current",
            "finished_at": "2026-10-09T00:01:00Z", "reason_code": None,
        },
        "result": {"state": "accepted", "reason_code": "VALID", "summary": None},
        "history_status": "backfilled",
        "last_known": None,
    }
    projection.update(overrides)
    return projection


def _legacy_success_line(projection):
    return {
        "target": "EXTRA_FULL", "state": "known", "status": "KNOWN", "valid": True,
        "record_id": "legacy-output", "status_projection": projection,
    }


@pytest.mark.parametrize("projection", [
    None,
    "accepted",
    {"capability": [], "run": {}, "result": {}, "history_status": "backfilled", "last_known": None},
    {**_status_projection(), "result": {"state": "accepted", "reason_code": 14, "summary": None}},
    {**_status_projection(), "history_status": "complete"},
    {**_status_projection(), "capability": {"implementation": "supported", "source": "corrupt_source"}},
])
def test_present_malformed_projection_fails_closed_instead_of_falling_back_to_legacy_success(projection):
    status = normalize_prediction_status_projection(_legacy_success_line(projection), target="EXTRA_FULL")

    assert status["capability"]["source"] == "contract_error"
    assert status["run"]["state"] == "unknown_terminal"
    assert status["result"]["state"] == "unavailable"
    assert status["result"]["reason_code"] == "PREDICTION_STATUS_CONTRACT_ERROR"
    assert status["last_known"] is None


@pytest.mark.parametrize("run_state,result_state", [
    ("pending", "accepted"),
    ("failed", "accepted"),
    ("not_started", "accepted"),
    ("succeeded", "not_attempted"),
])
def test_projection_run_result_contradictions_fail_closed_even_when_outer_line_looks_accepted(run_state, result_state):
    projection = _status_projection(
        run={"state": run_state, "run_id": "run-current" if run_state != "not_started" else None,
             "attempt_id": "attempt-current" if run_state != "not_started" else None,
             "finished_at": None, "reason_code": None},
        result={"state": result_state, "reason_code": "VALID", "summary": None},
    )

    status = normalize_prediction_status_projection(_legacy_success_line(projection), target="EXTRA_FULL")

    assert status["capability"]["source"] == "contract_error"
    assert status["result"]["state"] == "unavailable"


def test_absent_projection_remains_boundary_compatible_but_never_claims_modern_capability():
    line = {key: value for key, value in _legacy_success_line(None).items() if key != "status_projection"}

    status = normalize_prediction_status_projection(line, target="EXTRA_FULL")

    assert status["result"]["state"] == "accepted"
    assert status["capability"] == {"implementation": "unknown", "source": "unknown"}


def test_safe_last_known_exposes_forecast_only_when_original_state_is_valid():
    forecast = {"status": "KNOWN", "prediction_form": "point", "predicted_start": "2026-10-10T00:00:00Z"}
    valid = _safe_last_known({"state": "valid", "forecast": forecast, "forecast_id": "f-1"})
    expired = _safe_last_known({"state": "expired", "forecast_id": "f-1"})

    assert valid["forecast"]["predicted_start"] == forecast["predicted_start"]
    assert "forecast" not in expired
    assert _safe_last_known({"state": "expired", "forecast": forecast}) is None


def test_bad_last_known_dimension_turns_the_projection_into_contract_error():
    projection = _status_projection(last_known={"state": "expired", "forecast": {"predicted_start": "2026-10-10"}})

    status = normalize_prediction_status_projection(_legacy_success_line(projection), target="EXTRA_FULL")

    assert status["capability"]["source"] == "contract_error"
    assert status["result"]["state"] == "unavailable"


def test_normal_helper_reference_does_not_require_model_run_success():
    status = normalize_prediction_status_projection({
        "target": "NORMAL_WEEKLY",
        "status_projection": {
            "capability": {"implementation": "supported", "source": "ledger_v2"},
            "run": {"state": "not_started", "run_id": None, "attempt_id": None, "finished_at": None, "reason_code": None},
            "result": {"state": "accepted", "reason_code": "VALID", "summary": None},
            "history_status": "backfilled",
            "last_known": None,
            "normal": {"helper_status": "baseline", "calculation_status": "calculated"},
        },
    }, target="NORMAL_WEEKLY")

    assert status["capability"]["source"] == "ledger_v2"
    assert status["run"]["state"] == "not_started"
    assert status["result"]["state"] == "accepted"
    assert status["normal"]["calculation_status"] == "calculated"
