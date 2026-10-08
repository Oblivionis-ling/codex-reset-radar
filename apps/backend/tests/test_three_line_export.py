from __future__ import annotations

import copy
import hashlib
import json
import smtplib
import stat
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.review_common import canonical_bytes, sha256_json
from app.review_export import (
    ReviewExportError, ReviewPackageValidationError, artifact_measurement, export_review,
    partition_review, preview_review, verify_coverage, verify_review,
    load_verified_review, attach_evaluations,
)
from app.review_reader import ReviewReadError, ReviewRangeTooLarge, core_collection_binding, freeze_review, record_digest, with_record_digests
from test_review_export import _artifact, _connection, _integrated_connection, _ledger, _network_is_forbidden


WINDOW = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-08T00:00:00Z", "series_id": None}
FREEZE = WINDOW["end"]


@pytest.fixture(autouse=True)
def smtp_forbidden(monkeypatch: pytest.MonkeyPatch):
    def reject(*_args, **_kwargs):
        raise AssertionError("export fixtures must never send SMTP")
    for name in ("SMTP", "SMTP_SSL", "LMTP"):
        monkeypatch.setattr(smtplib, name, reject)


def _seven_days() -> sqlite3.Connection:
    """Existing direct-record contract, not fabricated modern dual-target data."""
    connection = _connection()
    body = _artifact(connection, "same-version-body", "text_content", {
        "text": "Synthetic shared historical body version only.", "tweet_id": "900000000000000001",
        "author": "@Fixture", "role": "target_post", "source_version": "f" * 64,
    }, recorded_at="2026-09-30T12:00:00Z")
    seq = 0
    for day in range(7):
        stamp = (datetime(2026, 10, 1, 12, tzinfo=UTC) + timedelta(days=day)).isoformat().replace("+00:00", "Z")
        run, attempt, forecast = f"run-{day}", f"http-{day}", f"forecast-{day}"
        records = [
            ("forecast_version", {"target": "EXTRA_FULL", "is_synthetic": True, "record_kind": "replay", "method": "model_inference"}),
            ("run_started", {"is_synthetic": True, "input_artifact_refs": [body]}),
            ("attempt_started", {"stage": "radar_judge", "is_synthetic": True}),
            ("output_committed", {"output_id": f"output-{day}", "structured_output": {"action_level": "YELLOW"},
                                  "validation": {"status": "accepted"}, "accepted_attempt_id": attempt}),
        ]
        for kind, payload in records:
            seq += 1
            _ledger(connection, seq, kind, payload, occurred_at=stamp, recorded_at=stamp,
                    run_id=run, attempt_id=attempt if kind in {"attempt_started", "output_committed"} else None,
                    forecast_id=forecast, series_id=f"series-{day}", revision=1 if kind == "forecast_version" else None)
    connection.commit()
    return connection


def _stage(tmp_path: Path) -> Path:
    path = tmp_path / "staging"
    path.mkdir()
    return path


def _rewrite_package(path: Path, change) -> Path:
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    change(members, manifest)
    for name, entry in manifest["files"].items():
        entry["sha256"] = hashlib.sha256(members[name]).hexdigest()
        entry["size_bytes"] = len(members[name])
    members["manifest.json"] = canonical_bytes(manifest)
    other = path.with_name(path.stem + "-tampered.zip")
    with zipfile.ZipFile(other, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value)
    return other


def test_digest_uses_common_lf_and_only_strips_typed_reference_digest():
    record = {"id": "dto", "sha256": "content-digest", "nested": {"sha256": "also-content"},
              "ref": {"target": "outputs", "id": "output", "status": "included", "reason": None, "sha256": "reference-only"}}
    projected = copy.deepcopy(record)
    del projected["ref"]["sha256"]
    assert record_digest(record) == sha256_json(projected)
    assert record_digest(record) == hashlib.sha256(canonical_bytes(projected)).hexdigest()
    changed = copy.deepcopy(record)
    changed["record_sha256"] = "own-only"
    changed["ref"]["sha256"] = "changed-reference"
    assert record_digest(changed) == record_digest(record)
    changed["nested"]["sha256"] = "changed-content"
    assert record_digest(changed) != record_digest(record)


def test_v2_mapper_normalizes_legacy_role_decoration_before_final_digest():
    material = {"metadata": {"activity_roots": []},
                "public_evidence": [{"id": "body-version", "text": "Synthetic exact body version", "role": "target_post"}],
                "outputs": [{"id": "processing-output", "evidence_refs": [{"target": "public_evidence", "id": "body-version", "status": "included", "reason": None, "role": "target_post"}]}]}
    final = with_record_digests(material)
    reference = final["outputs"][0]["evidence_refs"][0]
    assert set(reference) == {"target", "id", "status", "reason", "sha256"}
    assert final["public_evidence"][0]["role"] == "target_post"
    assert reference["sha256"] == final["public_evidence"][0]["record_sha256"]
    assert final["outputs"][0]["record_sha256"] == record_digest(final["outputs"][0])
    assert material["outputs"][0]["evidence_refs"][0]["role"] == "target_post"
    material["outputs"][0]["evidence_refs"][0]["unapproved_field"] = "do not silently accept"
    with pytest.raises(ReviewReadError, match="typed_reference_fields_unsupported"):
        with_record_digests(material)


