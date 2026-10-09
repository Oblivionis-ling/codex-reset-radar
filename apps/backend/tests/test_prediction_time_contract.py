from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest

from app.prediction_contract import (
    TargetContractError,
    next_reset_baseline,
    normalize_prediction_time,
    validate_predictions,
)


def _known(target: str, **changes):
    value = {
        "target": target,
        "status": "KNOWN",
        "method": "model_inference",
        "scope": {"value": "all_paid", "certainty": "inferred"},
        "predicted_start": "2026-10-10T10:00:00Z",
        "predicted_end": "2026-10-10T10:00:00Z",
        "prediction_form": "point",
        "source_timezone": "UTC",
        "precision": "minute",
        "time_basis": "model_inference",
        "expression": None,
        "relative_anchor_at": None,
        "relative_offset_seconds": None,
        "reason": "合成证据用于时间契约测试。",
        "unresolved_reason": None,
        "evidence_post_ids": ["source-1"],
        "evidence_refs": [],
        "lifecycle": "planned",
    }
    value.update(changes)
    return value


def _unknown(target: str):
    return _known(
        target,
        status="UNKNOWN",
        scope={"value": "unknown", "certainty": "unknown"},
        predicted_start=None,
        predicted_end=None,
        prediction_form="unknown",
        source_timezone=None,
        precision="unknown",
        time_basis="unknown",
        evidence_post_ids=[],
        unresolved_reason="没有独立时间依据。",
        lifecycle="unknown",
    )


def _context(text: str, *, posted_at="2026-10-09T09:00:00+08:00", author="user", analysis=None):
    return {
        "posts": [{
            "tweet_id": "source-1",
            "input_hash": "source-version-1",
            "text": text,
            "posted_at": posted_at,
            "author": author,
            "analysis": analysis or {},
        }]
    }


def _full_anchor(
    event_id: str,
    occurred_at: str | None,
    *,
    occurred_at_end: str | None = None,
    form="point",
    precision="minute",
    source_timezone="UTC",
    time_basis="verified_actual_start",
):
    return {
        "id": event_id,
        "event_type": "FULL_RESET",
        "occurred_at": occurred_at,
        "occurred_at_end": occurred_at_end,
        "time_basis": time_basis,
        "provenance": {
            "prediction_form": form,
            "time_precision": precision,
            "source_timezone": source_timezone,
        },
    }


def test_aware_utc_values_are_not_reinterpreted_by_source_timezone():
    normalized = normalize_prediction_time({
        "prediction_form": "range",
        "predicted_start": "2026-10-10T00:00:00Z",
        "predicted_end": "2026-10-10T02:00:00+00:00",
        "source_timezone": "UTC+8",
        "precision": "minute",
    })

    assert normalized["predicted_start"] == "2026-10-10T00:00:00Z"
    assert normalized["predicted_end"] == "2026-10-10T02:00:00Z"
    assert normalized["source_timezone"] == "UTC+8"


@pytest.mark.parametrize(
    ("local_value", "zone", "reason"),
    [
        ("2026-10-10T10:00:00", None, "TIMEZONE_NOT_STATED"),
        ("2026-11-01T01:30:00", "America/New_York", "AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME"),
        ("2026-03-08T02:30:00", "America/New_York", "AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME"),
    ],
)
def test_naive_local_time_requires_a_stated_unambiguous_zone(local_value, zone, reason):
    with pytest.raises(TargetContractError) as caught:
        normalize_prediction_time({
            "prediction_form": "point",
            "predicted_start": local_value,
            "predicted_end": local_value,
            "source_timezone": zone,
        })

    assert caught.value.reason_code == reason


