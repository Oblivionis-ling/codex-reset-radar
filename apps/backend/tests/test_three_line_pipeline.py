"""Formal hermetic three-line chain; provider responses are explicit controls.

Only MockTransport supplies fixture responses. The real DeepSeek client,
pipeline, target validation, ledger, API, reader, exporter and scorer execute.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.deepseek import DeepSeekError
from app.main import create_app
from app.logging_runtime import RuntimeLog
from app.prediction_ledger import LateInputRejected
from app.prediction_scoring import evaluate_review, freeze_evaluation_set
from app.review_common import canonical_bytes
from app.review_export import attach_evaluations, export_review, load_verified_review
from app.review_reader import CORE_COLLECTIONS, freeze_review
from test_prediction_review_pipeline import (
    FakeClock, FakeDeepSeekTransport, JudgeAction, PLAN_TWEET_ID, REPLY_TWEET_ID,
    ONLINE_INPUT_TWEET_ID, _judge_result, _ledger_rows, _process_fixture_post,
    _process_fixture_reply, _start_harness, hermetic_io_guard,
)

SEED = "900000000000000201"
BANKED_PLAN = "900000000000000202"
DELAY = "900000000000000203"
COMPLETED_NEXT = "900000000000000204"
FRESH = "900000000000000205"
DECOY = "900000000000000206"


def _effect(body, at, *, target="EXTRA_FULL", stage="announced", future=True):
    return {"temporal_mode": "future" if future else "past", "explicit_announcement": True,
            "event_status": "confirmed", "event_type": "FULL_RESET" if target == "EXTRA_FULL" else "SPECIAL_RESET",
            "special_type": None if target == "EXTRA_FULL" else "BANKED", "canonical_eligible": target == "EXTRA_FULL" and stage == "completed",
            "scope": "all_paid" if target == "EXTRA_FULL" else "banked_only", "execution_stage": stage,
            "event_time_start": at, "event_time_end": None, "time_basis": "explicit_text",
            "evidence_quote": body, "summary": "Explicit synthetic control effect.", "event_title": "Synthetic control",
            "claim_kind": "planned_occurrence" if future else "occurrence"}


def _analysis(identifier, body, effects):
    result = FakeDeepSeekTransport._analysis_result(identifier)
    if effects:
        result.update(effects[0])
        result.update(category="reset_announcement" if effects[0]["temporal_mode"] == "future" else "reset_confirmed", codex_relevant=True)
    result.update(tweet_id=identifier, effects=effects, context_sufficient=True, evidence_quote=body)
    return result


def _target(target, identifier, body, at, *, method="model_inference", lifecycle="planned"):
    return {"target": target, "status": "KNOWN", "method": method,
            "scope": {"value": "all_paid" if target == "EXTRA_FULL" else "banked_only", "certainty": "explicit synthetic fixture"},
            "predicted_start": at, "predicted_end": None, "prediction_form": "point", "source_timezone": "UTC",
            "precision": "fractional_second" if "." in at else "second", "time_basis": "official_planned" if method == "official_time_extraction" else "model_inference",
            "expression": at, "relative_anchor_at": None, "relative_offset_seconds": None,
            "reason": "Explicit synthetic control, not a real model prediction.", "unresolved_reason": None,
            "evidence_post_ids": [], "evidence_refs": [{"tweet_id": identifier, "evidence_quote": body}], "lifecycle": lifecycle}


def _result(full=None, banked=None):
    result = _judge_result(None)
    result["evidence_post_ids"] = []  # Banked must not leak into the old Full field.
    if full is not None:
        result["predictions"]["EXTRA_FULL"] = full
    if banked is not None:
        result["predictions"]["BANKED"] = banked
    return result


def test_formal_three_line_synthetic_sample_and_offline_assessment(settings, tmp_path: Path, monkeypatch):
    actual_started = datetime.now(UTC)
    clock = FakeClock(actual_started - timedelta(days=6))

    class FixtureDatetimeMeta(type):
        def __instancecheck__(cls, value):
            # Clock injection must still accept real owner/process timestamps
            # supplied as ordinary datetime instances by runtime_identity.
            return isinstance(value, datetime)

    class FixtureDatetime(datetime, metaclass=FixtureDatetimeMeta):
        @classmethod
        def now(cls, tz=None):
            value = cls.fromtimestamp(clock.current.timestamp(), UTC)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    # Inject clocks, not validators. Every acquired input is committed before
    # its subsequent semantic as_of; monotonic duration is deliberately real.
    for name in ("prediction_ledger", "deepseek", "pipeline"):
        monkeypatch.setattr(f"app.{name}.utc_text", clock.text)
    monkeypatch.setattr("app.db.utc_now", clock.text)
    monkeypatch.setattr("app.reply_context.now", clock.text)
    for name in ("db", "pipeline", "intelligence", "reply_context", "review_common"):
        monkeypatch.setattr(f"app.{name}.datetime", FixtureDatetime)

    async def scenario():
        harness = await _start_harness(settings, clock)
        db, pipeline, transport = harness.database, harness.pipeline, harness.transport
        scripted = {}
        fallback = transport._analysis_result
        monkeypatch.setattr(transport, "_analysis_result", lambda identifier: copy.deepcopy(scripted.get(identifier, fallback(identifier))))
        try:
            assert pipeline.is_synthetic and harness.model.ledger_attempts_enabled
            async def post(identifier, body, effects):
                scripted[identifier] = _analysis(identifier, body, effects)
                result = await asyncio.wait_for(_process_fixture_post(harness, identifier, body, clock.text(clock.current - timedelta(seconds=1))), 10)
                clock.advance(timedelta(seconds=1))
                return result
            async def judge(result, **kwargs):
                previous = len(transport.judge_attempt_ids)
                transport.queue_judge(JudgeAction(result=result, **kwargs))
                identifier = await asyncio.wait_for(pipeline.run_judge(as_of=None, data_health="HEALTHY"), 15)
                assert identifier > 0
                assert len(transport.judge_attempt_ids) == previous + 1, "two targets use one real client HTTP attempt"
                committed = _ledger_rows(db, "output_committed")[-1]["payload"]
                for target, raw in result["predictions"].items():
                    if raw.get("status") in {"KNOWN", "UNKNOWN"}:
                        validation = committed["target_outputs"][target]["validation"]
                        assert validation["valid"], f"{target} synthetic fixture rejected: {validation['reason']}"
                assert db.validate_judgement(db.get_judgement(identifier), at=clock.text())["valid"]
                clock.advance(timedelta(seconds=1))
                return identifier

            seed_at = clock.text(clock.current - timedelta(minutes=1))
            seed_body = f"SYNTHETIC CONTROL: Full reset completed at {seed_at} UTC for all paid users."
            await post(SEED, seed_body, [_effect(seed_body, seed_at, stage="completed", future=False)])
            assert len(db.list_reset_events(100)) == 1
            seed_event = db.last_full_reset()
            assert seed_event and seed_event["time_basis"] == "explicit_text"
            clock.advance(timedelta(days=1))
            full_at = clock.text(clock.current + timedelta(days=2))
            plan_body = f"SYNTHETIC CONTROL: Full reset planned for {full_at} UTC for all paid users."
            await post(PLAN_TWEET_ID, plan_body, [_effect(plan_body, full_at)])
            await asyncio.wait_for(_process_fixture_reply(harness, clock.text(clock.current - timedelta(seconds=1))), 10)
            clock.advance(timedelta(seconds=1))
            assert db.last_full_reset()["id"] == seed_event["id"], "a future plan is not a completed Full reset"
            first = await judge(_result(_target("EXTRA_FULL", PLAN_TWEET_ID, plan_body, full_at, method="official_time_extraction")))
            first_run = _ledger_rows(db, "run_started")[-1]
            assert first_run["payload"]["selection_mode"] == "online"
            assert set(first_run["payload"]["target_refs"]) == {"EXTRA_FULL", "BANKED"}
            reply = next(row for row in transport.judge_payloads[-1]["context"]["posts"] if row["tweet_id"] == REPLY_TWEET_ID)
            assert reply["reply_context"]["nodes"][0]["text"] == "What is the release window?"
            assert reply["input_hash"]
            forecast_count = len(_ledger_rows(db, "forecast_version"))
            second = await judge(_result(_target("EXTRA_FULL", PLAN_TWEET_ID, plan_body, clock.text(clock.current + timedelta(days=2, hours=1)))))
            second_run = _ledger_rows(db, "run_started")[-1]
            assert first != second and first_run["forecast_id"] == second_run["forecast_id"]
            assert len(_ledger_rows(db, "forecast_version")) == forecast_count
            outputs = {row["judgement_id"]: row["payload"] for row in _ledger_rows(db, "output_committed")}
            assert outputs[first]["target_outputs"]["EXTRA_FULL"]["predicted_start"] != outputs[second]["target_outputs"]["EXTRA_FULL"]["predicted_start"]
            normal_ids = [row["forecast_id"] for row in _ledger_rows(db, "normal_baseline")]

            banked_at = clock.text(clock.current + timedelta(days=1))
            banked_body = f"SYNTHETIC CONTROL: Banked reset cards planned for {banked_at} UTC."
            await post(BANKED_PLAN, banked_body, [_effect(banked_body, banked_at, target="BANKED")])
            banked_plan_judge = await judge(_result(banked=_target("BANKED", BANKED_PLAN, banked_body, banked_at, method="official_time_extraction")))
            banked_plan_run = _ledger_rows(db, "run_started")[-1]
            assert db.last_full_reset()["id"] == seed_event["id"]
            assert [row["forecast_id"] for row in _ledger_rows(db, "normal_baseline")] == normal_ids

            clock.advance(timedelta(days=1))
            delay_at = clock.text(clock.current + timedelta(days=2))
            delay_body = f"SYNTHETIC CONTROL: The Full plan is delayed until {delay_at} UTC."
            await post(DELAY, delay_body, [_effect(delay_body, delay_at, stage="delayed")])
            delayed_judge = await judge(_result(_target("EXTRA_FULL", DELAY, delay_body, delay_at, lifecycle="delayed")))
            delayed_run = _ledger_rows(db, "run_started")[-1]
            assert db.last_full_reset()["id"] == seed_event["id"]

            clock.advance(timedelta(days=1))
            completed_at = clock.text(clock.current - timedelta(minutes=2))
            issued_at = clock.text(clock.current - timedelta(minutes=1))
            next_at = clock.text(clock.current + timedelta(days=3))
            completed_quote = f"Full reset completed at {completed_at} UTC for all paid users."
            issued_quote = f"Banked reset cards were issued at {issued_at} UTC."
            next_quote = f"Next Full reset planned for {next_at} UTC for all paid users."
            combined_body = "SYNTHETIC CONTROL: " + " ".join((completed_quote, issued_quote, next_quote))
            await post(COMPLETED_NEXT, combined_body, [
                _effect(completed_quote, completed_at, stage="completed", future=False),
                _effect(issued_quote, issued_at, target="BANKED", stage="completed", future=False),
                _effect(next_quote, next_at),
            ])
            full_event = db.last_full_reset()
            banked_event = next(row for row in db.list_reset_events(100) if row.get("special_type") == "BANKED")
            assert full_event["id"] != seed_event["id"]
            assert len([row for row in db.list_reset_events(100) if row["event_type"] == "FULL_RESET"]) == 2
            next_judge = await judge(_result(_target("EXTRA_FULL", COMPLETED_NEXT, next_quote, next_at, method="official_time_extraction")))
            next_run = _ledger_rows(db, "run_started")[-1]
            new_normal_ids = [row["forecast_id"] for row in _ledger_rows(db, "normal_baseline")]
            assert new_normal_ids[-1] != normal_ids[-1]
            normal_rows = _ledger_rows(db, "normal_baseline")
            assert {row["payload"]["anchor_event_id"] for row in normal_rows} == {seed_event["id"], full_event["id"]}

            # Actual bounded client retries remain visible, not multiplied by
            # target count. A global provider failure publishes no output.
            committed_before = len(_ledger_rows(db, "output_committed"))
            http_before = len(transport.judge_attempt_ids)
            transport.queue_judge(JudgeAction(status=503)); transport.queue_judge(JudgeAction(status=503))
            with pytest.raises(DeepSeekError):
                await asyncio.wait_for(pipeline.run_judge(as_of=None, data_health="HEALTHY"), 15)
            assert len(transport.judge_attempt_ids) == http_before + 2
            assert len(_ledger_rows(db, "output_committed")) == committed_before
            partial_result = _result(_target("EXTRA_FULL", COMPLETED_NEXT, next_quote, next_at))
            partial_result["predictions"]["BANKED"] = {}
            partial = await judge(partial_result)
            partial_payload = _ledger_rows(db, "output_committed")[-1]["payload"]
            assert partial_payload["prediction_validation"]["status"] == "partial"
            assert partial_payload["target_outputs"]["BANKED"]["validation"]["valid"] is False

            entered, release = asyncio.Event(), asyncio.Event()
            transport.queue_judge(JudgeAction(result=_result(_target("EXTRA_FULL", COMPLETED_NEXT, next_quote, next_at)), entered=entered, release=release))
            inflight = asyncio.create_task(pipeline.run_judge(as_of=None, data_health="HEALTHY"))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                clock.advance(timedelta(seconds=1))
                await post(ONLINE_INPUT_TWEET_ID, "SYNTHETIC CONTROL: newly acquired valid quota context, no occurrence.", [])
                release.set()
                with pytest.raises(LateInputRejected):
                    await asyncio.wait_for(inflight, 10)
            finally:
                release.set()
                if not inflight.done():
                    inflight.cancel()
                    await asyncio.wait_for(asyncio.gather(inflight, return_exceptions=True), 5)
            assert db.latest_judgement()["id"] == partial
            rejection = [row for row in _ledger_rows(db, "attempt_event") if row["payload"].get("event_type") == "late_input_rejected"][-1]
            assert rejection["payload"]["output_available_at"] is None
            assert rejection["payload"]["publication_status"] == "rejected"
            assert rejection["payload"]["input_version_delta"]
            assert not any(row["attempt_id"] == rejection["attempt_id"] for row in _ledger_rows(db, "output_committed"))

            # Human fixture adjudication is explicitly synthetic and revisioned;
            # it does not rewrite business events, forecasts or previous output.
            forecasts_before_truth = copy.deepcopy(_ledger_rows(db, "forecast_version"))
            for event, target, actual in ((full_event, "EXTRA_FULL", completed_at), (banked_event, "BANKED", issued_at)):
                current = max(row["revision"] for row in _ledger_rows(db, "truth_revision") if row["event_id"] == event["id"])
                for revision in range(2):
                    pipeline.prediction_ledger.append_truth(event["id"], current + revision, {
                        "actual_start": actual, "actual_start_end": actual, "actual_time_basis": "synthetic_trusted_fixture",
                        "actual_precision": "fractional_second", "truth_status": "fixture_adjudicated", "adjudication_version": f"synthetic-review-{revision + 1}",
                        "actual_event_type": "FULL_RESET" if target == "EXTRA_FULL" else "SPECIAL_RESET",
                        "special_type": None if target == "EXTRA_FULL" else "BANKED", "scope": event["scope"], "execution_stage": "completed",
                    }, [], "Synthetic human-fixture adjudication, never production truth.", is_synthetic=True)
                    clock.advance(timedelta(seconds=1))
                chain = [row for row in _ledger_rows(db, "truth_revision") if row["event_id"] == event["id"]]
                assert [row["revision"] for row in chain] == [1, 2, 3]
                assert chain[-1]["payload"]["is_synthetic"] is True
            assert _ledger_rows(db, "forecast_version") == forecasts_before_truth
            assert db.last_full_reset()["id"] == full_event["id"]

            # Finish with a genuinely fresh synthetic online acquisition/Judge.
            # Historical outputs are not given a longer valid_until for a demo.
            clock.current = datetime.now(UTC) - timedelta(seconds=3)
            fresh_full = clock.text(clock.current + timedelta(days=1))
            fresh_banked = clock.text(clock.current + timedelta(days=1, hours=1))
            fresh_full_quote = f"Next Full reset planned for {fresh_full} UTC for all paid users."
            fresh_banked_quote = f"Banked cards planned for {fresh_banked} UTC."
            fresh_body = "SYNTHETIC CONTROL: " + fresh_full_quote + " " + fresh_banked_quote
            await post(FRESH, fresh_body, [_effect(fresh_full_quote, fresh_full), _effect(fresh_banked_quote, fresh_banked, target="BANKED")])
            await post(DECOY, "SYNTHETIC CONTROL: unrelated editor keyboard shortcut announcement.", [])
            final_id = await judge(_result(_target("EXTRA_FULL", FRESH, fresh_full_quote, fresh_full, method="official_time_extraction"),
                                           _target("BANKED", FRESH, fresh_banked_quote, fresh_banked, method="official_time_extraction")))
            fresh_run = _ledger_rows(db, "run_started")[-1]
            assert all(value["validation"]["valid"] for value in _ledger_rows(db, "output_committed")[-1]["payload"]["target_outputs"].values())
            assert db.validate_judgement(db.get_judgement(first), at=clock.text())["reason"] != "VALID"
            assert db.validate_judgement(db.get_judgement(final_id), at=clock.text())["valid"]
            api_settings = replace(settings, database_path=db.path, log_dir=tmp_path / "three-line-api-logs", deepseek_api_key="")
            with TestClient(create_app(api_settings, is_synthetic=True)) as api:
                assert api.app.state.pipeline is None, "isolated API smoke must never start a real model worker"
                for component in ("profile_monitor", "replies_monitor", "search_backfill"):
                    assert api.post("/api/v2/collector/heartbeat", json={"component": component, "instance_id": component + "-explicit-synthetic", "sequence": 1}).status_code == 200
                radar_response = api.get("/api/v2/radar")
                assert radar_response.status_code == 200
                radar = radar_response.json()
                assert radar["judgement_id"] == final_id
                assert radar["validation"]["valid"]
                assert radar["display_mode"] == "current"
                assert set(radar["prediction"]["lines"]) == {"NORMAL_WEEKLY", "EXTRA_FULL", "BANKED"}
                for target in ("EXTRA_FULL", "BANKED"):
                    line = radar["prediction"]["lines"][target]
                    assert line["predicted_start"] == (fresh_full if target == "EXTRA_FULL" else fresh_banked)
                    assert line["validity"]["state"] == "valid"
                history_response = api.get("/api/v2/predictions/history", params={"target": "NORMAL_WEEKLY", "limit": 200})
                assert history_response.status_code == 200
                assert len(history_response.json()["items"]) >= 2
            with db.connect() as connection:
                shared_body = connection.execute("SELECT COUNT(*) FROM prediction_artifacts WHERE kind='text_content' AND json_extract(payload_json,'$.text')=?", (plan_body,)).fetchone()[0]
                assert shared_body == 1, "same body/version is reused across Full/Banked shared inputs and repeated outputs"

            # Prune only diagnostics created in this isolated test directory.
            old_log, kept_log = settings.log_dir / "three-line-own-old.jsonl", settings.log_dir / "three-line-own-kept.jsonl"
            old_log.write_text('{"is_synthetic":true}\n', encoding="utf-8")
            kept_log.write_text('{"is_synthetic":true}\n', encoding="utf-8")
            old_time = time.time() - 6 * 86400
            os.utime(old_log, (old_time, old_time))
            RuntimeLog(settings.log_dir, retention_days=5, max_bytes=settings.log_max_bytes).write("app", "SYNTHETIC_THREE_LINE_FIVE_DAY_RETENTION")
            assert not old_log.exists() and kept_log.exists()

            freeze_at = clock.text(clock.current + timedelta(seconds=1))
            selection = {"start": clock.text(datetime.fromisoformat(freeze_at.replace("Z", "+00:00")) - timedelta(days=7)), "end": freeze_at, "series_id": None}
            with db.connect() as connection:
                review = freeze_review(connection, selection, freeze_at)
            stage = tmp_path / "three-line-stage"; stage.mkdir()
            base_path = tmp_path / "three-line-synthetic-base.zip"
            export_review(review, output_path=base_path, staging_dir=stage)
            base = load_verified_review(base_path)
            source = {**base["collections"], "source_binding": base["source_binding"],
                      "package_binding": {key: base[key] for key in ("source_package_sha256", "manifest_sha256")}}
            for target in CORE_COLLECTIONS:
                assert all(row.get("is_synthetic") is True for row in source[target] if not row.get("placeholder")), target
            events = []
            for event, target in ((full_event, "EXTRA_FULL"), (banked_event, "BANKED")):
                truth = max((row for row in source["truth_revisions"] if row["event_id"] == event["id"]), key=lambda row: row["truth_revision"])
                # The same Full round includes the repeated output, the input
                # revision after the Banked plan, and the delayed-plan revision.
                # Their actual target outputs (including accepted UNKNOWN) must
                # remain candidates. NEXT/fresh identify independent rounds;
                # target/date proximity alone never associates them here.
                round_runs = (first_run, second_run, banked_plan_run, delayed_run) if target == "EXTRA_FULL" else (banked_plan_run,)
                forecasts = sorted({run["payload"]["target_refs"][target]["forecast_id"] for run in round_runs})
                events.append({"actual_event_id": str(event["id"]), "target": target, "scope": event["scope"], "association_status": "confirmed",
                               "truth_ref": {"target": "truth_revisions", "id": truth["id"]}, "forecast_ids": forecasts})
            definition = {"id": "formal-synthetic-three-line-set", "observation_cutoff_at": freeze_at,
                          "coverage": {"status": "partial", "start": selection["start"], "end": freeze_at},
                          "rules": {"inclusion": "explicit_fixture_event_identity", "exclusion": "none", "deduplication": "target_event_id", "adjudication_version": "synthetic-review-2"},
                          "events": events, "tie_order": {"basis": "fixed_record_id_order", "output_ids": sorted(row["id"] for row in source["outputs"] if row.get("output_kind") == "judge_output")}}
            frozen = freeze_evaluation_set(source, definition, source["source_binding"])
            full_member = next(row for row in frozen["events"] if row["target"] == "EXTRA_FULL")
            full_candidate_forecasts = {row["id"] for row in full_member["prediction_refs"]}
            assert full_candidate_forecasts == {run["payload"]["target_refs"]["EXTRA_FULL"]["forecast_id"]
                                                for run in (first_run, second_run, banked_plan_run, delayed_run)}
            assert delayed_run["payload"]["target_refs"]["EXTRA_FULL"]["forecast_id"] in full_candidate_forecasts
            assert full_candidate_forecasts.isdisjoint({run["payload"]["target_refs"]["EXTRA_FULL"]["forecast_id"]
                                                        for run in (next_run, fresh_run)})
            assert {row["id"] for row in full_member["output_refs"]} == {str(value) for value in (first, second, banked_plan_judge, delayed_judge)}
            assert {str(next_judge), str(final_id)}.isdisjoint(row["id"] for row in full_member["output_refs"])
            assessment = evaluate_review(source, frozen)
            assert all(sum(row["counts"].values()) == row["N"] == 1 for row in assessment["panels"])
            assert {row["boundary"] for row in assessment["panels"]} == {"first", "last"}
            assert {row["method"] for row in assessment["panels"]} == {"official_time_extraction", "model_inference"}
            full_panels = [row for row in assessment["panels"] if row["target"] == "EXTRA_FULL"]
            for panel in full_panels:
                result = panel["events"][0]
                if panel["method"] == "official_time_extraction":
                    # A sole accepted official target execution is provably
                    # pre-event even when its observation is only an upper bound.
                    assert result["selected_output_ref"]["id"] == str(first)
                    assert result["availability"]["kind"] == "observed_upper_bound"
                    assert result["lead"]["kind"] == "lower_bound"
                else:
                    # Multiple observational upper bounds do not prove actual
                    # first/last order; publication sequence is not exact time.
                    assert result["category"] == "undetermined"
                    assert result["selected_output_ref"] is None
                    assert "first_last_order_or_precedence_unproven" in result["reason_codes"]
            final_path = tmp_path / "three-line-synthetic-scored.zip"
            exported = export_review(attach_evaluations(review, evaluation_sets=[frozen], assessments=[assessment]), output_path=final_path, staging_dir=stage)
            assert exported["verification"]["assessments_reproduced"] == 1
            verified = load_verified_review(final_path)
            assert verified["manifest"]["synthetic_provenance"]["status"] == "SYNTHETIC"
            assert verified["manifest"]["synthetic_provenance"]["counts"]["undeclared"] == 0
            attempt_rows = [row for row in verified["collections"]["attempts"] if row.get("is_attempt")]
            assert len(attempt_rows) == len(transport.all_attempt_ids) == transport.send_persistence_checks
            assert set(row["attempt_id"] for row in attempt_rows) == set(transport.all_attempt_ids)
            exported_rejected = [event for row in verified["collections"]["attempts"] for event in row.get("events", []) if event.get("event_type") == "late_input_rejected"]
            assert exported_rejected and exported_rejected[-1]["output_available_at"] is None and exported_rejected[-1]["input_version_delta"]
            receipt = {"status": "FORMAL_SYNTHETIC_CHAIN_AND_PACKAGE_VERIFIED", "is_synthetic": True,
                       "database": str(settings.database_path), "package": str(final_path), "verification": exported["verification"],
                       "counts": verified["manifest"]["counts"], "provenance": verified["manifest"]["synthetic_provenance"],
                       "clock": {"wall_clock": "explicit injected synthetic UTC", "monotonic": "actual interpreter monotonic, not fabricated", "actual_started_utc": actual_started.isoformat(), "final_synthetic_utc": clock.text()},
                       "http_attempts": len(attempt_rows), "http_by_operation": {key: len(value) for key, value in transport.attempt_ids_by_operation.items()},
                       "run_lifecycle_objects": sum(row.get("record_type") == "run_lifecycle" for row in verified["collections"]["attempts"]),
                       "latest_judgement_id": final_id, "latest_validation": db.validate_judgement(db.get_judgement(final_id), at=clock.text()),
                       "api_smoke": {"radar_http": radar_response.status_code, "history_http": history_response.status_code, "three_targets_present": True, "latest_judge_valid": True, "real_client_worker_started": False},
                       "retention": {"days": 5, "own_old_log_removed": not old_log.exists(), "own_fresh_log_retained": kept_log.exists(), "ledger_and_scoring_exported_after_prune": True},
                       "shared_plan_body_artifacts": shared_body, "real_model_calls": 0, "smtp_calls": 0,
                       "full_round_scoring_candidates": {"forecast_ids": sorted(full_candidate_forecasts),
                           "output_ids": sorted(row["id"] for row in full_member["output_refs"]),
                           "delayed_forecast_included": True, "next_and_fresh_excluded": True,
                           "first_last": [{key: row[key] for key in ("method", "boundary", "threshold_hours", "counts", "events")}
                                          for row in full_panels]},
                       "evaluation_set_hash": frozen["set_hash"], "assessment_hash": assessment["assessment_hash"],
                       "limitations": ["Mock responses are controls, not prediction accuracy evidence", "Formal observations retain upper-bound semantics; stable publication sequence is not exact availability"]}
            (tmp_path / "synthetic-acceptance.json").write_bytes(canonical_bytes(receipt))
            (tmp_path / "evaluation-definition.json").write_bytes(canonical_bytes(definition))
        finally:
            await harness.close()
    asyncio.run(asyncio.wait_for(scenario(), 90))