def test_frozen_preview_and_export_never_reread_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    connection, bait = _integrated_connection()
    review = freeze_review(connection, WINDOW, FREEZE)
    before = copy.deepcopy(review)
    connection.close()
    import app.review_export as module
    monkeypatch.setattr(module, "read_review", lambda *_args, **_kwargs: pytest.fail("source was reread"))
    preview = preview_review(review)
    assert preview["source_binding"]["sourcekind"] == "readonly_transaction"
    assert preview["source_binding"]["source_sha256"] is None
    result = export_review(review, output_path=tmp_path / "v2.zip", staging_dir=_stage(tmp_path))
    assert result["verification"]["valid"]
    assert result["manifest"]["schema_version"] == "crr-review-package-v2"
    assert result["manifest"]["files"]["evaluation-sets.jsonl"]["records"] == 0
    assert result["manifest"]["source_binding"] == preview["source_binding"]
    assert bait["secret"] not in json.dumps(review)
    assert review == before


def test_verified_snapshot_binding_checks_connection_hash_and_wal(tmp_path: Path):
    source = _seven_days()
    path = tmp_path / "snapshot.sqlite"
    target = sqlite3.connect(path)
    source.backup(target)
    target.close()
    source.close()
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
    review = freeze_review(connection, WINDOW, FREEZE, snapshot_file=path, source_sha256=expected)
    assert review["metadata"]["source_binding"]["source_sha256"] == expected
    assert review["metadata"]["source_binding"]["sourcekind"] == "verified_snapshot_file"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    with pytest.raises(ReviewReadError, match="sha256_mismatch"):
        freeze_review(connection, WINDOW, FREEZE, snapshot_file=path, source_sha256="0" * 64)
    wrong = tmp_path / "different.sqlite"
    wrong.write_bytes(path.read_bytes())
    with pytest.raises(ReviewReadError, match="does_not_match_connection"):
        freeze_review(connection, WINDOW, FREEZE, snapshot_file=wrong, source_sha256=expected)
    wal = Path(str(path) + "-wal")
    wal.write_bytes(b"nonempty stale candidate WAL")
    with pytest.raises(ReviewReadError, match="nonempty_wal"):
        freeze_review(connection, WINDOW, FREEZE, snapshot_file=path, source_sha256=expected)
    connection.close()


def test_transaction_digest_and_highwater_are_frozen_in_one_read(tmp_path: Path):
    source = _seven_days()
    path = tmp_path / "transaction.sqlite"
    destination = sqlite3.connect(path)
    source.backup(destination)
    destination.execute("PRAGMA journal_mode=WAL")
    source.close()
    reader = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
    first = freeze_review(reader, WINDOW, FREEZE)
    _ledger(destination, 29, "run_started", {"is_synthetic": True}, run_id="later-run")
    destination.commit()
    second = freeze_review(reader, WINDOW, FREEZE)
    assert first["metadata"]["source_binding"]["high_water"] == 28
    assert second["metadata"]["source_binding"]["high_water"] == 29
    assert first["metadata"]["source_binding"]["snapshot_id"] != second["metadata"]["source_binding"]["snapshot_id"]
    assert first["metadata"]["source_binding"]["source_sha256"] is None
    reader.close()
    destination.close()


def test_v1_verifier_remains_strict_while_v2_has_exact_member_set(tmp_path: Path):
    connection = _seven_days()
    stage = _stage(tmp_path)
    old = export_review(connection, WINDOW, FREEZE, tmp_path / "v1.zip", stage)
    assert old["verification"]["schema_version"] == "crr-review-package-v1"
    def extra(members, _manifest):
        members["evaluation-sets.jsonl"] = b""
    bad = _rewrite_package(tmp_path / "v1.zip", extra)
    with pytest.raises(ReviewPackageValidationError, match="schema_member_set"):
        verify_review(bad)
    frozen = freeze_review(connection, WINDOW, FREEZE)
    export_review(frozen, output_path=tmp_path / "modern.zip", staging_dir=stage)
    def drop(members, _manifest):
        del members["evaluation-sets.jsonl"]
        del _manifest["files"]["evaluation-sets.jsonl"]
    bad = _rewrite_package(tmp_path / "modern.zip", drop)
    with pytest.raises(ReviewPackageValidationError, match="schema_member_set"):
        verify_review(bad)
    connection.close()


@pytest.mark.parametrize("tamper", ["record", "reference", "binding", "freeze"])
def test_v2_hash_and_binding_tampering_rejected_even_with_member_hashes_updated(tmp_path: Path, tamper: str):
    connection = _seven_days()
    frozen = freeze_review(connection, WINDOW, FREEZE)
    package = tmp_path / "original.zip"
    export_review(frozen, output_path=package, staging_dir=_stage(tmp_path))
    def mutate(members, manifest):
        if tamper in {"binding", "freeze"}:
            manifest["source_binding"]["transaction_snapshot_digest" if tamper == "binding" else "freeze_at"] = "0" * 64 if tamper == "binding" else "2026-10-09T00:00:00Z"
        else:
            rows = [json.loads(line) for line in members["outputs.jsonl"].splitlines()]
            if tamper == "record":
                rows[0]["structured_output"]["action_level"] = "RED"
            else:
                rows[0]["references"]["attempt"]["sha256"] = "0" * 64
            members["outputs.jsonl"] = b"".join(canonical_bytes(row) for row in rows)
    bad = _rewrite_package(package, mutate)
    with pytest.raises(ReviewPackageValidationError, match="digest_mismatch|snapshot_id_mismatch"):
        verify_review(bad)
    connection.close()