def test_local_date_is_a_full_dst_aware_day_envelope_not_a_point():
    normalized = normalize_prediction_time({
        "prediction_form": "date",
        "expression": "2026-03-08",
        "source_timezone": "America/New_York",
        "precision": "day",
    })

    start = datetime.fromisoformat(normalized["predicted_start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(normalized["predicted_end"].replace("Z", "+00:00"))
    assert normalized["prediction_form"] == "date"
    assert normalized["precision"] == "day"
    assert normalized["date_boundaries"] == "closed_conservative_local_day_envelope_not_execution_instants"
    assert normalized["predicted_start"] == "2026-03-08T05:00:00Z"
    assert normalized["predicted_end"] == "2026-03-09T04:00:00Z"
    assert end > start
    assert (end - start).total_seconds() == 23 * 60 * 60


@pytest.mark.parametrize(
    ("form", "start", "end", "expected_start", "expected_end"),
    [
        ("point", "2026-10-10T10:00:00Z", "2026-10-10T10:00:00Z", "2026-10-10T10:00:00Z", "2026-10-10T10:00:00Z"),
        ("point", "2026-10-10T10:00:00Z", None, "2026-10-10T10:00:00Z", None),
        ("start_only", "2026-10-10T10:00:00Z", None, "2026-10-10T10:00:00Z", None),
        ("end_only", None, "2026-10-10T10:00:00Z", None, "2026-10-10T10:00:00Z"),
    ],
)
def test_explicit_point_and_one_sided_forms_keep_their_endpoints(form, start, end, expected_start, expected_end):
    normalized = normalize_prediction_time({
        "prediction_form": form,
        "predicted_start": start,
        "predicted_end": end,
        "source_timezone": "UTC",
    })

    assert normalized["prediction_form"] == form
    assert normalized["predicted_start"] == expected_start
    assert normalized["predicted_end"] == expected_end
    if form == "start_only":
        assert normalized.get("resolved_prediction_form") is None


def test_explicit_point_rejects_two_different_endpoints():
    with pytest.raises(TargetContractError) as caught:
        normalize_prediction_time({
            "prediction_form": "point",
            "predicted_start": "2026-10-10T10:00:00Z",
            "predicted_end": "2026-10-10T11:00:00Z",
            "source_timezone": "UTC",
        })

    assert caught.value.reason_code == "INVALID_POINT_OR_START_ONLY"


def test_relative_wall_clock_uses_the_source_post_anchor_and_quoted_timezone():
    phrase = "明天约10:30 UTC+8"
    anchor = "2026-10-09T09:00:00+08:00"
    target = _known(
        "EXTRA_FULL",
        prediction_form="relative",
        predicted_start=None,
        predicted_end=None,
        source_timezone="UTC+8",
        time_basis="relative_to_post",
        expression=phrase,
        relative_anchor_at=anchor,
        evidence_post_ids=[],
        evidence_refs=[{"tweet_id": "source-1", "evidence_quote": phrase}],
    )
    context = _context(f"作者发布于 {anchor}，正文写着：{phrase}。", posted_at=anchor)

    outputs, summary = validate_predictions({"EXTRA_FULL": target, "BANKED": _unknown("BANKED")}, context)

    assert summary["status"] == "accepted"
    assert outputs["EXTRA_FULL"]["validation"]["valid"] is True
    assert outputs["EXTRA_FULL"]["relative_anchor_at"] == "2026-10-09T01:00:00Z"
    assert outputs["EXTRA_FULL"]["predicted_start"] == "2026-10-10T02:30:00Z"
    assert outputs["EXTRA_FULL"]["predicted_end"] is None
    assert outputs["EXTRA_FULL"]["resolved_prediction_form"] == "point"


@pytest.mark.parametrize(("declared_offset", "valid", "reason"), [
    (5400, True, "VALID"),
    (3600, False, "RELATIVE_OFFSET_SEMANTICS_NOT_VERIFIED"),
])
def test_relative_elapsed_offset_must_match_the_quoted_duration(declared_offset, valid, reason):
    phrase = "in 90 minutes"
    anchor = "2026-10-09T01:00:00Z"
    target = _known(
        "EXTRA_FULL",
        prediction_form="relative",
        predicted_start=None,
        predicted_end=None,
        source_timezone="UTC",
        time_basis="relative_to_post",
        expression=phrase,
        relative_anchor_at=anchor,
        relative_offset_seconds=declared_offset,
        evidence_post_ids=[],
        evidence_refs=[{"tweet_id": "source-1", "evidence_quote": phrase}],
    )
    outputs, summary = validate_predictions(
        {"EXTRA_FULL": target, "BANKED": _unknown("BANKED")},
        _context(f"The reset starts {phrase}.", posted_at=anchor),
    )

    assert outputs["EXTRA_FULL"]["validation"]["valid"] is valid
    assert outputs["EXTRA_FULL"]["validation"]["reason"] == reason
    if valid:
        assert summary["status"] == "accepted"
        assert outputs["EXTRA_FULL"]["predicted_start"] == "2026-10-09T02:30:00Z"
    else:
        assert summary["status"] == "partial"


def test_relative_tomorrow_without_source_time_text_is_rejected():
    phrase = "明天约10:30 UTC+8"
    anchor = "2026-10-09T09:00:00+08:00"
    target = _known(
        "EXTRA_FULL",
        prediction_form="relative",
        predicted_start=None,
        predicted_end=None,
        source_timezone="UTC+8",
        time_basis="relative_to_post",
        expression=phrase,
        relative_anchor_at=anchor,
        evidence_post_ids=[],
        evidence_refs=[{"tweet_id": "source-1"}],
    )

    outputs, summary = validate_predictions(
        {"EXTRA_FULL": target, "BANKED": _unknown("BANKED")},
        _context("We expect a reset soon, but gave no date or time.", posted_at=anchor),
    )

    assert summary["status"] == "partial"
    assert outputs["EXTRA_FULL"]["validation"] == {
        "valid": False,
        "reason": "RELATIVE_CLOCK_SEMANTICS_NOT_VERIFIED",
    }
    assert outputs["EXTRA_FULL"]["rejected_output"]["predicted_start"] is None


def test_relative_utc_does_not_match_utc_plus_eight_prefix_in_source_quote():
    phrase = "Tomorrow 10:30 UTC+8"
    anchor = "2026-10-09T12:00:00Z"
    target = _known(
        "EXTRA_FULL",
        method="model_inference",
        prediction_form="relative",
        predicted_start=None,
        predicted_end=None,
        source_timezone="UTC",
        time_basis="relative_to_post",
        expression=phrase,
        relative_anchor_at=anchor,
        evidence_post_ids=[],
        evidence_refs=[{"tweet_id": "source-1", "evidence_quote": phrase}],
    )

    outputs, summary = validate_predictions(
        {"EXTRA_FULL": target, "BANKED": _unknown("BANKED")},
        _context(f"{phrase}; source-time boundary case.", posted_at=anchor),
    )

    assert summary["status"] == "partial"
    assert outputs["EXTRA_FULL"]["validation"]["valid"] is False
    assert outputs["EXTRA_FULL"]["validation"]["reason"] == "RELATIVE_CLOCK_SEMANTICS_NOT_VERIFIED"


def test_valid_unknown_missing_target_and_rejected_target_are_distinct():
    context = _context("A synthetic source post with no official schedule.")
    known = _known("EXTRA_FULL")
    unknown = _unknown("BANKED")

    outputs, summary = validate_predictions({"EXTRA_FULL": known, "BANKED": unknown}, context)
    assert summary == {"status": "accepted", "accepted_targets": ["EXTRA_FULL", "BANKED"]}
    assert outputs["BANKED"]["status"] == "UNKNOWN"
    assert outputs["BANKED"]["validation"] == {"valid": True, "reason": "VALID", "date_status": "UNKNOWN"}

    missing_outputs, missing_summary = validate_predictions({"EXTRA_FULL": known}, context)
    assert missing_summary["status"] == "partial"
    assert missing_outputs["BANKED"]["validation"]["reason"] == "MISSING_TARGET"

    point_without_end = _known("BANKED", predicted_end=None)
    point_outputs, point_summary = validate_predictions(
        {"EXTRA_FULL": known, "BANKED": point_without_end}, context
    )
    assert point_summary["status"] == "accepted"
    assert point_outputs["BANKED"]["validation"]["valid"] is True
    assert point_outputs["BANKED"]["prediction_form"] == "point"
    assert point_outputs["BANKED"]["predicted_end"] is None

    malformed = _known("BANKED", predicted_end="2026-10-10T11:00:00Z")
    rejected_outputs, rejected_summary = validate_predictions(
        {"EXTRA_FULL": known, "BANKED": malformed}, context
    )
    assert rejected_summary["status"] == "partial"
    assert rejected_outputs["EXTRA_FULL"]["validation"]["valid"] is True
    assert rejected_outputs["BANKED"]["validation"]["valid"] is False
    assert rejected_outputs["BANKED"]["validation"]["reason"] == "INVALID_POINT_OR_START_ONLY"


_OFFICIAL_QUOTE = (
    "For Plus Pro, the reset is planned to start between "
    "2026-10-10T10:00Z and 2026-10-10T12:00Z."
)


def _official_case(target="EXTRA_FULL"):
    event_type = "FULL_RESET" if target == "EXTRA_FULL" else "SPECIAL_RESET"
    effect = {
        "event_type": event_type,
        "special_type": "BANKED" if target == "BANKED" else None,
        "claim_kind": "planned_occurrence",
        "execution_stage": "announced",
        "time_basis": "explicit_text",
        "evidence_quote": _OFFICIAL_QUOTE,
        "event_time_start": "2026-10-10T10:00:00Z",
        "event_time_end": "2026-10-10T12:00:00Z",
        "prediction_form": "range",
        "time_precision": "minute",
        "source_timezone": "UTC",
        "scope": {"value": "plus_pro", "certainty": "explicit"},
    }
    prediction = _known(
        target,
        method="official_time_extraction",
        scope={"value": "plus_pro", "certainty": "explicit"},
        predicted_start="2026-10-10T10:00:00Z",
        predicted_end="2026-10-10T12:00:00Z",
        prediction_form="range",
        source_timezone="UTC",
        precision="minute",
        time_basis="official_planned",
        evidence_post_ids=[],
        evidence_refs=[{"tweet_id": "source-1", "evidence_quote": _OFFICIAL_QUOTE}],
    )
    context = _context(_OFFICIAL_QUOTE, author="@OpenAI", analysis={"effects": [effect]})
    return prediction, context


def _official_point_case(target="EXTRA_FULL", timestamp="2026-10-11T15:00:00Z", tweet_id="source-1"):
    quote = f"The reset is planned to start at {timestamp}."
    scope = {"value": "unknown", "certainty": "unknown"}
    effect = {
        "event_type": "FULL_RESET" if target == "EXTRA_FULL" else "SPECIAL_RESET",
        "special_type": "BANKED" if target == "BANKED" else None,
        "claim_kind": "planned_occurrence",
        "execution_stage": "announced",
        "time_basis": "explicit_text",
        "evidence_quote": quote,
        "event_time_start": timestamp,
        "event_time_end": None,
        "prediction_form": "point",
        "time_precision": "second",
        "source_timezone": "UTC",
        "scope": scope,
    }
    prediction = _known(
        target,
        method="official_time_extraction",
        scope=scope,
        predicted_start=timestamp,
        predicted_end=None,
        prediction_form="point",
        source_timezone="UTC",
        precision="second",
        time_basis="official_planned",
        evidence_post_ids=[],
        evidence_refs=[{"tweet_id": tweet_id, "evidence_quote": quote}],
    )
    context = _context(quote, author="@OpenAI", analysis={"effects": [effect]})
    context["posts"][0]["tweet_id"] = tweet_id
    return prediction, context


def _official_sparse_effect_point_case(quote, normalized_start, tweet_id="source-1"):
    scope = {"value": "unknown", "certainty": "unknown"}
    effect = {
        "event_type": "FULL_RESET",
        "special_type": None,
        "claim_kind": "planned_occurrence",
        "execution_stage": "announced",
        "time_basis": "explicit_text",
        "evidence_quote": quote,
        "event_time_start": normalized_start,
        "event_time_end": None,
        "scope": scope,
    }
    prediction = _known(
        "EXTRA_FULL",
        method="official_time_extraction",
        scope=scope,
        predicted_start=normalized_start,
        predicted_end=None,
        prediction_form="point",
        source_timezone="UTC",
        precision="second",
        time_basis="official_planned",
        evidence_post_ids=[],
        evidence_refs=[{"tweet_id": tweet_id, "evidence_quote": quote}],
    )
    context = _context(quote, author="@OpenAI", analysis={"effects": [effect]})
    context["posts"][0]["tweet_id"] = tweet_id
    return prediction, context


@pytest.mark.parametrize("target_name", ["EXTRA_FULL", "BANKED"])
def test_official_extraction_requires_a_verbatim_quote_and_matching_formal_effect(target_name):
    prediction, context = _official_case(target_name)
    outputs, summary = validate_predictions(
        {target_name: prediction, ("BANKED" if target_name == "EXTRA_FULL" else "EXTRA_FULL"): _unknown(
            "BANKED" if target_name == "EXTRA_FULL" else "EXTRA_FULL"
        )},
        context,
    )

    assert summary["status"] == "accepted"
    assert outputs[target_name]["validation"]["valid"] is True
    assert outputs[target_name]["evidence_refs"][0]["evidence_quote"] == _OFFICIAL_QUOTE
    assert outputs[target_name]["prediction_form"] == "range"
    assert outputs[target_name]["predicted_start"] == "2026-10-10T10:00:00Z"
    assert outputs[target_name]["predicted_end"] == "2026-10-10T12:00:00Z"


def test_official_explicit_point_accepts_equivalent_utc_and_needs_no_end():
    prediction, context = _official_point_case()
    prediction["predicted_start"] = "2026-10-11T15:00:00+00:00"

    outputs, summary = validate_predictions(
        {"EXTRA_FULL": prediction, "BANKED": _unknown("BANKED")}, context
    )

    assert summary["status"] == "accepted"
    assert outputs["EXTRA_FULL"]["validation"]["valid"] is True
    assert outputs["EXTRA_FULL"]["prediction_form"] == "point"
    assert outputs["EXTRA_FULL"]["precision"] == "second"
    assert outputs["EXTRA_FULL"]["scope"] == {"value": "unknown", "certainty": "unknown"}
    assert outputs["EXTRA_FULL"]["predicted_start"] == "2026-10-11T15:00:00Z"
    assert outputs["EXTRA_FULL"]["predicted_end"] is None


def test_official_explicit_point_is_not_degraded_to_start_only_minute():
    prediction, context = _official_point_case()
    prediction.update(prediction_form="start_only", precision="minute")

    outputs, summary = validate_predictions(
        {"EXTRA_FULL": prediction, "BANKED": _unknown("BANKED")}, context
    )

    assert summary["status"] == "partial"
    assert outputs["EXTRA_FULL"]["validation"] == {
        "valid": False,
        "reason": "OFFICIAL_PLAN_NOT_VERIFIED",
    }


def test_sparse_effect_with_explicit_iso_seconds_accepts_point_with_unknown_scope():
    quote = "The reset is planned for 2026-10-11T15:00:00Z."
    prediction, context = _official_sparse_effect_point_case(
        quote, "2026-10-11T15:00:00Z"
    )
    effect = context["posts"][0]["analysis"]["effects"][0]
    assert not {"prediction_form", "time_precision", "source_timezone"} & effect.keys()

    outputs, summary = validate_predictions(
        {"EXTRA_FULL": prediction, "BANKED": _unknown("BANKED")}, context
    )

    assert summary["status"] == "accepted"
    assert outputs["EXTRA_FULL"]["validation"]["valid"] is True
    assert outputs["EXTRA_FULL"]["prediction_form"] == "point"
    assert outputs["EXTRA_FULL"]["precision"] == "second"
    assert outputs["EXTRA_FULL"]["predicted_start"] == "2026-10-11T15:00:00Z"
    assert outputs["EXTRA_FULL"]["predicted_end"] is None
    assert outputs["EXTRA_FULL"]["scope"] == {"value": "unknown", "certainty": "unknown"}


@pytest.mark.parametrize(
    ("field", "value"),
    [("prediction_form", "start_only"), ("precision", "minute")],
)
def test_sparse_effect_point_rejects_form_or_precision_degradation_independently(field, value):
    quote = "The reset is planned for 2026-10-11T15:00:00Z."
    prediction, context = _official_sparse_effect_point_case(
        quote, "2026-10-11T15:00:00Z"
    )
    prediction[field] = value

    outputs, summary = validate_predictions(
        {"EXTRA_FULL": prediction, "BANKED": _unknown("BANKED")}, context
    )

    assert summary["status"] == "partial"
    assert outputs["EXTRA_FULL"]["validation"] == {
        "valid": False,
        "reason": "OFFICIAL_PLAN_NOT_VERIFIED",
    }
    assert outputs["BANKED"]["validation"]["valid"] is True


@pytest.mark.parametrize(("precision", "valid"), [("minute", True), ("second", False)])
def test_sparse_effect_hhmm_quote_does_not_gain_precision_from_normalized_seconds(precision, valid):
    quote = "The reset is planned for 2026-10-11T15:00Z."
    prediction, context = _official_sparse_effect_point_case(
        quote, "2026-10-11T15:00:00Z"
    )
    prediction["precision"] = precision
    effect = context["posts"][0]["analysis"]["effects"][0]
    assert not {"prediction_form", "time_precision", "source_timezone"} & effect.keys()

    outputs, summary = validate_predictions(
        {"EXTRA_FULL": prediction, "BANKED": _unknown("BANKED")}, context
    )

    assert outputs["EXTRA_FULL"]["validation"]["valid"] is valid
    if valid:
        assert summary["status"] == "accepted"
        assert outputs["EXTRA_FULL"]["precision"] == "minute"
        assert outputs["EXTRA_FULL"]["predicted_start"] == "2026-10-11T15:00:00Z"
        assert outputs["EXTRA_FULL"]["predicted_end"] is None
    else:
        assert summary["status"] == "partial"
        assert outputs["EXTRA_FULL"]["validation"]["reason"] == "OFFICIAL_PLAN_NOT_VERIFIED"


def test_full_and_banked_keep_distinct_official_plan_times_and_do_not_borrow():
    full, full_context = _official_point_case(
        "EXTRA_FULL", "2026-10-11T15:00:00Z", "full-source"
    )
    banked, banked_context = _official_point_case(
        "BANKED", "2026-10-11T18:00:00Z", "banked-source"
    )
    context = {"posts": full_context["posts"] + banked_context["posts"]}

    outputs, summary = validate_predictions({"EXTRA_FULL": full, "BANKED": banked}, context)

    assert summary["status"] == "accepted"
    assert outputs["EXTRA_FULL"]["predicted_start"] == "2026-10-11T15:00:00Z"
    assert outputs["BANKED"]["predicted_start"] == "2026-10-11T18:00:00Z"
    assert outputs["EXTRA_FULL"]["scope"]["value"] == "unknown"
    assert outputs["BANKED"]["scope"]["value"] == "unknown"

    borrowed = {
        "EXTRA_FULL": {**full, "predicted_start": "2026-10-11T18:00:00Z"},
        "BANKED": {**banked, "predicted_start": "2026-10-11T15:00:00Z"},
    }
    rejected, rejected_summary = validate_predictions(borrowed, context)

    assert rejected_summary["status"] == "rejected"
    assert rejected["EXTRA_FULL"]["validation"]["reason"] == "OFFICIAL_PLAN_NOT_VERIFIED"
    assert rejected["BANKED"]["validation"]["reason"] == "OFFICIAL_PLAN_NOT_VERIFIED"


@pytest.mark.parametrize("mutation", [
    "missing_quote",
    "range_collapsed_to_point",
    "plus_pro_expanded_to_all_paid",
    "precision_upgraded",
    "wrong_official_event_type",
])
def test_official_extraction_rejects_unquoted_or_expanded_claims(mutation):
    prediction, context = _official_case("EXTRA_FULL")
    prediction = deepcopy(prediction)
    context = deepcopy(context)
    effect = context["posts"][0]["analysis"]["effects"][0]

    if mutation == "missing_quote":
        prediction["evidence_refs"] = [{"tweet_id": "source-1"}]
    elif mutation == "range_collapsed_to_point":
        prediction["prediction_form"] = "point"
        prediction["predicted_end"] = prediction["predicted_start"]
    elif mutation == "plus_pro_expanded_to_all_paid":
        prediction["scope"] = {"value": "all_paid", "certainty": "explicit"}
    elif mutation == "precision_upgraded":
        prediction["precision"] = "second"
    else:
        effect["event_type"] = "SPECIAL_RESET"
        effect["special_type"] = "BANKED"

    outputs, summary = validate_predictions(
        {"EXTRA_FULL": prediction, "BANKED": _unknown("BANKED")}, context
    )

    assert summary["status"] == "partial"
    assert outputs["EXTRA_FULL"]["validation"] == {
        "valid": False,
        "reason": "OFFICIAL_PLAN_NOT_VERIFIED",
    }


@pytest.mark.parametrize(
    ("form", "occurred_at", "occurred_at_end", "expected_start", "expected_end"),
    [
        ("start_only", "2026-05-01T10:00:00Z", None, "2026-05-08T10:00:00Z", None),
        ("end_only", None, "2026-05-01T10:00:00Z", None, "2026-05-08T10:00:00Z"),
    ],
)
def test_normal_baseline_keeps_a_single_anchor_side(form, occurred_at, occurred_at_end, expected_start, expected_end):
    baseline = next_reset_baseline(
        _full_anchor("full-1", occurred_at, occurred_at_end=occurred_at_end, form=form),
        as_of="2026-05-01T00:00:00Z",
    )

    assert baseline["status"] == "baseline"
    assert baseline["prediction_form"] == form
    assert baseline["predicted_start"] == expected_start
    assert baseline["predicted_end"] == expected_end


def test_normal_baseline_shifts_both_ends_of_a_full_range_by_seven_days():
    baseline = next_reset_baseline(
        _full_anchor(
            "full-range",
            "2026-05-01T10:00:00Z",
            occurred_at_end="2026-05-01T12:00:00Z",
            form="range",
        ),
        as_of="2026-05-01T00:00:00Z",
    )

    assert baseline["prediction_form"] == "range"
    assert baseline["predicted_start"] == "2026-05-08T10:00:00Z"
    assert baseline["predicted_end"] == "2026-05-08T12:00:00Z"
    assert baseline["anchor_event_id"] == "full-range"


def test_normal_baseline_retains_proxy_and_date_precision():
    baseline = next_reset_baseline(
        _full_anchor(
            "proxy-full",
            "2026-05-01T00:00:00Z",
            form="date",
            precision="day",
            source_timezone="UTC",
            time_basis="post_time_proxy",
        ),
        as_of="2026-05-01T00:00:00Z",
    )

    assert baseline["prediction_form"] == "proxy"
    assert baseline["time_form"] == "proxy"
    assert baseline["precision"] == "day"
    assert baseline["predicted_start"] == "2026-05-08T00:00:00Z"
    assert baseline["predicted_end"] == "2026-05-09T00:00:00Z"
    assert baseline["anchor_time_basis"] == "post_time_proxy"
    assert baseline["anchor_limitation"] == "POST_TIME_PROXY_NOT_ACTUAL_START"


def test_normal_baseline_does_not_upgrade_an_unknown_precision_legacy_point():
    anchor = _full_anchor("legacy-full", "2026-05-01T10:00:00Z", form="point", precision="unknown")
    baseline = next_reset_baseline(anchor, as_of="2026-05-01T00:00:00Z")

    assert baseline["prediction_form"] == "start_only"
    assert baseline["predicted_start"] == "2026-05-08T10:00:00Z"
    assert baseline["predicted_end"] is None
    assert baseline["anchor_limitation"] == "LEGACY_ANCHOR_PRECISION_NOT_VERIFIED"


def test_expired_normal_baseline_stays_expired_without_rolling_forward():
    baseline = next_reset_baseline(
        _full_anchor("full-1", "2026-10-01T12:00:00Z"),
        as_of="2026-10-20T00:00:00Z",
    )

    assert baseline["status"] == "expired"
    assert baseline["predicted_start"] == "2026-10-08T12:00:00Z"
    assert baseline["predicted_start"] != "2026-10-15T12:00:00Z"
    assert baseline["anchor_event_id"] == "full-1"


def test_new_full_reanchors_normal_and_banked_event_does_not_become_the_anchor():
    as_of = "2026-10-01T00:00:00Z"
    old_baseline = next_reset_baseline(
        _full_anchor("full-old", "2026-10-01T12:00:00Z"), as_of=as_of
    )
    new_baseline = next_reset_baseline(
        _full_anchor("full-new", "2026-10-05T12:00:00Z"), as_of=as_of
    )
    banked_baseline = next_reset_baseline({
        "id": "banked-1",
        "event_type": "SPECIAL_RESET",
        "special_type": "BANKED",
        "occurred_at": "2026-10-05T12:00:00Z",
        "time_basis": "verified_actual_start",
    }, as_of=as_of)

    assert old_baseline["anchor_event_id"] == "full-old"
    assert old_baseline["predicted_start"] == "2026-10-08T12:00:00Z"
    assert new_baseline["anchor_event_id"] == "full-new"
    assert new_baseline["predicted_start"] == "2026-10-12T12:00:00Z"
    assert banked_baseline["status"] == "waiting_for_verified_history"
    assert banked_baseline["unresolved_reason"] == "NO_BUSINESS_FULL_ANCHOR"
