from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import socket
import smtplib
import sqlite3

import httpx
import pytest

from app.prediction_scoring import (
    ALGORITHM_VERSION, METHODS, ScoringContractError, availability_from_output,
    classify_error, evaluate_review, freeze_evaluation_set, interval_metrics, select_candidate, verify_assessment,
)
from app.review_common import canonical_bytes, sha256_json
from app.review_reader import freeze_review, record_digest


@pytest.fixture(autouse=True)
def no_network_or_notifications(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("scoring tests forbid network and notifications")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
    for name in ("SMTP", "SMTP_SSL", "LMTP"):
        monkeypatch.setattr(smtplib, name, blocked)


def at(hours: float) -> str:
    return (datetime(2026, 10, 1, tzinfo=UTC) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def seal(row):
    row = copy.deepcopy(row)
    row["record_sha256"] = record_digest(row)
    return row


def truth(identifier="truth-1", *, event="event-1", start=0, end=0, synthetic=True, target="EXTRA_FULL", scope="all_paid"):
    return seal({"id": identifier, "event_id": event, "actual_start": at(start), "actual_start_end": at(end),
                 "actual_precision": "minute", "actual_time_basis": "synthetic_trusted_fixture" if synthetic is True else "verified_execution_start",
                 "truth_status": "fixture_adjudicated" if synthetic is True else "ADJUDICATED",
                 "actual_event_type": "FULL_RESET" if target == "EXTRA_FULL" else "SPECIAL_RESET", "special_type": None if target == "EXTRA_FULL" else "BANKED",
                 "scope": scope, "is_synthetic": synthetic})


def forecast(identifier="forecast-1", *, start=0, end=0, form="range", method="model_inference", synthetic=True,
             target="EXTRA_FULL", scope="all_paid", unknown=False, record_kind="online", series="series-1"):
    return seal({"id": identifier, "forecast_id": identifier, "series_id": series, "event_id": "known-anchor-not-actual-event",
                 "record_kind": record_kind, "status": "UNKNOWN" if unknown else "KNOWN", "method": method, "target": target,
                 "scope": scope, "prediction_form": "unknown" if unknown else form, "predicted_start": None if unknown or start is None else at(start),
                 "predicted_end": None if unknown or end is None else at(end), "is_synthetic": synthetic})


def output(identifier="output-1", fid="forecast-1", *, available=-2, kind="exact", synthetic=True, accepted=True):
    return seal({"id": identifier, "output_id": identifier, "forecast_id": fid,
                 "validation_status": "accepted" if accepted else "rejected", "status": "accepted" if accepted else "rejected",
                 "output_available_at": at(available) if available is not None else None,
                 "availability_source": "synthetic_exact_fixture" if kind == "exact" and synthetic is True else "formal_commit_exact" if kind == "exact" else "formal_read_post_commit_upper_bound" if kind == "observed_upper_bound" else None,
                 "is_synthetic": synthetic})


def candidate(identifier, *, hour=-2, kind="exact", unknown=False, start=0, end=0):
    return {"id": identifier, "prediction": {"state": "unknown" if unknown else "known", "interval": [start, end], "reason_codes": []},
            "availability": {"kind": kind, "at": at(hour) if hour is not None else None, "source": "test", "reason_codes": []}}


def normalized_truth(start=0, end=0, missing=False):
    # Use the public adapter through a one-event evaluation where needed; these
    # candidates exercise the pure ordering function's documented normalized DTO.
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    def us(h):
        d = datetime.fromisoformat(at(h).replace("Z", "+00:00")) - epoch
        return (d.days * 86400 + d.seconds) * 1_000_000 + d.microseconds
    return {"trusted": not missing, "interval": None if missing else [us(start), us(end)], "reason_codes": ["missing_truth"] if missing else []}


def review_fixture(*, forecasts=None, outputs=None, truths=None):
    return {"forecasts": [forecast()] if forecasts is None else forecasts,
            "outputs": [output()] if outputs is None else outputs,
            "truth_revisions": [truth()] if truths is None else truths,
            "evaluation_sets": [], "assessments": [],
            "source_binding": {"snapshot_id": "fixture-snapshot", "source_sha256": sha256_json({"fixture_snapshot": 1}), "freeze_at": at(240), "high_water": 50, "binding_version": "crr-review-source-binding-v1"},
            "package_binding": {"source_package_sha256": sha256_json({"fixture_package": 1}), "manifest_sha256": sha256_json({"fixture_manifest": 1})}}


def definition(*, events=None):
    return {"id": "fixed-set-1", "observation_cutoff_at": at(200), "coverage": {"status": "partial", "start": at(-48), "end": at(200)},
            "rules": {"inclusion": "pre_registered_event_ids", "exclusion": "none", "deduplication": "target_event_id", "adjudication_version": "fixture-review-v1"},
            "events": [{"actual_event_id": "event-1", "target": "EXTRA_FULL", "scope": "all_paid", "association_status": "confirmed",
                        "truth_ref": {"target": "truth_revisions", "id": "truth-1"}, "forecast_ids": ["forecast-1"]}] if events is None else events}


def evaluate(review=None, spec=None):
    review = review_fixture() if review is None else review
    frozen = freeze_evaluation_set(review, definition() if spec is None else spec, review["source_binding"])
    return frozen, evaluate_review(review, frozen)


def panel(result, *, method="model_inference", boundary="first", threshold=24, target="EXTRA_FULL", provenance="SYNTHETIC"):
    return next(row for row in result["panels"] if (row["method"], row["boundary"], row["threshold_hours"], row["target"], row["provenance"]) == (method, boundary, threshold, target, provenance))


@pytest.mark.parametrize("actual,predicted,expected24,expected48", [
    ((0, 0), (-1, 1), "definite_hit", "definite_hit"),
    ((0, 0), (-48, 48), "error_indeterminate", "definite_hit"),
    ((0, 0), (24, 24), "definite_hit", "definite_hit"),
    ((0, 0), (25, 25), "definite_miss", "definite_hit"),
    ((0, 0), (23, 25), "error_indeterminate", "definite_hit"),
    ((0, 2), (25, 25), "error_indeterminate", "definite_hit"),
])
def test_s1_math_and_range_truth(actual, predicted, expected24, expected48):
    metrics = interval_metrics(predicted, actual)
    assert classify_error(metrics, 24) == expected24
    assert classify_error(metrics, 48) == expected48
    if actual == (0, 2):
        assert (metrics["e_min_hours"], metrics["e_max_hours"]) == (23, 25)


@pytest.mark.parametrize("predicted,expected", [((-1, 3), "definitely_covered"), ((3, 4), "definitely_not_covered"), ((1, 3), "coverage_indeterminate")])
def test_coverage_is_not_accuracy(predicted, expected):
    assert interval_metrics(predicted, (0, 2))["coverage"] == expected


@pytest.mark.parametrize("invalid", [(float("nan"), 1), (0, float("inf")), (2, 1), (None, 0), (False, 1), (0,)])
def test_invalid_intervals_are_not_fixed(invalid):
    with pytest.raises(ScoringContractError):
        interval_metrics(invalid, (0, 0))


@pytest.mark.parametrize("hour,start,end,expected", [(0, 0, 0, "no_prediction"), (1, 0, 2, "undetermined"), (2, 0, 2, "no_prediction"), (-1, 0, 2, "selected")])
def test_exact_pre_post_and_start_boundary(hour, start, end, expected):
    assert select_candidate([candidate("a", hour=hour)], normalized_truth(start, end), "first")["status"] == expected


def test_upper_bound_never_proves_post_event_or_orders_other_upper_bound():
    assert select_candidate([candidate("a", hour=5, kind="observed_upper_bound")], normalized_truth(), "first")["status"] == "undetermined"
    assert select_candidate([candidate("a", hour=-2, kind="observed_upper_bound")], normalized_truth(), "first")["status"] == "selected"
    rows = [candidate("a", hour=-10, kind="observed_upper_bound"), candidate("b", hour=-2, kind="observed_upper_bound")]
    for boundary in ("first", "last"):
        assert select_candidate(rows, normalized_truth(), boundary, ["a", "b"])["status"] == "undetermined"


def test_missing_candidate_and_range_candidate_affect_only_provable_panel():
    rows = [candidate("a", hour=-2), candidate("b", hour=1)]
    assert select_candidate(rows, normalized_truth(0, 2), "first")["selected"]["id"] == "a"
    assert select_candidate(rows, normalized_truth(0, 2), "last")["status"] == "undetermined"
    rows.append(candidate("missing", hour=None, kind="missing"))
    for boundary in ("first", "last"):
        assert select_candidate(rows, normalized_truth(0, 2), boundary)["status"] == "undetermined"


def test_first_unknown_cannot_skip_later_hit_and_ties_require_frozen_order():
    rows = [candidate("unknown", hour=-10, unknown=True), candidate("hit", hour=-2)]
    assert select_candidate(rows, normalized_truth(), "first")["status"] == "prediction_unknown"
    assert select_candidate(rows, normalized_truth(), "last")["selected"]["id"] == "hit"
    rows[0]["availability"]["at"] = at(-2)
    assert select_candidate(rows, normalized_truth(), "first")["status"] == "undetermined"
    assert select_candidate(rows, normalized_truth(), "first", ["unknown", "hit"])["status"] == "prediction_unknown"


def test_all_unknown_with_missing_truth_but_post_unknown_is_no_prediction():
    rows = [candidate("a", unknown=True)]
    result = select_candidate(rows, normalized_truth(missing=True), "last")
    assert result["status"] == "prediction_unknown" and "missing_truth" in result["reason_codes"]
    rows[0]["availability"]["at"] = at(0)
    assert select_candidate(rows, normalized_truth(), "first")["status"] == "no_prediction"


def test_availability_never_borrows_old_clocks_or_unknown_source():
    row = {"created_at": at(-20), "judgement_as_of": at(-20), "attempt_finished_at": at(-20), "output_available_at": None}
    assert availability_from_output(row)["kind"] == "missing"
    row.update(output_available_at=at(-20), availability_source="not_certified")
    assert availability_from_output(row)["kind"] == "missing"
    row.update(availability_source="formal_read_post_commit_upper_bound")
    assert availability_from_output(row)["kind"] == "observed_upper_bound"
    row["availability_observations"] = [{"clock_anomaly": "wall_clock_reversed", "time_limitation": "timestamps_retained_without_ordering"}]
    value = availability_from_output(row)
    assert value["kind"] == "missing" and {"clock_anomaly", "time_limitation"} <= set(value["reason_codes"])
    assert value["observations"][0]["clock_anomaly"] == "wall_clock_reversed"
    row.update(output_available_at="2026-10-01T00:00:00", availability_observations=[])
    assert availability_from_output(row)["kind"] == "missing"


def test_bound_package_set_truth_and_no_nearest_event():
    review = review_fixture(truths=[truth(), truth("truth-near", event="near", start=1, end=1)])
    frozen, result = evaluate(review)
    row = panel(result)["events"][0]
    assert row["truth_ref"]["id"] == "truth-1"
    assert row["actual_event_id"] == "event-1"
    assert frozen["source_binding"]["high_water"] == 50
    assert result["package_binding"] == review["package_binding"]
    assert result["algorithm_version"] == ALGORITHM_VERSION and result["set_hash"] == frozen["set_hash"]
    assert result["evaluation_set_ref"]["sha256"] == record_digest(frozen)
    assert evaluate_review(review, frozen) == result
    assert canonical_bytes(review) == canonical_bytes(review_fixture(truths=[truth(), truth("truth-near", event="near", start=1, end=1)]))


def test_all_method_panels_keep_same_target_N_and_normal_separate():
    normal = forecast("normal", target="NORMAL_WEEKLY", record_kind="baseline", method=None)
    review = review_fixture(forecasts=[forecast(), normal])
    frozen, result = evaluate(review)
    for row in result["panels"]:
        assert sum(row["counts"].values()) == row["N"]
        assert sum(row["coverage_counts"].values()) == row["N"]
        assert row["N"] == (1 if row["target"] == "EXTRA_FULL" else 0)
    assert panel(result, method="official_time_extraction")["counts"]["no_prediction"] == 1
    assert result["normal"]["history_count"] == len(frozen["normal_refs"]) == 1
    assert panel(result, target="BANKED")["ratios"]["definite_hits_over_N"] is None


@pytest.mark.parametrize("kind", ["missing_truth", "scope", "ambiguous", "retracted", "proxy", "missing_forecast", "missing_output", "missing_field"])
def test_gaps_remain_in_fixed_N(kind):
    review, spec = review_fixture(), definition()
    if kind == "missing_truth":
        review["truth_revisions"] = []
    elif kind == "scope":
        spec["events"][0]["scope"] = "partial_users"
    elif kind == "ambiguous":
        spec["events"][0]["association_status"] = "ambiguous"
    elif kind in {"retracted", "proxy"}:
        review["truth_revisions"][0].update(truth_status="RETRACTED" if kind == "retracted" else "legacy_event_snapshot_not_independently_adjudicated", actual_precision=None)
        review["truth_revisions"][0] = seal(review["truth_revisions"][0])
    elif kind == "missing_forecast":
        review["forecasts"] = []
    elif kind == "missing_output":
        review["outputs"] = []
    else:
        review["forecasts"][0].pop("prediction_form")
        review["forecasts"][0] = seal(review["forecasts"][0])
    _, result = evaluate(review, spec)
    cohort = "UNDECLARED" if kind == "missing_truth" else "SYNTHETIC"
    assert panel(result, provenance=cohort)["N"] == 1
    assert panel(result, provenance=cohort)["events"][0]["category"] == "undetermined"


def test_legal_unknown_priority_not_missing_or_failed():
    review = review_fixture(forecasts=[forecast(unknown=True)], truths=[])
    _, result = evaluate(review)
    row = panel(result, provenance="UNDECLARED")["events"][0]
    # Candidate flags cannot certify an event's missing origin.
    assert row["category"] == "undetermined"
    assert "missing_truth" in row["reason_codes"] and "event_origin_unproven" in row["reason_codes"]
    review = review_fixture(forecasts=[forecast(unknown=True)], truths=[seal({**truth(), "actual_start": None, "actual_start_end": None})])
    _, result = evaluate(review)
    row = panel(result)["events"][0]
    assert row["category"] == "prediction_unknown" and "truth_not_finite_closed_interval" in row["reason_codes"]
    review = review_fixture(forecasts=[forecast(unknown=True)], outputs=[output(accepted=False)])
    _, result = evaluate(review)
    assert panel(result)["events"][0]["category"] == "no_prediction"


def test_provenance_and_replay_are_not_combined_or_guessed():
    events, fs, os, ts = [], [], [], []
    for index, marker in enumerate((True, False, None)):
        fid, tid, eid = f"f{index}", f"t{index}", f"e{index}"
        fs.append(forecast(fid, synthetic=marker))
        os.append(output(f"o{index}", fid, synthetic=marker))
        item = truth(tid, event=eid, synthetic=marker)
        if marker is None:
            item = seal({**item, "source_mode": "legacy_reset_events", "truth_status": "legacy_event_snapshot_not_independently_adjudicated"})
            fs[-1] = seal({**fs[-1], "source_kind": "legacy_forecast"})
            os[-1] = seal({**os[-1], "source_kind": "legacy_output"})
        ts.append(item)
        events.append({"actual_event_id": eid, "target": "EXTRA_FULL", "scope": "all_paid", "association_status": "confirmed", "truth_ref": {"target": "truth_revisions", "id": tid}, "forecast_ids": [fid]})
    _, result = evaluate(review_fixture(forecasts=fs, outputs=os, truths=ts), definition(events=events))
    assert {p["provenance"] for p in result["panels"]} == {"SYNTHETIC", "REAL", "LEGACY_UNDECLARED"}
    assert all(p["N"] == 1 for p in result["panels"] if p["target"] == "EXTRA_FULL")
    _, result = evaluate(review_fixture(forecasts=[forecast(record_kind="replay")]))
    assert panel(result)["events"][0]["category"] == "no_prediction"
    assert "non_online_forecast_excluded" in panel(result)["events"][0]["reason_codes"]


@pytest.mark.parametrize("form,bounds,expected", [("point", None, "definite_hit"), ("start_only", None, "prediction_unknown"), ("relative", None, "prediction_unknown"), ("date", "half_open_local_day_not_execution_instants", "prediction_unknown"), ("date", "closed_conservative_local_day_envelope_not_execution_instants", "definite_hit")])
def test_explicit_point_only_and_date_closed_envelope_contract(form, bounds, expected):
    f = forecast(form=form, end=24 if form == "date" else None)
    if bounds:
        f.update(date_boundaries=bounds, precision="day")
    review = review_fixture(forecasts=[seal(f)])
    _, result = evaluate(review)
    row = panel(result)["events"][0]
    assert row["category"] == expected
    if form == "date" and expected == "definite_hit":
        assert row["metrics"]["prediction_width_hours"] == 24
        assert "conservative_day_envelope_not_execution_instants" in row["reason_codes"]


def test_upper_bound_lead_is_lower_bound_not_exact_and_unknown_source_is_not_post():
    review = review_fixture(outputs=[output(kind="observed_upper_bound", available=-3)])
    _, result = evaluate(review)
    assert panel(result)["events"][0]["lead"] == {"kind": "lower_bound", "minimum_hours": 3, "maximum_hours": None}
    review["outputs"] = [output(kind="observed_upper_bound", available=3)]
    _, result = evaluate(review)
    assert panel(result)["events"][0]["category"] == "undetermined"


@pytest.mark.parametrize("field", ["set_hash", "source_binding", "package_binding", "truth"])
def test_frozen_binding_tamper_is_rejected(field):
    review = review_fixture()
    frozen, _ = evaluate(review)
    if field == "set_hash":
        frozen["events"][0]["actual_event_id"] = "changed"
    elif field in {"source_binding", "package_binding"}:
        key = "high_water" if field == "source_binding" else "manifest_sha256"
        review[field][key] = 51 if key == "high_water" else "0" * 64
    else:
        review["truth_revisions"][0]["actual_start"] = at(3)
    if field == "package_binding":
        # Attaching sets/assessments changes ZIP/manifest bytes, not core input.
        assert evaluate_review(review, frozen)["package_binding"] == frozen["package_binding"]
    else:
        with pytest.raises((ScoringContractError, ValueError)):
            evaluate_review(review, frozen)


def test_truth_revision_new_assessment_does_not_overwrite_old():
    review = review_fixture()
    frozen, old = evaluate(review)
    before = canonical_bytes(old)
    review2 = copy.deepcopy(review)
    review2["truth_revisions"].append(truth("truth-retracted"))
    review2["truth_revisions"][-1] = seal({**review2["truth_revisions"][-1], "truth_status": "RETRACTED"})
    spec = definition()
    spec["events"][0]["truth_ref"]["id"] = "truth-retracted"
    new_set, new = evaluate(review2, spec)
    assert new["id"] != old["id"] and new_set["set_hash"] != frozen["set_hash"]
    assert panel(new)["events"][0]["category"] == "undetermined"
    assert canonical_bytes(old) == before


@pytest.mark.parametrize("coverage,outcome,expected", [("partial", "no_observed_event", "undetermined"), ("complete", "no_observed_event", "no_event_observed_complete_coverage"), ("complete", "cancelled", "cancelled"), ("complete", "postponed", "postponed")])
def test_series_outcomes_use_separate_frozen_K_and_coverage(coverage, outcome, expected):
    fact = seal({**truth("series-fact"), "source_snapshot": {"execution_stage": outcome}, "scope": "all_paid"})
    review, spec = review_fixture(truths=[truth(), fact]), definition()
    spec["prediction_series_set"] = {"id": "series-set-1", "observation_cutoff_at": at(100), "coverage": {"status": coverage, "start": at(-10), "end": at(10)},
                                     "entries": [{"series_id": "series-1", "target": "EXTRA_FULL", "scope": "all_paid", "forecast_ids": ["forecast-1"], "requested_outcome": outcome, "outcome_truth_ids": ["series-fact"], "association_status": "confirmed", "outcome_event_id": "event-1"}]}
    frozen, result = evaluate(review, spec)
    series = result["series_outcomes"]
    assert series["groups"][0]["K"] == 1
    assert series["groups"][0]["series"][0]["outcome"] == expected
    assert series["set_hash"] == frozen["prediction_series_set"]["set_hash"]
    assert series["reality_false_positive_claim"] is False
    assert panel(result)["N"] == 1


def test_zero_N_and_invalid_freeze_ranges_fail_without_truncation(monkeypatch):
    review = review_fixture(forecasts=[], outputs=[], truths=[])
    _, result = evaluate(review, definition(events=[]))
    assert all(p["N"] == 0 and p["ratios"]["definite_hits_over_N"] is None for p in result["panels"])
    spec = definition()
    spec["observation_cutoff_at"] = "2026-10-01T00:00:00"
    with pytest.raises(ScoringContractError, match="timezone_required"):
        freeze_evaluation_set(review, spec, review["source_binding"])
    import app.prediction_scoring as scoring
    monkeypatch.setattr(scoring, "MAX_SET_ITEMS", 1)
    with pytest.raises(ScoringContractError, match="set_list_size"):
        freeze_evaluation_set(review, definition(events=[definition()["events"][0], definition()["events"][0]]), review["source_binding"])


def test_real_target_time_contract_is_used_without_date_or_relative_reinterpretation():
    from app.prediction_contract import normalize_prediction_time
    date = normalize_prediction_time({"prediction_form": "date", "expression": "2026-10-01", "source_timezone": "UTC", "precision": "day"})
    f = seal({**forecast(), **date})
    _, result = evaluate(review_fixture(forecasts=[f]))
    assert panel(result)["events"][0]["category"] == "definite_hit"
    assert panel(result)["events"][0]["metrics"]["prediction_width_hours"] == 24
    relative = normalize_prediction_time({"prediction_form": "relative", "relative_anchor_at": at(-24), "relative_offset_seconds": 86400, "precision": "minute", "source_timezone": "UTC"})
    _, result = evaluate(review_fixture(forecasts=[seal({**forecast(), **relative})]))
    assert panel(result)["events"][0]["category"] == "definite_hit"
    relative.pop("resolved_prediction_form")
    _, result = evaluate(review_fixture(forecasts=[seal({**forecast(), **relative})]))
    assert panel(result)["events"][0]["category"] == "prediction_unknown"


def test_classification_priorities_with_association_subtags_and_no_published_question_output():
    for association in ("confirmed", "ambiguous", "unresolved"):
        spec = definition()
        spec["events"][0]["association_status"] = association
        question = seal({**forecast(method=None), "version_role": "question_version"})
        _, result = evaluate(review_fixture(forecasts=[question], outputs=[]), spec)
        assert panel(result)["events"][0]["category"] == "no_prediction"
        _, result = evaluate(review_fixture(forecasts=[forecast(unknown=True)]), spec)
        assert panel(result)["events"][0]["category"] == "prediction_unknown"
        _, result = evaluate(review_fixture(outputs=[output(available=1)]), spec)
        assert panel(result)["events"][0]["category"] == "no_prediction"
    spec["events"][0]["output_ids"] = ["declared-missing-output"]
    _, result = evaluate(review_fixture(forecasts=[question], outputs=[]), spec)
    assert panel(result)["events"][0]["category"] == "undetermined"


def test_frozen_tie_order_verified_sequence_or_none_and_reverse_rejected():
    fs = [forecast(), forecast("f2", start=100, end=100)]
    os = [seal({**output(), "ledger_seq": 3}), seal({**output("o2", "f2"), "ledger_seq": 4})]
    review, spec = review_fixture(forecasts=fs, outputs=os), definition()
    spec["events"][0]["forecast_ids"].append("f2")
    spec["tie_order"] = {"basis": "persisted_same_timestamp_order", "output_ids": ["output-1", "o2"]}
    _, result = evaluate(review, spec)
    assert panel(result)["events"][0]["selected_prediction_ref"]["id"] == "forecast-1"
    assert panel(result, boundary="last")["events"][0]["selected_prediction_ref"]["id"] == "f2"
    spec["tie_order"]["output_ids"].reverse()
    with pytest.raises(ScoringContractError, match="tie_order_contradicts"):
        evaluate(review, spec)
    spec["tie_order"]["output_ids"].reverse()
    review["outputs"] = [seal({key: value for key, value in row.items() if key != "ledger_seq"}) for row in os]
    frozen, result = evaluate(review, spec)
    assert frozen["tie_order"]["basis"] == "none"
    assert panel(result)["events"][0]["category"] == "undetermined"


def test_missing_truth_does_not_mix_real_synthetic_without_independent_event_origin():
    review = review_fixture(forecasts=[forecast(unknown=True), forecast("real-f", unknown=True, synthetic=False)],
                            outputs=[output(), output("real-o", "real-f", synthetic=False)], truths=[])
    spec = definition()
    spec["events"][0]["forecast_ids"].append("real-f")
    frozen, result = evaluate(review, spec)
    assert {row["provenance"] for row in result["panels"]} == {"UNDECLARED"}
    assert panel(result, provenance="UNDECLARED")["events"][0]["category"] == "undetermined"
    review["public_evidence"] = [seal({"id": "event-proof", "source_snapshot": {"event_id": "event-1"}, "is_synthetic": True})]
    spec["events"][0]["event_ref"] = {"target": "public_evidence", "id": "event-proof"}
    # Remove the foreign real candidate: a known synthetic event with all legal
    # UNKNOWNs keeps UNKNOWN plus missing-truth, never a guessed real cohort.
    spec["events"][0]["forecast_ids"] = ["forecast-1"]
    frozen, result = evaluate(review, spec)
    assert frozen["events"][0]["provenance"] == "SYNTHETIC"
    row = panel(result)["events"][0]
    assert row["category"] == "prediction_unknown" and "missing_truth" in row["reason_codes"]


@pytest.mark.parametrize("case", ["wrong_target", "other_round", "ambiguous"])
def test_series_outcome_requires_target_subtype_and_unique_exact_event(case):
    review, spec = review_fixture(), definition()
    fact = truth("outcome-fact", event="other-round" if case == "other_round" else "event-1", target="BANKED" if case == "wrong_target" else "EXTRA_FULL")
    review["truth_revisions"].append(seal({**fact, "source_snapshot": {"execution_stage": "completed"}}))
    entry = {"series_id": "series-1", "target": "EXTRA_FULL", "scope": "all_paid", "forecast_ids": ["forecast-1"],
             "outcome_event_id": "event-1", "association_status": "ambiguous" if case == "ambiguous" else "confirmed",
             "requested_outcome": "observed", "outcome_truth_ids": ["outcome-fact"]}
    spec["prediction_series_set"] = {"id": "series-set", "observation_cutoff_at": at(100), "coverage": {"status": "complete", "start": at(-10), "end": at(10)}, "entries": [entry]}
    _, result = evaluate(review, spec)
    assert result["series_outcomes"]["groups"][0]["series"][0]["outcome"] == "undetermined"


def test_series_windows_freeze_all_actual_accepted_target_outputs_not_question_or_latest():
    question = seal({**forecast(method=None, scope="unknown", start=None, end=None), "version_role": "question_version"})
    outputs = []
    for index, predicted in enumerate((3, 9)):
        child = {**forecast(start=predicted, end=predicted), "target": "EXTRA_FULL", "validation": {"valid": True}}
        outputs.append(seal({**output(f"retry-{index}", available=-10 + index), "target_refs": {"EXTRA_FULL": {"forecast_id": "forecast-1"}}, "target_outputs": {"EXTRA_FULL": child}}))
    review, spec = review_fixture(forecasts=[question], outputs=outputs), definition()
    spec["prediction_series_set"] = {"id": "series-set", "observation_cutoff_at": at(100), "coverage": {"status": "complete", "start": at(0), "end": at(5)},
                                     "entries": [{"series_id": "series-1", "target": "EXTRA_FULL", "scope": "all_paid", "forecast_ids": ["forecast-1"], "requested_outcome": "no_observed_event"}]}
    frozen, result = evaluate(review, spec)
    windows = frozen["prediction_series_set"]["entries"][0]["accepted_windows"]
    assert [row["predicted_start"] for row in windows] == [at(3), at(9)]
    assert result["series_outcomes"]["groups"][0]["series"][0]["outcome"] == "undetermined"
    assert "observation_coverage_insufficient" in result["series_outcomes"]["groups"][0]["series"][0]["reason_codes"]


def test_final_package_collection_attachment_keeps_assessment_reproducible_not_zip_self_binding():
    review = review_fixture()
    frozen, assessment = evaluate(review)
    final_review = copy.deepcopy(review)
    final_review["evaluation_sets"] = [frozen]
    final_review["assessments"] = [assessment]
    final_review["package_binding"] = {"source_package_sha256": sha256_json({"final_zip": 2}), "manifest_sha256": sha256_json({"final_manifest": 2})}
    reproduced = evaluate_review(final_review, final_review["evaluation_sets"][0])
    assert reproduced == final_review["assessments"][0]
    assert reproduced["package_binding"] == review["package_binding"] != final_review["package_binding"]
    assert verify_assessment(final_review, assessment)["reproducible"] is True
    corrupt = copy.deepcopy(assessment)
    corrupt["panels"][0]["counts"]["definite_hit"] += 1
    corrupt = seal(corrupt)
    with pytest.raises(ScoringContractError, match="assessment_not_reproducible"):
        verify_assessment(final_review, corrupt)


def test_structured_output_scope_value_matches_truth_without_copying_question_certainty():
    f = forecast(scope={"value": "all_paid", "certainty": "source_explicit"})
    _, result = evaluate(review_fixture(forecasts=[f]))
    assert panel(result)["events"][0]["category"] == "definite_hit"


def test_same_actual_event_cannot_certify_two_series_outcomes():
    fs = [forecast(), forecast("second-forecast", series="second-series")]
    review = review_fixture(forecasts=fs, outputs=[output(), output("second-output", "second-forecast")])
    review["truth_revisions"].append(seal({**truth("completed-fact"), "source_snapshot": {"execution_stage": "completed"}}))
    spec = definition()
    entries = [{"series_id": row["series_id"], "target": "EXTRA_FULL", "scope": "all_paid", "forecast_ids": [row["id"]],
                "outcome_event_id": "event-1", "association_status": "confirmed", "requested_outcome": "observed", "outcome_truth_ids": ["completed-fact"]} for row in fs]
    spec["prediction_series_set"] = {"id": "series-set", "observation_cutoff_at": at(100), "coverage": {"status": "complete", "start": at(-1), "end": at(10)}, "entries": entries}
    frozen, result = evaluate(review, spec)
    assert all(row["association_status"] == "ambiguous" for row in frozen["prediction_series_set"]["entries"])
    assert result["series_outcomes"]["groups"][0]["counts"] == {"undetermined": 2}


def test_cli_embedded_assessment_is_recomputed_without_original_zip_self_reference(tmp_path, monkeypatch, capsys):
    cli, review = scoring_cli(), review_fixture()
    frozen, assessment = evaluate(review)
    review["evaluation_sets"], review["assessments"] = [frozen], [assessment]
    review["package_binding"] = {"source_package_sha256": sha256_json({"appended_package": 1}), "manifest_sha256": sha256_json({"appended_manifest": 1})}
    install_fake_loader(monkeypatch, cli, review)
    assert cli.main(["verify-assessment", "--package", str(tmp_path / "loader-final.zip"), "--assessment-id", assessment["id"]]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["reproducible"] is True and result["prediction_quality_pass"] is None


def test_successful_output_cannot_hide_explicit_missing_execution_extreme():
    question = seal({**forecast(method=None), "version_role": "question_version"})
    child = {**forecast(), "target": "EXTRA_FULL", "validation": {"valid": True}}
    published = seal({**output(), "target_refs": {"EXTRA_FULL": {"forecast_id": "forecast-1"}}, "target_outputs": {"EXTRA_FULL": child}})
    spec = definition()
    spec["events"][0]["output_ids"] = ["explicit-missing-output-2"]
    _, result = evaluate(review_fixture(forecasts=[question], outputs=[published]), spec)
    for boundary in ("first", "last"):
        row = panel(result, boundary=boundary)["events"][0]
        assert row["category"] == "undetermined" and "associated_output_missing" in row["reason_codes"]


@pytest.mark.parametrize("origin_fault", ["identity", "provenance"])
@pytest.mark.parametrize("state", ["known", "unknown", "no_output"])
def test_explicit_event_origin_conflict_blocks_known_pair_not_classification_priority(origin_fault, state):
    f = forecast(unknown=state == "unknown", synthetic=None)
    if state == "no_output":
        f = seal({**f, "version_role": "question_version", "method": None})
    review = review_fixture(forecasts=[f], outputs=[] if state == "no_output" else [output(synthetic=None)], truths=[truth(synthetic=None)])
    review["public_evidence"] = [seal({"id": "wrong-event-proof", "source_snapshot": {
        "event_id": "different-event" if origin_fault == "identity" else "event-1",
    }, "is_synthetic": None if origin_fault == "identity" else True})]
    spec = definition()
    spec["events"][0]["event_ref"] = {"target": "public_evidence", "id": "wrong-event-proof"}
    _, result = evaluate(review, spec)
    row = panel(result, provenance="UNDECLARED")["events"][0]
    assert row["category"] == {"known": "undetermined", "unknown": "prediction_unknown", "no_output": "no_prediction"}[state]
    assert f"event_origin_{origin_fault}_conflict" in row["reason_codes"]
    if state == "no_output":
        assert "no_actual_published_output" in row["reason_codes"] and "associated_output_missing" not in row["reason_codes"]


def test_question_versions_use_each_execution_target_method_and_shared_output_refs():
    full = seal({**forecast(start=99, end=99, method=None, scope="unknown"), "version_role": "question_version"})
    banked = seal({**forecast("forecast-banked", target="BANKED", method=None, scope="unknown"), "version_role": "question_version"})
    def shared(oid, hour, full_method, banked_valid=True):
        child = {**forecast(), "target": "EXTRA_FULL", "method": full_method, "validation": {"valid": True, "reason": "VALID"}}
        bchild = {**forecast(target="BANKED", unknown=True), "target": "BANKED", "validation": {"valid": banked_valid, "reason": "VALID" if banked_valid else "MISSING_TARGET"}}
        return seal({**output(oid, available=hour), "status": "partial" if not banked_valid else "accepted", "validation_status": "partial" if not banked_valid else "accepted",
                     "target_refs": {"EXTRA_FULL": {"forecast_id": full["id"], "series_id": "series-1", "revision": 1}, "BANKED": {"forecast_id": banked["id"], "revision": 1}},
                     "target_outputs": {"EXTRA_FULL": child, "BANKED": bchild}, "attempt_id": "one-attempt", "structured_output": {"predictions": {"EXTRA_FULL": child, "BANKED": bchild}}})
    first, second = shared("shared-1", -10, "official_time_extraction", False), shared("shared-2", -2, "model_inference")
    review = review_fixture(forecasts=[full, banked], outputs=[first, second], truths=[truth(), truth("truth-banked", event="event-banked", target="BANKED")])
    spec = definition()
    spec["events"].append({"actual_event_id": "event-banked", "target": "BANKED", "scope": "all_paid", "association_status": "confirmed", "truth_ref": {"target": "truth_revisions", "id": "truth-banked"}, "forecast_ids": [banked["id"]]})
    frozen, result = evaluate(review, spec)
    assert all(len(member["output_refs"]) == 2 for member in frozen["events"])
    assert panel(result, method="official_time_extraction")["events"][0]["selected_output_ref"]["id"] == "shared-1"
    assert panel(result)["events"][0]["selected_output_ref"]["id"] == "shared-2"
    assert panel(result)["events"][0]["category"] == "definite_hit"  # not static 99h question fields
    assert panel(result, target="BANKED")["events"][0]["category"] == "prediction_unknown"
    assert full["method"] is None and banked["method"] is None


def test_question_missing_target_output_is_gap_not_false_unknown():
    question = seal({**forecast(method=None), "version_role": "question_version"})
    _, result = evaluate(review_fixture(forecasts=[question]))
    assert panel(result)["events"][0]["category"] == "undetermined"
    assert "target_output_or_reference_missing" in panel(result)["events"][0]["reason_codes"]


def test_v2_transaction_binding_does_not_claim_live_main_file_sha():
    review = review_fixture()
    review["source_binding"].update(sourcekind="readonly_transaction", source_sha256=None,
                                   transaction_snapshot_digest=sha256_json({"transaction_projection": 1}))
    review["source_binding"]["snapshot_id"] = sha256_json({key: value for key, value in review["source_binding"].items() if key != "snapshot_id"})
    frozen, result = evaluate(review)
    assert frozen["source_binding"] == review["source_binding"] == result["source_binding"]
    assert frozen["source_binding"]["source_sha256"] is None


def test_formal_verified_package_cli_and_embedded_assessment_reproduce_without_source_zip(tmp_path, capsys):
    from app.review_export import export_review, load_verified_review

    # Explicit synthetic DTO records in a disposable SQLite fixture, using the
    # actual reader/exporter contracts. No loader/verifier is mocked here.
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE prediction_ledger(seq INTEGER PRIMARY KEY AUTOINCREMENT,record_id TEXT UNIQUE,"
        "kind TEXT,series_id TEXT,forecast_id TEXT,run_id TEXT,attempt_id TEXT,revision INTEGER,"
        "judgement_id INTEGER,event_id INTEGER,occurred_at TEXT,recorded_at TEXT,idempotency_key TEXT UNIQUE,payload_json TEXT)"
    )
    target_refs = {target: {"forecast_id": fid, "series_id": f"series-{target}", "revision": 1, "previous_id": None}
                   for target, fid in (("EXTRA_FULL", "full-question"), ("BANKED", "banked-question"))}
    targets = {}
    for index, target in enumerate(target_refs):
        targets[target] = {"target": target, "method": METHODS[index], "scope": "all_paid", "status": "KNOWN",
                           "prediction_form": "point", "predicted_start": at(index), "predicted_end": None,
                           "lifecycle": "planned", "validation": {"valid": True, "reason": "VALID", "date_status": "KNOWN"}}
    records = [
        ("forecast_version", {"target": target, "scope": "unknown", "version_role": "question_version", "method": None,
                              "record_kind": "online", "is_synthetic": True}, fid, None, None, None)
        for target, fid in (("EXTRA_FULL", "full-question"), ("BANKED", "banked-question"))
    ]
    records.extend([
        ("run_started", {"is_synthetic": True, "record_kind": "online", "target_refs": target_refs}, "full-question", "run", None, None),
        ("attempt_started", {"is_synthetic": True, "stage": "radar_judge"}, "full-question", "run", "attempt", None),
        ("output_committed", {"output_id": "shared-output", "target_refs": target_refs, "target_outputs": targets,
                              "validation": {"status": "accepted"}, "structured_output": {"predictions": targets}}, "full-question", "run", "attempt", None),
        ("output_observed", {"output_id": "shared-output", "observed_at": at(-2), "source": "formal_read_post_commit_upper_bound"},
         "full-question", "run", "attempt", None),
    ])
    for index, target in enumerate(target_refs, 1):
        facts = {key: value for key, value in truth(event=str(index), start=index - 1, end=index - 1, target=target).items()
                 if key not in {"id", "record_sha256", "event_id", "is_synthetic"}}
        records.append(("truth_revision", {"true_fields": facts, "is_synthetic": True, "event_id": index, "revision": 1}, None, None, None, index))
    for seq, (kind, payload, fid, run, attempt, event) in enumerate(records, 1):
        connection.execute(
            "INSERT INTO prediction_ledger(seq,record_id,kind,forecast_id,run_id,attempt_id,event_id,revision,occurred_at,recorded_at,payload_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (seq, f"source-record-{seq}", kind, fid, run, attempt, event, 1 if kind in {"forecast_version", "truth_revision"} else None,
             at(-3), at(-3), canonical_bytes(payload).decode("utf-8")),
        )
    connection.commit()
    frozen_review = freeze_review(connection, {"start": at(-48), "end": at(200), "series_id": None}, at(240))
    connection.close()
    stage = tmp_path / "staging"
    stage.mkdir()
    original = tmp_path / "original.zip"
    export_review(frozen_review, output_path=original, staging_dir=stage)
    original_loaded = load_verified_review(original)
    spec = definition(events=[
        {"actual_event_id": str(index), "target": target, "scope": "all_paid", "association_status": "confirmed",
         "truth_ref": {"target": "truth_revisions", "id": f"source-record-{6 + index}"}, "forecast_ids": [target_refs[target]["forecast_id"]]}
        for index, target in enumerate(target_refs, 1)
    ])
    spec_path, set_path, score_path = (tmp_path / name for name in ("definition.json", "set.json", "score.json"))
    spec_path.write_bytes(canonical_bytes(spec))
    cli = scoring_cli()
    assert cli.main(["freeze", "--package", str(original), "--definition", str(spec_path), "--out", str(set_path), "--staging-dir", str(stage)]) == 0
    assert cli.main(["score", "--package", str(original), "--set", str(set_path), "--out", str(score_path), "--staging-dir", str(stage)]) == 0
    assessment = json.loads(score_path.read_bytes())
    assert panel(assessment, method="official_time_extraction")["counts"]["definite_hit"] == 1
    assert panel(assessment, target="BANKED")["counts"]["definite_hit"] == 1
    final = tmp_path / "final-with-assessment.zip"
    exported = export_review(frozen_review, output_path=final, staging_dir=stage, evaluation_sets=[set_path], assessments=[score_path])
    assert exported["verification"]["assessments_reproduced"] == 1
    final_loaded = load_verified_review(final)
    assert final_loaded["source_package_sha256"] != original_loaded["source_package_sha256"]
    assert final_loaded["collections"]["assessments"][0]["package_binding"]["source_package_sha256"] == original_loaded["source_package_sha256"]
    # The original source package is not available to either final-only command.
    original.rename(tmp_path / "retained-original-evidence.zip")
    assert cli.main(["verify-assessment", "--package", str(final), "--assessment-id", assessment["id"]]) == 0
    recomputed = tmp_path / "recomputed.json"
    assert cli.main(["score", "--package", str(final), "--set-id", spec["id"], "--out", str(recomputed), "--staging-dir", str(stage)]) == 0
    assert json.loads(recomputed.read_bytes()) == assessment
    assert list(stage.iterdir()) == []
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(line.get("reproducible") is True for line in lines)


def scoring_cli():
    script = Path(__file__).resolve().parents[3] / "scripts" / "score_prediction_review.py"
    spec = importlib.util.spec_from_file_location("scoring_cli_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_fake_loader(monkeypatch, cli, review):
    # CLI publisher tests use an explicit fake public-loader boundary, not a
    # copied ZIP verifier or a claim that arbitrary ZIP data was verified.
    loaded = {"collections": {key: value for key, value in review.items() if isinstance(value, list)},
              "manifest": {"source_binding": review["source_binding"]}, "verification": {"valid": True}, **review["package_binding"]}
    monkeypatch.setattr(cli.review_export, "load_verified_review", lambda _path: copy.deepcopy(loaded), raising=False)


def test_cli_freeze_score_sidecars_stable_and_source_untouched(tmp_path, monkeypatch, capsys):
    cli, review = scoring_cli(), review_fixture()
    install_fake_loader(monkeypatch, cli, review)
    source = tmp_path / "fake-loader-source.zip"
    source.write_bytes(b"public loader fake fixture, not a production package")
    before = source.read_bytes()
    spec = tmp_path / "definition.json"
    spec.write_bytes(canonical_bytes(definition()))
    frozen, result = tmp_path / "set.json", tmp_path / "assessment.json"
    stage = tmp_path / "explicit-matter-staging"
    stage.mkdir()
    sentinel = stage / "user-existing.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    base = ["--package", str(source), "--staging-dir", str(stage)]
    assert cli.main(["freeze", *base, "--definition", str(spec), "--out", str(frozen)]) == 0
    assert cli.main(["score", *base, "--set", str(frozen), "--out", str(result)]) == 0
    assert json.loads(result.read_bytes())["set_hash"] == json.loads(frozen.read_bytes())["set_hash"]
    assert cli.main(["score", *base, "--set", str(frozen), "--out", str(result)]) == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["error"] == "output_path_already_exists"
    assert source.read_bytes() == before and list(stage.iterdir()) == [sentinel]


@pytest.mark.parametrize("race", [True, False])
def test_cli_atomic_no_clobber_and_fixed_private_error(tmp_path, monkeypatch, capsys, race):
    cli, review = scoring_cli(), review_fixture()
    install_fake_loader(monkeypatch, cli, review)
    spec = tmp_path / "definition.json"
    spec.write_bytes(canonical_bytes(definition()))
    target, stage = tmp_path / "set.json", tmp_path / "staging"
    stage.mkdir()
    original_link = cli.os.link
    def interrupted_publish(source, destination):
        if race:
            Path(destination).write_bytes(b"concurrent owner original bytes")
            return original_link(source, destination)
        raise OSError("C:/Users/private-publish-bait/file.json")
    monkeypatch.setattr(cli.os, "link", interrupted_publish)
    assert cli.main(["freeze", "--package", str(tmp_path / "loader-fake.zip"), "--definition", str(spec),
                     "--out", str(target), "--staging-dir", str(stage)]) == 2
    captured = capsys.readouterr()
    assert "private-publish-bait" not in captured.out + captured.err
    assert json.loads(captured.out)["error"] == ("output_path_already_exists" if race else "atomic_no_clobber_publish_failed")
    assert target.read_bytes() == b"concurrent owner original bytes" if race else not target.exists()
    assert list(stage.iterdir()) == []


def test_cli_strips_unapproved_payload_and_fails_before_publish_on_missing_loader(tmp_path, monkeypatch, capsys):
    cli, review = scoring_cli(), review_fixture()
    install_fake_loader(monkeypatch, cli, review)
    spec = definition()
    spec.update(raw_json={"chain_of_thought": "scoring-secret-body-bait"}, private_body="scoring-secret-body-bait")
    path, output_path = tmp_path / "definition.json", tmp_path / "set.json"
    path.write_bytes(canonical_bytes(spec))
    stage = tmp_path / "staging"
    stage.mkdir()
    args = ["freeze", "--package", str(tmp_path / "loader-fake.zip"), "--definition", str(path), "--out", str(output_path), "--staging-dir", str(stage)]
    assert cli.main(args) == 0
    assert b"scoring-secret-body-bait" not in output_path.read_bytes()
    monkeypatch.delattr(cli.review_export, "load_verified_review")
    args[-3] = str(tmp_path / "another-set.json")
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["error"] == "shared_verified_loader_unavailable"