def test_seven_day_partitions_keep_all_activity_and_stable_dependencies(tmp_path: Path):
    connection = _seven_days()
    with pytest.raises(ReviewRangeTooLarge):
        freeze_review(connection, WINDOW, FREEZE, max_records=12)
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True, max_records=12)
    preview = preview_review(review, multipart=True, max_records=12)
    assert preview["multipart"]["parts"] > 1
    with pytest.raises(ReviewRangeTooLarge, match="single_package"):
        export_review(review, output_path=tmp_path / "too-big.zip", staging_dir=_stage(tmp_path), max_records=12)
    result = export_review(review, output_path=tmp_path / "week.zip", staging_dir=tmp_path / "staging", multipart=True, max_records=12)
    assert verify_coverage(Path(result["coverage"]))["valid"]
    coverage = json.loads(Path(result["coverage"]).read_bytes())
    assert coverage["window"]["start_utc"] == WINDOW["start"]
    assert coverage["window"]["end_utc_exclusive"] == WINDOW["end"]
    assert len(coverage["activity_roots"]) == 28
    assert sum(len(part["activity_roots"]) for part in coverage["parts"]) == 28
    assert len({root["id"] for part in coverage["parts"] for root in part["activity_roots"]}) == 28
    assert coverage["measurement"]["cross_package_repeat_occurrences"] > 0
    seen = {}
    for child in result["parts"]:
        with zipfile.ZipFile(child) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["source_binding"] == review["metadata"]["source_binding"]
            assert sum(manifest["counts"].values()) <= 12
            for name in ("public-evidence.jsonl", "input-snapshots.jsonl"):
                for line in archive.read(name).splitlines():
                    row = json.loads(line)
                    identity = (name, row["id"])
                    assert identity not in seen or seen[identity] == row
                    seen[identity] = row
    connection.close()


@pytest.mark.parametrize("tamper", ["omit", "duplicate", "path", "hash"])
def test_coverage_rejects_omissions_duplicates_paths_and_hashes(tmp_path: Path, tamper: str):
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True, max_records=12)
    result = export_review(review, output_path=tmp_path / "week.zip", staging_dir=_stage(tmp_path), multipart=True, max_records=12)
    path = Path(result["coverage"])
    coverage = json.loads(path.read_bytes())
    if tamper == "omit":
        coverage["parts"].pop()
    elif tamper == "duplicate":
        coverage["parts"].append(coverage["parts"][0])
    elif tamper == "path":
        coverage["parts"][0]["file"] = "../escape.zip"
    else:
        coverage["parts"][0]["sha256"] = "0" * 64
    path.write_bytes(canonical_bytes(coverage))
    with pytest.raises(ReviewPackageValidationError):
        verify_coverage(path)
    connection.close()


def test_unbreakable_root_closure_and_limits_fail_without_publish(tmp_path: Path):
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True)
    with pytest.raises(ReviewRangeTooLarge, match="single_activity_root"):
        partition_review(review, max_records=2)
    with pytest.raises(ReviewExportError, match="between_1_and_20000"):
        export_review(review, output_path=tmp_path / "bypass.zip", staging_dir=_stage(tmp_path), max_records=20_001)
    assert not list(tmp_path.glob("*.zip"))
    connection.close()


def test_artifact_measurement_does_not_merge_different_versions():
    base = {"id": "one", "tweet_id": "123", "content_version": "version-one", "text": "body", "is_synthetic": True}
    duplicate = {**base, "id": "two"}
    revised = {**base, "id": "three", "content_version": "version-two"}
    result = artifact_measurement({"public_evidence": [base, duplicate, revised]})
    assert result["artifact_objects"] == 3
    assert result["distinct_version_projections"] == 2
    assert result["duplicate_version_projections"] == 1
    assert result["duplicate_projected_utf8_bytes"] == len(canonical_bytes(duplicate))


def test_actual_20000_record_boundary_materializes_then_partitions_without_bypass():
    connection = _connection()
    for seq in range(1, 20_002):
        _ledger(connection, seq, "run_started", {"is_synthetic": True}, run_id=f"bounded-run-{seq}")
    connection.commit()
    with pytest.raises(ReviewRangeTooLarge, match="more_than_20000"):
        freeze_review(connection, WINDOW, FREEZE)
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True)
    assert len(review["attempts"]) == 20_001
    assert len(review["metadata"]["activity_roots"]) == 20_001
    parts = partition_review(review)
    assert len(parts) == 2
    assert [len(part["attempts"]) for part in parts] == [20_000, 1]
    assert sum(len(part["metadata"]["activity_roots"]) for part in parts) == 20_001
    assert all(part["metadata"]["max_records"] == 20_000 for part in parts)
    connection.close()


def test_materialization_and_source_scan_remain_bounded(monkeypatch: pytest.MonkeyPatch):
    import app.review_reader as reader
    connection = _seven_days()
    monkeypatch.setattr(reader, "MAX_FROZEN_DTO_BYTES", 10)
    with pytest.raises(ReviewRangeTooLarge, match="materialization_byte_limit"):
        freeze_review(connection, WINDOW, FREEZE, multipart=True)
    assert not connection.in_transaction
    monkeypatch.setattr(reader, "MAX_FROZEN_DTO_BYTES", 100 * 1024 * 1024)
    monkeypatch.setattr(reader, "MAX_SOURCE_ROWS", 20)
    with pytest.raises(ReviewRangeTooLarge, match="snapshot_source_prediction_ledger"):
        freeze_review(connection, WINDOW, FREEZE, multipart=True)
    assert not connection.in_transaction
    connection.close()


def test_v2_no_clobber_keeps_racing_winner_and_staging_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.review_export as module
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE)
    stage = _stage(tmp_path)
    owner = stage / "caller-owned.txt"
    owner.write_text("keep", encoding="utf-8")
    output = tmp_path / "winner.zip"
    original_link = module.os.link
    def race(source, destination):
        if Path(destination) == output:
            output.write_bytes(b"racing publisher remains intact")
        return original_link(source, destination)
    monkeypatch.setattr(module.os, "link", race)
    with pytest.raises(FileExistsError, match="already_exists"):
        export_review(review, output_path=output, staging_dir=stage)
    assert output.read_bytes() == b"racing publisher remains intact"
    assert [path.name for path in stage.iterdir()] == [owner.name]
    connection.close()


def test_multipart_no_clobber_never_publishes_false_complete_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.review_export as module
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True, max_records=12)
    stage = _stage(tmp_path)
    original_link = module.os.link
    winner = tmp_path / "week-part-0002.zip"
    def race(source, destination):
        if Path(destination) == winner:
            winner.write_bytes(b"another publisher")
        return original_link(source, destination)
    monkeypatch.setattr(module.os, "link", race)
    with pytest.raises(FileExistsError, match="partial_multipart"):
        export_review(review, output_path=tmp_path / "week.zip", staging_dir=stage, multipart=True, max_records=12)
    assert winner.read_bytes() == b"another publisher"
    assert (tmp_path / "week-part-0001.zip").exists()
    assert not (tmp_path / "week.coverage.json").exists()
    assert list(stage.iterdir()) == []
    connection.close()


def _modern_target(target: str, when: str, *, method: str = "model_inference") -> dict:
    return {"target": target, "status": "KNOWN", "method": method, "predicted_start": when,
            "predicted_end": None, "prediction_form": "start_only", "source_timezone": "UTC",
            "precision": "minute", "time_basis": "official_planned" if method == "official_time_extraction" else "model_inference",
            "expression": when, "relative_anchor_at": None, "reason": "Synthetic stored contract DTO only.",
            "unresolved_reason": None, "evidence_post_ids": [], "evidence_refs": [], "lifecycle": "planned",
            "validation": {"valid": True, "reason": "VALID", "date_status": "KNOWN"}}


def test_dual_target_outputs_keep_question_versions_and_each_output_dates(tmp_path: Path):
    connection = _connection()
    refs = {target: {"forecast_id": identifier, "series_id": "series-" + target, "revision": 1, "previous_id": None}
            for target, identifier in (("EXTRA_FULL", "full-question"), ("BANKED", "banked-question"))}
    for seq, target in enumerate(refs, 1):
        _ledger(connection, seq, "forecast_version", {"target": target, "version_role": "question_version", "method": None,
                                                      "is_synthetic": True}, forecast_id=refs[target]["forecast_id"], series_id=refs[target]["series_id"], revision=1)
    _ledger(connection, 3, "run_started", {"is_synthetic": True, "target_refs": refs, "prediction_contract_version": "crr-prediction-targets-v1"},
            forecast_id="full-question", run_id="shared-run", series_id="series-EXTRA_FULL")
    _ledger(connection, 4, "attempt_started", {"stage": "radar_judge"}, forecast_id="full-question", run_id="shared-run", attempt_id="shared-http")
    first = {"EXTRA_FULL": _modern_target("EXTRA_FULL", "2026-10-04T10:00:00Z", method="official_time_extraction"),
             "BANKED": _modern_target("BANKED", "2026-10-05T12:00:00Z")}
    second = {"EXTRA_FULL": _modern_target("EXTRA_FULL", "2026-10-06T10:00:00Z"),
              "BANKED": {"target": "BANKED", "status": None, "validation": {"valid": False, "reason": "MISSING_TARGET"},
                         "rejected_output": {"predicted_start": "2026-10-07T00:00:00Z", "raw_json": "must not export"}}}
    for seq, identifier, targets, status in ((5, "shared-output-1", first, "accepted"), (6, "shared-output-2", second, "partial")):
        _ledger(connection, seq, "output_committed", {"output_id": identifier, "target_refs": refs, "target_outputs": targets,
                                                     "prediction_validation": {"status": status, "accepted_targets": [key for key, child in targets.items() if child["validation"]["valid"]]},
                                                     "prediction_contract_version": "crr-prediction-targets-v1",
                                                     "structured_output": {"action_level": "YELLOW", "predictions": targets}, "validation": {"status": status}},
                forecast_id="full-question", run_id="shared-run", attempt_id="shared-http")
    _ledger(connection, 7, "output_observed", {"output_id": "shared-output-1", "observed_at": "2026-10-03T12:02:00Z",
                                              "source": "formal_read_post_commit_upper_bound", "clock_anomaly": "wall_clock_reversed",
                                              "time_limitation": "timestamps_retained_without_ordering"}, forecast_id="full-question", run_id="shared-run", attempt_id="shared-http")
    connection.commit()
    # Selecting Banked also closes the shared output/attempt and Full question.
    review = freeze_review(connection, {**WINDOW, "series_id": "series-BANKED"}, FREEZE)
    assert {row["id"] for row in review["forecasts"]} == {"full-question", "banked-question"}
    assert all(row["method"] is None and row["version_role"] == "question_version" and "predicted_start" not in row for row in review["forecasts"])
    outputs = {row["id"]: row for row in review["outputs"]}
    assert outputs["shared-output-1"]["target_outputs"]["EXTRA_FULL"]["predicted_start"] == "2026-10-04T10:00:00Z"
    assert outputs["shared-output-2"]["target_outputs"]["EXTRA_FULL"]["predicted_start"] == "2026-10-06T10:00:00Z"
    assert outputs["shared-output-2"]["target_outputs"]["BANKED"]["validation"]["valid"] is False
    assert "raw_json" not in json.dumps(review)
    assert outputs["shared-output-1"]["availability_source"] == "formal_read_post_commit_upper_bound"
    assert outputs["shared-output-1"]["availability_observations"][0]["ledger_seq"] == 7
    assert outputs["shared-output-1"]["availability_observations"][0]["clock_anomaly"] == "wall_clock_reversed"
    assert outputs["shared-output-2"]["output_available_at"] is None
    for row in outputs.values():
        assert set(row["target_forecast_refs"]) == {"EXTRA_FULL", "BANKED"}
        assert all(ref["status"] == "included" and len(ref["sha256"]) == 64 for ref in row["target_forecast_refs"].values())
    assert len([row for row in review["attempts"] if row.get("is_attempt")]) == 1
    assert len([row for row in review["attempts"] if row.get("record_type") == "run_lifecycle"]) == 1
    assert len(review["outputs"]) == 2
    assert export_review(review, output_path=tmp_path / "dual.zip", staging_dir=_stage(tmp_path))["verification"]["valid"]
    connection.close()


def test_normal_history_is_persisted_not_legacy_compatibility_or_fake_http(tmp_path: Path):
    connection = _connection()
    for seq, forecast, prior, anchor, day in ((1, "normal-one", None, 21, "2026-10-04T12:00:00Z"),
                                           (3, "normal-two", "normal-one", 22, "2026-10-06T12:00:00Z")):
        reference = {"forecast_id": forecast, "series_id": "normal-series", "revision": 1 if prior is None else 2, "previous_id": prior}
        baseline = {"target": "NORMAL_WEEKLY", "method": None, "status": "expired", "predicted_start": day,
                    "predicted_end": None, "prediction_form": "proxy", "precision": "unknown", "source_timezone": None,
                    "anchor_event_id": anchor, "anchor_time_basis": "post_time_proxy", "anchor_limitation": "POST_TIME_PROXY_NOT_ACTUAL_START",
                    "time_basis": "user_full_plus_7d", "basis": "User reference; not an official promise."}
        _ledger(connection, seq, "normal_baseline", {**reference, "target": "NORMAL_WEEKLY", "record_kind": "baseline",
                                                     "method": None, "basis": "user_full_plus_7d", "forecast": baseline,
                                                     "target_refs": {"NORMAL_WEEKLY": reference}, "target_outputs": {"NORMAL_WEEKLY": baseline},
                                                     "anchor_event_id": anchor, "output_id": "normal-" + forecast, "is_synthetic": True},
                forecast_id=forecast, series_id="normal-series", event_id=anchor, revision=reference["revision"])
        _ledger(connection, seq + 1, "output_observed", {"output_id": "normal-" + forecast, "observed_at": "2026-10-03T12:01:00Z",
                                                       "source": "formal_read_post_commit_upper_bound", "is_synthetic": True},
                forecast_id=forecast, series_id="normal-series")
    connection.commit()
    review = freeze_review(connection, WINDOW, FREEZE)
    assert review["metadata"]["capabilities"]["normal_baseline_history"] == "RECORDED_FROM_IMPLEMENTATION_ONLY"
    assert not any(row.get("source_kind") == "normal_baseline_compatibility_view" for row in review["forecasts"])
    assert {row["id"] for row in review["outputs"]} == {"normal-normal-one", "normal-normal-two"}
    assert all(row["output_kind"] == "normal_baseline_output" and row["is_synthetic"] is True for row in review["outputs"])
    assert not review["attempts"]
    assert all(row["basis"] == "user_full_plus_7d" for row in review["forecasts"])
    assert next(row for row in review["forecasts"] if row["id"] == "normal-two")["previous_id"] == "normal-one"
    assert all(row["target_outputs"]["NORMAL_WEEKLY"]["status"] == "expired" for row in review["outputs"])
    assert export_review(review, output_path=tmp_path / "normal.zip", staging_dir=_stage(tmp_path))["verification"]["valid"]
    connection.close()


def test_freeze_is_one_query_only_transaction_and_source_dml_is_denied():
    connection = _seven_days()
    traces = []
    forbidden = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                 sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE}
    def authorize(action, _arg1, _arg2, _database, _trigger):
        assert action not in forbidden, "frozen reader attempted source DML/DDL"
        return sqlite3.SQLITE_OK
    connection.set_authorizer(authorize)
    connection.set_trace_callback(traces.append)
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True)
    assert [query for query in traces if query in {"BEGIN", "COMMIT", "ROLLBACK"}] == ["BEGIN", "COMMIT"]
    assert not any("wal_checkpoint" in query.lower() for query in traces)
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    assert review["metadata"]["source_binding"]["sourcekind"] == "readonly_transaction"
    connection.close()


def test_normal_anchor_privacy_keeps_time_proof_without_private_payload():
    from app.review_privacy import PrivacyContext, sanitize_dto
    source = {"input_frame": {"normal_anchor": {"id": 23, "event_type": "FULL_RESET", "occurred_at": "2026-10-01T00:00:00Z",
                                               "time_basis": "post_time_proxy", "provenance": {"precision": "day", "source_timezone": "UTC", "raw_json": "omit"},
                                               "request_body": "omit"}, "is_synthetic": True}}
    safe = sanitize_dto(source, {"input_frame"}, PrivacyContext.from_sources([source]))
    anchor = safe["input_frame"]["normal_anchor"]
    assert anchor["event_id"] == 23 and anchor["time_basis"] == "post_time_proxy"
    assert anchor["time_metadata"] == {"precision": "day", "source_timezone": "UTC"}
    assert "raw_json" not in json.dumps(safe) and "request_body" not in json.dumps(safe)


def test_core_collection_basis_excludes_result_attachment_and_zip_metadata():
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE)
    basis = core_collection_binding(review)
    attached = copy.deepcopy(review)
    attached["evaluation_sets"] = [{"id": "only-binding-test-not-a-valid-evaluation-set"}]
    attached["assessments"] = [{"id": "only-binding-test-not-a-valid-assessment"}]
    attached["metadata"]["source_package_sha256"] = "0" * 64
    assert core_collection_binding(attached) == basis
    attached["outputs"][0]["reason_summary"] = "Changed scoring input."
    attached["outputs"][0]["record_sha256"] = record_digest(attached["outputs"][0])
    assert core_collection_binding(attached) != basis
    assert review["metadata"]["core_collection_binding"] == basis
    connection.close()


def test_coverage_recomputes_global_core_basis_not_just_child_file_hashes(tmp_path: Path):
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True, max_records=12)
    result = export_review(review, output_path=tmp_path / "week.zip", staging_dir=_stage(tmp_path), multipart=True, max_records=12)
    assert result["verification"]["valid"]
    coverage_path = Path(result["coverage"])
    coverage = json.loads(coverage_path.read_bytes())
    assert coverage["core_collection_binding"] == core_collection_binding(review)
    coverage["core_collection_binding"]["collections"]["outputs"]["records"] += 1
    coverage_path.write_bytes(canonical_bytes(coverage))
    with pytest.raises(ReviewPackageValidationError, match="core_collection_binding_mismatch"):
        verify_coverage(coverage_path)
    connection.close()


def test_banked_capability_requires_accepted_output_not_question_or_failed_run():
    connection = _connection()
    refs = {"BANKED": {"forecast_id": "banked-question", "series_id": "banked-series", "revision": 1, "previous_id": None}}
    _ledger(connection, 1, "forecast_version", {"target": "BANKED", "version_role": "question_version", "method": None,
                                               "is_synthetic": True}, forecast_id="banked-question", series_id="banked-series")
    _ledger(connection, 2, "run_started", {"is_synthetic": True, "target_refs": refs}, run_id="failed-run", forecast_id="banked-question")
    connection.commit()
    initial = freeze_review(connection, WINDOW, FREEZE)
    assert initial["metadata"]["capabilities"]["independent_banked_forecasts"] == "NOT_RECORDED_IN_FROZEN_SOURCE"
    connection.execute("PRAGMA query_only=OFF")
    _ledger(connection, 3, "output_committed", {"output_id": "rejected-banked-partial", "target_refs": refs,
                                              "target_outputs": {"BANKED": {"target": "BANKED", "validation": {"valid": False}}}},
            forecast_id="banked-question", run_id="failed-run")
    connection.commit()
    rejected = freeze_review(connection, WINDOW, FREEZE)
    assert rejected["metadata"]["capabilities"]["independent_banked_forecasts"] == "NOT_RECORDED_IN_FROZEN_SOURCE"
    connection.execute("PRAGMA query_only=OFF")
    _ledger(connection, 4, "output_committed", {"output_id": "accepted-banked", "target_refs": refs,
                                              "target_outputs": {"BANKED": _modern_target("BANKED", "2026-10-05T12:00:00Z")}},
            forecast_id="banked-question", run_id="failed-run")
    connection.commit()
    accepted = freeze_review(connection, WINDOW, FREEZE)
    assert accepted["metadata"]["capabilities"]["independent_banked_forecasts"] == "RECORDED_ACCEPTED_TARGET_OUTPUT"
    connection.close()


def test_shared_loader_uses_verified_bytes_and_returns_core_binding(tmp_path: Path):
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE)
    output = tmp_path / "source.zip"
    export_review(review, output_path=output, staging_dir=_stage(tmp_path))
    loaded = load_verified_review(output)
    assert loaded["verification"]["valid"]
    assert loaded["source_package_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert loaded["core_collection_binding"] == core_collection_binding(review)
    assert loaded["source_binding"] == review["metadata"]["source_binding"]
    assert loaded["core_binding_scope"] == "standalone_package"
    assert loaded["collections"]["outputs"] == review["outputs"]
    connection.close()


@pytest.mark.parametrize("replacement_at", ["before_capture", "after_capture"])
def test_coverage_hash_is_bound_to_captured_zip_not_reopened_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement_at: str,
):
    import app.review_export as module
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True, max_records=12)
    result = export_review(review, output_path=tmp_path / "week.zip", staging_dir=_stage(tmp_path), multipart=True, max_records=12)
    coverage_path = Path(result["coverage"])
    coverage = json.loads(coverage_path.read_bytes())
    child = Path(result["parts"][0])
    replacement = _rewrite_package(child, lambda members, _manifest: members.__setitem__("README.md", members["README.md"] + b"\nDistinct delivery audit text.\n"))
    original_bytes, replacement_bytes = child.read_bytes(), replacement.read_bytes()
    assert original_bytes != replacement_bytes
    assert load_verified_review(child)["core_collection_binding"] == load_verified_review(replacement)["core_collection_binding"]
    # Before capture: index expects the original ZIP but capture sees replacement.
    # After capture: index expects replacement but capture saw the original ZIP.
    # Identical core DTOs cannot substitute for the actual indexed delivery hash.
    if replacement_at == "after_capture":
        coverage["parts"][0]["sha256"] = hashlib.sha256(replacement_bytes).hexdigest()
        coverage_path.write_bytes(canonical_bytes(coverage))
    original_load = module.load_verified_review
    captures = []
    def replacing_load(path):
        captures.append(Path(path))
        if Path(path) == child and replacement_at == "before_capture":
            child.write_bytes(replacement_bytes)
        loaded = original_load(path)
        if Path(path) == child and replacement_at == "after_capture":
            child.write_bytes(replacement_bytes)
        return loaded
    monkeypatch.setattr(module, "load_verified_review", replacing_load)
    with pytest.raises(ReviewPackageValidationError, match="coverage_package_hash_or_path_mismatch"):
        verify_coverage(coverage_path)
    assert captures == [child]
    connection.close()


def test_coverage_uses_single_verified_capture_even_if_path_changes_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import app.review_export as module
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True, max_records=12)
    result = export_review(review, output_path=tmp_path / "week.zip", staging_dir=_stage(tmp_path), multipart=True, max_records=12)
    children = [Path(path) for path in result["parts"]]
    original_load = module.load_verified_review
    captures = []
    def capture_then_replace(path):
        captures.append(Path(path))
        loaded = original_load(path)
        Path(path).write_bytes(b"replacement must never be reopened or merged")
        return loaded
    def prohibited_reopen(*_args, **_kwargs):
        pytest.fail("coverage must use only its verified byte capture")
    monkeypatch.setattr(module, "load_verified_review", capture_then_replace)
    monkeypatch.setattr(module, "file_sha256", prohibited_reopen)
    monkeypatch.setattr(module, "verify_review", prohibited_reopen)
    verified = verify_coverage(Path(result["coverage"]))
    assert verified["valid"] and verified["parts_verified"] == len(children)
    assert captures == children
    connection.close()


@pytest.mark.parametrize("boundary", ["coverage", "subpackage"])
def test_coverage_capture_limits_reject_oversized_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str,
):
    import app.review_export as module
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True, max_records=12)
    result = export_review(review, output_path=tmp_path / "week.zip", staging_dir=_stage(tmp_path), multipart=True, max_records=12)
    if boundary == "coverage":
        monkeypatch.setattr(module, "_MAX_MEMBER_BYTES", 8)
        message = "coverage_size_limit_exceeded"
    else:
        monkeypatch.setattr(module, "_MAX_TOTAL_BYTES", 8)
        message = "package_archive_size_limit_exceeded"
    with pytest.raises(ReviewPackageValidationError, match=message):
        verify_coverage(Path(result["coverage"]))
    connection.close()


def _scoring_sidecars(review, tmp_path: Path):
    from app.prediction_scoring import evaluate_review, freeze_evaluation_set
    stage = _stage(tmp_path)
    original = tmp_path / "original.zip"
    export_review(review, output_path=original, staging_dir=stage)
    loaded = load_verified_review(original)
    source = {**loaded["collections"], "source_binding": loaded["source_binding"],
              "package_binding": {key: loaded[key] for key in ("source_package_sha256", "manifest_sha256")}}
    definition = {"id": "frozen-gap-set", "observation_cutoff_at": FREEZE,
                  "coverage": {"status": "partial", "start": WINDOW["start"], "end": WINDOW["end"]},
                  "rules": {"inclusion": "explicit_fixture_event", "exclusion": "none", "deduplication": "target_event_id", "adjudication_version": "fixture-v1"},
                  "events": [{"actual_event_id": "explicit-missing-truth-event", "target": "BANKED", "scope": "unknown",
                              "association_status": "unresolved", "truth_ref": {"target": "truth_revisions", "id": "missing-truth"},
                              "forecast_ids": []}]}
    frozen = freeze_evaluation_set(source, definition, source["source_binding"])
    assessment = evaluate_review(source, frozen)
    return frozen, assessment, stage, loaded


def test_validated_sidecar_attachment_reproduces_without_zip_hash_cycle(tmp_path: Path):
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE)
    before = copy.deepcopy(review)
    frozen, assessment, stage, original = _scoring_sidecars(review, tmp_path)
    set_path, assessment_path = tmp_path / "set.json", tmp_path / "score.json"
    set_path.write_bytes(canonical_bytes(frozen))
    assessment_path.write_bytes(canonical_bytes(assessment))
    attached = attach_evaluations(review, evaluation_sets=[set_path], assessments=[assessment_path])
    assert review == before
    assert core_collection_binding(attached) == core_collection_binding(review)
    connection.close()  # There is no source connection to reopen or write.
    result = export_review(attached, output_path=tmp_path / "attached.zip", staging_dir=stage)
    loaded = load_verified_review(tmp_path / "attached.zip")
    assert result["verification"]["assessments_reproduced"] == 1
    assert loaded["collections"]["evaluation_sets"] == [frozen]
    assert loaded["collections"]["assessments"] == [assessment]
    assert loaded["source_package_sha256"] != original["source_package_sha256"]
    assert frozen["package_binding"]["source_package_sha256"] == original["source_package_sha256"]
    assert loaded["core_collection_binding"] == original["core_collection_binding"]
    assert all(sum(panel["counts"].values()) == panel["N"] for panel in assessment["panels"])
    assert all(panel["N"] == 1 for panel in assessment["panels"] if panel["target"] == "BANKED")
    assert not any(panel["counts"]["definite_hit"] for panel in assessment["panels"])


@pytest.mark.parametrize("tamper", ["root_field", "nested_field", "source", "score"])
def test_sidecar_contract_rejects_tampering_even_when_rehashed(tmp_path: Path, tamper: str):
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE)
    frozen, assessment, _stage_path, _loaded = _scoring_sidecars(review, tmp_path)
    if tamper == "root_field":
        frozen["extra_delivery_field"] = "not approved"
    elif tamper == "nested_field":
        frozen["events"][0]["extra_claim"] = "not approved"
    elif tamper == "source":
        frozen["source_binding"]["high_water"] += 1
    else:
        assessment["panels"][0]["N"] += 1
    frozen["set_hash"] = sha256_json({key: child for key, child in frozen.items() if key not in {"set_hash", "record_sha256"}})
    frozen["record_sha256"] = record_digest(frozen)
    assessment["assessment_hash"] = sha256_json({key: child for key, child in assessment.items() if key not in {"assessment_hash", "record_sha256", "id"}})
    assessment["id"] = "assessment-" + assessment["assessment_hash"]
    assessment["record_sha256"] = record_digest(assessment)
    with pytest.raises(ReviewPackageValidationError):
        attach_evaluations(review, evaluation_sets=[frozen], assessments=[assessment])
    connection.close()


@pytest.mark.parametrize("invalid", [b'{"id":"one","id":"two"}', b'{"id":NaN}', b'[]'])
def test_external_sidecars_reject_duplicate_keys_nonfinite_and_nonobjects(tmp_path: Path, invalid: bytes):
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE)
    sidecar = tmp_path / "invalid.json"
    sidecar.write_bytes(invalid)
    with pytest.raises(ReviewPackageValidationError):
        attach_evaluations(review, evaluation_sets=[sidecar])
    connection.close()


def test_multipart_scoring_keeps_fixed_set_and_reproduces_only_verified_union(tmp_path: Path):
    connection = _seven_days()
    review = freeze_review(connection, WINDOW, FREEZE, multipart=True)
    frozen, assessment, stage, _loaded = _scoring_sidecars(review, tmp_path)
    attached = attach_evaluations(review, evaluation_sets=[frozen], assessments=[assessment])
    result = export_review(attached, output_path=tmp_path / "scored-week.zip", staging_dir=stage, multipart=True, max_records=12)
    assert result["verification"]["assessments_reproduced"] == 1
    assert len(result["parts"]) > 1
    for path in result["parts"]:
        part = load_verified_review(Path(path))
        assert sum(part["manifest"]["counts"].values()) <= 12
        assert part["collections"]["evaluation_sets"] == [frozen]
        assert part["collections"]["assessments"] == [assessment]
        assert part["verification"]["assessments_reproduced"] == 0
        assert part["verification"]["assessment_recomputation_scope"] == "coverage_union_required"
        assert part["core_binding_scope"] == "subpackage_only"
    union = load_verified_review(Path(result["coverage"]))
    assert union["core_binding_scope"] == "verified_coverage_union"
    assert union["collections"]["assessments"] == [assessment]
    assert union["core_collection_binding"] == core_collection_binding(review)
    assert union["verification"]["assessments_reproduced"] == 1
    connection.close()
