from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

import pytest

from app.review_common import canonical_bytes, sha256_json
import app.review_export as review_export_module
import scripts.export_prediction_review as review_cli
from app.review_export import ReviewExportError, export_review, verify_review
from app.review_privacy import PrivacyContext, clean_text, sanitize_dto
from app.review_reader import ReviewReadError, read_review
from app.intelligence import ledger_processing_output
from app.prediction_ledger import AttemptTracker, PredictionLedger


WINDOW = {
    "start": "2026-10-01T00:00:00Z",
    "end": "2026-10-07T00:00:00Z",
    "series_id": None,
}
FREEZE = "2026-10-07T00:00:00Z"


@pytest.fixture(autouse=True)
def _network_is_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_network(*_args, **_kwargs):
        raise AssertionError("focused review tests must not use network")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)


def _connection(*, ledger: bool = True, artifacts: bool = True, events: bool = False) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    if artifacts:
        connection.execute(
            "CREATE TABLE prediction_artifacts(id TEXT PRIMARY KEY,kind TEXT NOT NULL,content_hash TEXT NOT NULL,"
            "payload_json TEXT NOT NULL,recorded_at TEXT NOT NULL,UNIQUE(kind,content_hash))"
        )
    if ledger:
        connection.execute(
            "CREATE TABLE prediction_ledger(seq INTEGER PRIMARY KEY AUTOINCREMENT,record_id TEXT UNIQUE NOT NULL,"
            "kind TEXT NOT NULL,series_id TEXT,forecast_id TEXT,run_id TEXT,attempt_id TEXT,revision INTEGER,"
            "judgement_id INTEGER,event_id INTEGER,occurred_at TEXT,recorded_at TEXT NOT NULL,idempotency_key TEXT UNIQUE,"
            "payload_json TEXT NOT NULL)"
        )
    if events:
        connection.execute(
            "CREATE TABLE reset_events(id INTEGER PRIMARY KEY,event_type TEXT NOT NULL,special_type TEXT,"
            "occurred_at TEXT,occurred_at_end TEXT,time_basis TEXT,scope TEXT,execution_stage TEXT,"
            "evidence_post_ids TEXT,title TEXT,summary TEXT,provenance TEXT,created_at TEXT,updated_at TEXT)"
        )
    return connection


def _artifact(
    connection: sqlite3.Connection,
    artifact_id: str,
    kind: str,
    payload: dict,
    recorded_at: str = "2026-10-01T00:00:00Z",
) -> dict[str, str]:
    digest = sha256_json(payload)
    connection.execute(
        "INSERT INTO prediction_artifacts(id,kind,content_hash,payload_json,recorded_at) VALUES(?,?,?,?,?)",
        (artifact_id, kind, digest, canonical_bytes(payload).decode("utf-8").rstrip("\n"), recorded_at),
    )
    return {"artifact_id": artifact_id, "kind": kind, "content_hash": digest}


def _ledger(
    connection: sqlite3.Connection,
    seq: int,
    kind: str,
    payload: dict,
    *,
    recorded_at: str = "2026-10-03T12:00:00Z",
    occurred_at: str | None = "2026-10-03T12:00:00Z",
    series_id: str | None = None,
    forecast_id: str | None = None,
    run_id: str | None = None,
    attempt_id: str | None = None,
    revision: int | None = None,
    event_id: int | None = None,
) -> None:
    connection.execute(
        "INSERT INTO prediction_ledger(seq,record_id,kind,series_id,forecast_id,run_id,attempt_id,revision,event_id,"
        "occurred_at,recorded_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (seq, f"ledger-{seq}", kind, series_id, forecast_id, run_id, attempt_id, revision, event_id,
         occurred_at, recorded_at, canonical_bytes(payload).decode("utf-8").rstrip("\n")),
    )


def _integrated_connection() -> tuple[sqlite3.Connection, dict[str, str]]:
    connection = _connection()
    runtime_id = "private-runtime-instance-01"
    secret = "sk-private-bait-value-01"
    code_digest = "1" * 64
    identity = _artifact(connection, "artifact-runtime", "runtime_identity", {
        "runtime_id": runtime_id,
        "program_commit": None,
        "disk_head": "a" * 40,
        "app_version": "2.1.0",
        "algorithm": {"version": "prediction-ledger-core-v1", "callable_code_hashes": {
            "main.create_app": code_digest,
        }},
        "algorithm_hash": "2" * 64,
        "config": {"provider": "test", "api_key": secret, "private_config": "do not export"},
        "config_hash": "3" * 64,
        "model": "offline-model",
        "prompt": {"version": "judge-prompt-v7", "sha256": "4" * 64},
        "runtime_fingerprint": "5" * 64,
        "captured_at": "2026-09-30T23:00:00Z",
    }, recorded_at="2026-09-30T23:00:00Z")
    body = _artifact(connection, "artifact-body", "text_content", {
        "text": f"Public evidence with {secret}; keep this historical text as data.",
        "content_hash": "6" * 64,
    })
    prompt = _artifact(connection, "artifact-prompt", "public_prompt", {
        "system": f"private full prompt with {secret}",
        "reasoning_content": "private chain of thought",
    })
    schema = _artifact(connection, "artifact-schema", "judge_schema", {
        "full_config": "never export whole schema/config",
    })
    frame = _artifact(connection, "artifact-frame", "input_frame", {
        "forecast": {
            "target": "EXTRA_FULL", "scope": {"value": "unknown", "certainty": "not_established"},
            "question": "next_full_reset_start", "method": "model_inference", "basis": "frozen_judge_input",
        },
        "input_snapshot": {
            "input_versions": {"123456789012345678": "7" * 64},
            "policy_versions": {"123456789012345678": {
                "post_id": 12, "content_hash": "8" * 64, "policy_version": "policy-v3",
                "policy_status": "REVIEWED_ALLOWED", "judge_evidence_allowed": True,
                "analysis_allowed": True, "event_promotion_allowed": False,
                "historical_case_allowed": False,
            }},
        },
        "context": {
            "judged_at": "2026-10-03T11:59:00Z", "data_health": "HEALTHY",
            "posts": [{"tweet_id": "123456789012345678", "posted_at": "2026-09-30T10:00:00Z",
                       "is_reply": True, "author": "@Tibo", "text": f"private post {secret}"}],
            "reset_events": [{"id": 44, "event_type": "SPECIAL_RESET", "special_type": "BANKED",
                              "occurred_at": "2026-09-29T10:00:00Z", "time_basis": "post_time_proxy",
                              "execution_stage": "announced", "scope": "unknown", "summary": "structured event"}],
            "historical_cases": [{"case_id": "case-7", "outcome_type": "FULL_RESET",
                                  "verification_status": "verified", "original_text": "omit this body"}],
            "previous_judgement": {"action_level": "YELLOW", "reasoning_content": "omit CoT"},
            "private_debug": f"{secret} must not export",
        },
        "evidence_sources": [{
            "post_id": 12, "tweet_id": "123456789012345678", "author": "@Tibo", "role": "target_post",
            "relation_to_target": "prompt_post_source", "source_version": "9" * 64,
            "snapshot_status": "frozen",
            "original_text": {"artifact_ref": body, "source_ref": {
                "post_id": 12, "tweet_id": "123456789012345678", "author": "@Tibo",
                "role": "target_post", "relation_to_target": "prompt_post_source",
            }},
        }],
        "policy_versions": {"123456789012345678": {
            "post_id": 12, "content_hash": "8" * 64, "policy_version": "policy-v3",
            "policy_status": "REVIEWED_ALLOWED", "judge_evidence_allowed": True,
            "analysis_allowed": True, "event_promotion_allowed": False,
            "historical_case_allowed": False,
        }},
        "public_prompt_artifact_ref": prompt,
        "judge_schema_artifact_ref": schema,
    })
    snapshot = _artifact(connection, "artifact-snapshot", "input_snapshot", {
        "semantic_input_hash": "b" * 64,
        "input_snapshot": {"input_versions": {"123456789012345678": "7" * 64}},
        "input_frame_artifact_ref": frame,
        "evidence_artifact_refs": [body],
        "public_prompt_artifact_ref": prompt,
        "judge_schema_artifact_ref": schema,
    })
    request = _artifact(connection, "artifact-request", "request_descriptor", {
        "stage": "radar_judge", "judgement_as_of": "2026-10-03T11:59:00Z",
        "input_cutoff_at": "2026-10-03T11:58:00Z", "input_snapshot_hash": "a" * 64,
        "forecast_semantic_hash": "b" * 64, "request_hash": "c" * 64,
        "input_frame_artifact_ref": frame, "prompt_artifact_ref": prompt, "schema_artifact_ref": schema,
        "model": "offline-model", "temperature": 0, "response_format": {"type": "json_object", "secret": secret},
        "message_count": 2, "messages": [secret], "request_body": secret,
    })
    _ledger(connection, 1, "runtime_identity", {"runtime_id": runtime_id, "runtime_artifact_ref": identity},
            recorded_at="2026-09-30T23:00:00Z", occurred_at="2026-09-30T23:00:00Z")
    _ledger(connection, 2, "forecast_version", {
        "target": "EXTRA_FULL", "scope": {"value": "unknown", "certainty": "not_established"},
        "record_kind": "online", "method": "model_inference", "forecast": {"question": "next_full_reset_start"},
    }, series_id="series-extra-full", forecast_id="forecast-1", revision=1)
    _ledger(connection, 3, "run_started", {
        "is_synthetic": True, "runtime": {"runtime_id": runtime_id},
        "forecast": {"target": "EXTRA_FULL", "scope": {"value": "unknown", "certainty": "not_established"}},
        "input_artifact_refs": [snapshot, frame, body, prompt, schema],
        "input_snapshot_artifact_ref": snapshot, "input_frame_artifact_ref": frame,
    }, series_id="series-extra-full", forecast_id="forecast-1", run_id="run-1")
    _ledger(connection, 4, "attempt_started", {
        "request_artifact_ref": request, "stage": "radar_judge", "attempt_started_at": "2026-10-03T12:00:00Z",
    }, series_id="series-extra-full", forecast_id="forecast-1", run_id="run-1", attempt_id="attempt-1")
    connection.commit()
    return connection, {"secret": secret, "runtime_id": runtime_id, "body_hash": body["content_hash"]}


def _all_public_json(review: dict) -> str:
    return json.dumps(review, ensure_ascii=False, sort_keys=True)


def test_privacy_keeps_approved_fingerprints_but_aliases_private_hashes_and_cleans_urls() -> None:
    private_hash = "a" * 64
    public_hash = "b" * 64
    context = PrivacyContext.from_sources([{"input_versions": {"123": private_hash}}])
    safe = sanitize_dto({
        "disk_head": "c" * 40,
        "program_commit": None,
        "config_fingerprint": public_hash,
        "loaded_code_fingerprints": {"main.create_app": "d" * 64, "unexpected": "e" * 64},
        "input_versions": {"123": private_hash},
    }, {"disk_head", "program_commit", "config_fingerprint", "loaded_code_fingerprints", "input_versions"}, context)
    assert safe["disk_head"] == "c" * 40
    assert safe["program_commit"] is None
    assert safe["config_fingerprint"] == public_hash
    assert safe["loaded_code_fingerprints"] == {"main.create_app": "d" * 64}
    assert safe["input_versions"]["123"] != private_hash

    urls = (
        "https://user:pass@example.com/private/token-secret-value?q=secret#fragment",
        "https://example.com/private/path?api_key=secret-value#secret",
        "https://x.com/Tibo/status/123?token=secret-value#fragment",
    )
    cleaned = [clean_text(value, context)[0] for value in urls]
    joined = " ".join(cleaned)
    assert "user:pass" not in joined and "secret-value" not in joined and "fragment" not in joined
    assert "https://x.com/Tibo/status/123" in joined

    timed = sanitize_dto({
        "structured_output": {
            "estimated_start_expression": "2026-10-08",
            "estimated_start_time_metadata": {
                "precision": "day", "source_timezone": None, "timezone_status": "not_stated",
            },
            "reasoning_content": "omit private reasoning",
        },
    }, {"structured_output"}, context)
    assert timed["structured_output"]["estimated_start_expression"] == "2026-10-08"
    assert timed["structured_output"]["estimated_start_time_metadata"]["precision"] == "day"
    assert "reasoning_content" not in json.dumps(timed)


def test_cli_reuses_timezone_fallback_and_rejects_naive_generated_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_zone(_name: str):
        raise ZoneInfoNotFoundError("Asia/Shanghai")

    monkeypatch.setattr(review_export_module, "ZoneInfo", missing_zone)
    assert review_cli.parse_user_time("2026-10-07").isoformat() == "2026-10-06T16:00:00+00:00"
    assert review_cli.parse_user_time("2026-10-07T00:00:00").isoformat() == "2026-10-06T16:00:00+00:00"

    connection, _ = _integrated_connection()
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(ReviewExportError, match="generated_at_must_be_timezone_aware"):
        export_review(connection, WINDOW, FREEZE, tmp_path / "naive.zip", staging,
                      generated_at="2026-10-07T01:00:00")
    assert not (tmp_path / "naive.zip").exists()
    connection.close()


def test_cli_help_prepare_preview_export_verify_on_readonly_fixture(tmp_path: Path) -> None:
    connection, _ = _integrated_connection()
    database_path = tmp_path / "cli-fixture.sqlite"
    target = sqlite3.connect(database_path)
    connection.backup(target)
    target.close()
    connection.close()

    repository_root = Path(__file__).resolve().parents[3]
    script = repository_root / "scripts" / "export_prediction_review.py"
    staging = tmp_path / "explicit-staging"
    staging.mkdir()
    package = tmp_path / "cli-review.zip"
    selection = [
        "--database", str(database_path),
        "--from", "2026-10-01",
        "--to", "2026-10-07",
        "--freeze-at", "2026-10-07",
    ]

    help_result = subprocess.run(
        [sys.executable, str(script), "--help"], cwd=repository_root,
        capture_output=True, text=True, timeout=30,
    )
    assert help_result.returncode == 0 and all(name in help_result.stdout for name in ("prepare", "preview", "export", "verify"))
    for command in ("prepare", "export"):
        command_help = subprocess.run(
            [sys.executable, str(script), command, "--help"], cwd=repository_root,
            capture_output=True, text=True, timeout=30,
        )
        assert command_help.returncode == 0 and "--staging-dir" in command_help.stdout

    def invoke(*arguments: str) -> dict:
        result = subprocess.run(
            [sys.executable, str(script), *arguments], cwd=repository_root,
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"CLI failed ({result.returncode}): {result.stdout}\n{result.stderr}"
        return json.loads(result.stdout)

    prepared = invoke("prepare", *selection, "--out", str(package), "--staging-dir", str(staging))
    assert prepared["publish_preflight"] == "ready_same_volume_no_output_created"
    assert not package.exists()
    preview = invoke("preview", *selection)
    assert preview["ready"] is True
    exported = invoke("export", *selection, "--out", str(package), "--staging-dir", str(staging))
    assert exported["verification"]["valid"]
    verified = invoke("verify", "--package", str(package))
    assert verified["valid"]


def test_export_publish_does_not_clobber_target_created_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, _ = _integrated_connection()
    staging = tmp_path / "staging"
    staging.mkdir()
    package = tmp_path / "concurrently-created.zip"
    winner = b"another publisher won the race"
    real_link = review_export_module.os.link

    def create_racing_target(source, destination, *args, **kwargs):
        Path(destination).write_bytes(winner)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(review_export_module.os, "link", create_racing_target)
    with pytest.raises(FileExistsError, match="output_path_already_exists"):
        export_review(connection, WINDOW, FREEZE, package, staging,
                      generated_at="2026-10-07T01:00:00Z")

    assert package.read_bytes() == winner
    assert list(staging.iterdir()) == []
    connection.close()


def test_export_publish_oserror_fails_closed_and_only_cleans_own_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    connection, _ = _integrated_connection()
    database_path = tmp_path / "publish-failure.sqlite"
    target = sqlite3.connect(database_path)
    connection.backup(target)
    target.close()
    connection.close()

    staging = tmp_path / "staging"
    staging.mkdir()
    caller_file = staging / "caller-owned.txt"
    caller_file.write_text("keep", encoding="utf-8")
    package = tmp_path / "must-not-publish.zip"

    def reject_hard_link(source, destination, *_args, **_kwargs):
        raise OSError(13, "simulated hard-link permission failure", str(source), str(destination))

    monkeypatch.setattr(review_export_module.os, "link", reject_hard_link)
    exit_code = review_cli.main([
        "export", "--database", str(database_path),
        "--from", "2026-10-01T00:00:00Z", "--to", "2026-10-07T00:00:00Z",
        "--freeze-at", "2026-10-07T00:00:00Z", "--out", str(package),
        "--staging-dir", str(staging),
    ])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "atomic_no_clobber_publish_failed" in captured.out
    assert "simulated hard-link permission failure" not in captured.out + captured.err
    assert str(package) not in captured.out + captured.err
    assert str(staging) not in captured.out + captured.err
    assert not package.exists()
    assert caller_file.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in staging.iterdir()) == [caller_file.name]


def test_reader_preserves_observation_clock_and_safe_rejection_delta() -> None:
    connection = _connection()
    old_hash, new_hash = "c" * 64, "d" * 64
    _ledger(connection, 1, "run_started", {"is_synthetic": True}, run_id="run-reject", series_id="series-reject", forecast_id="forecast-reject")
    _ledger(connection, 2, "attempt_started", {
        "stage": "radar_judge", "declared_model": "offline-declared-model",
        "attempt_started_at": "2026-10-03T12:00:00Z",
    }, run_id="run-reject", attempt_id="attempt-reject", series_id="series-reject", forecast_id="forecast-reject")
    _ledger(connection, 3, "attempt_event", {
        "event_type": "late_input_rejected", "failure_terminal": True,
        "reason_code": "INPUT_SNAPSHOT_CHANGED", "attempt_finished_at": "2026-10-03T12:01:00Z",
        "output_available_at": None, "publication_status": "rejected",
        "declared_model": "offline-declared-model", "reported_model": "offline-response-model",
        "reported_model_source": "response.model", "reported_model_missing_reason": None,
        "structured_output": {
            "action_level": "UNKNOWN", "reason_summary": "structured result retained",
            "reasoning_content": "private chain of thought must not export",
        },
        "input_version_delta": [{
            "class": "input_version", "entity": "123456789012345678",
            "old_hash": old_hash, "new_hash": new_hash,
        }],
    }, run_id="run-reject", attempt_id="attempt-reject", series_id="series-reject", forecast_id="forecast-reject")
    _ledger(connection, 4, "output_committed", {
        "output_id": "legacy-output-1", "structured_output": {"action_level": "GREEN"},
        "validation": {"status": "accepted"}, "accepted_attempt_id": "attempt-reject",
    }, run_id="run-reject", attempt_id="attempt-reject", series_id="series-reject", forecast_id="forecast-reject")
    _ledger(connection, 5, "output_observed", {
        "output_id": "legacy-output-1", "observed_at": "2026-10-03T12:02:00Z",
        "source": "formal_getter", "clock_anomaly": "wall_clock_reversed",
        "time_limitation": "timestamps_retained_without_ordering",
    }, run_id="run-reject", attempt_id="attempt-reject", series_id="series-reject", forecast_id="forecast-reject")
    connection.commit()

    review = read_review(connection, WINDOW, FREEZE)
    attempt = next(item for item in review["attempts"] if item.get("attempt_id") == "attempt-reject")
    rejected = next(event for event in attempt["events"] if event.get("event_type") == "late_input_rejected")
    assert rejected["output_available_at"] is None and rejected["publication_status"] == "rejected"
    assert rejected["declared_model"] == "offline-declared-model"
    assert rejected["reported_model"] == "offline-response-model"
    assert rejected["structured_output"]["action_level"] == "UNKNOWN"
    assert "reasoning_content" not in json.dumps(rejected)
    delta = rejected["input_version_delta"][0]
    assert delta["old_hash"] != old_hash and delta["new_hash"] != new_hash
    assert old_hash not in _all_public_json(review) and new_hash not in _all_public_json(review)
    output = next(item for item in review["outputs"] if item.get("output_id") == "legacy-output-1")
    observation = output["availability_observations"][0]
    assert observation["clock_anomaly"] == "wall_clock_reversed"
    assert observation["time_limitation"] == "timestamps_retained_without_ordering"
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    connection.close()


def test_reader_closes_runtime_and_projects_only_safe_frame_and_request_fields() -> None:
    connection, bait = _integrated_connection()
    before = connection.total_changes
    review = read_review(connection, WINDOW, FREEZE)

    runtime = next(item for item in review["runtime_identities"] if item.get("identity_status") == "captured")
    assert runtime["is_synthetic"] is None
    assert runtime["program_commit"] is None
    assert runtime["disk_head"] == "a" * 40
    assert runtime["loaded_code_fingerprints"]["main.create_app"] == "1" * 64
    assert runtime["config_fingerprint"] == "3" * 64
    assert "config" not in runtime and bait["runtime_id"] not in _all_public_json(review)
    assert any(item.get("dependency_reason") == "runtime_identity_for_run" for item in review["runtime_identities"])

    frame = next(item for item in review["input_snapshots"] if item.get("source_kind") == "ledger_input_frame")
    safe_frame = frame["input_frame"]
    assert safe_frame["forecast"]["question"] == "next_full_reset_start"
    assert safe_frame["context"]["reset_events"][0]["special_type"] == "BANKED"
    assert safe_frame["policy_versions"]["123456789012345678"]["policy_status"] == "REVIEWED_ALLOWED"
    assert "text" not in safe_frame["context"]["posts"][0]
    assert "private_debug" not in safe_frame["context"]
    request = next(item for item in review["input_snapshots"] if item.get("source_kind") == "ledger_request_descriptor")
    safe_request = request["request_descriptor"]
    assert safe_request["model"] == "offline-model" and safe_request["temperature"] == 0
    assert safe_request["response_format"] == {"type": "json_object"}
    assert "request_body" not in safe_request and "messages" not in safe_request
    assert request.get("references", {}).get("artifacts")
    assert any(
        item.get("text") and bait["secret"] not in item["text"] and item.get("redacted")
        for item in review["public_evidence"]
    )
    assert bait["secret"] not in _all_public_json(review)
    assert "reasoning_content" not in _all_public_json(review)
    assert connection.total_changes == before
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    connection.close()


@pytest.mark.parametrize("fault", ["payload_hash", "ref_hash", "kind"])
def test_reader_rejects_corrupt_or_conflicting_frozen_artifacts(fault: str) -> None:
    connection = _connection()
    payload = {"forecast": {"target": "EXTRA_FULL"}}
    ref = _artifact(connection, "artifact-check", "input_frame", payload)
    if fault == "payload_hash":
        connection.execute(
            "UPDATE prediction_artifacts SET payload_json=? WHERE id=?",
            ('{"forecast":{"target":"DIFFERENT"}}', "artifact-check"),
        )
    elif fault == "kind":
        connection.execute("UPDATE prediction_artifacts SET kind='request_descriptor' WHERE id='artifact-check'")
    elif fault == "ref_hash":
        ref["content_hash"] = "f" * 64
    _ledger(connection, 1, "run_started", {"input_frame_artifact_ref": ref, "runtime": {"runtime_id": "r"}}, run_id="run")
    connection.commit()

    with pytest.raises(ReviewReadError, match="artifact"):
        read_review(connection, WINDOW, FREEZE)
    connection.close()


def test_artifact_recorded_after_freeze_is_an_explicit_missing_reference() -> None:
    connection = _connection()
    ref = _artifact(connection, "artifact-late", "input_frame", {"forecast": {"target": "EXTRA_FULL"}},
                    recorded_at="2026-10-08T00:00:00Z")
    _ledger(connection, 1, "run_started", {"input_frame_artifact_ref": ref, "runtime": {"runtime_id": "late-runtime"}})
    connection.commit()

    review = read_review(connection, WINDOW, FREEZE)
    placeholders = [item for item in review["input_snapshots"] if item.get("placeholder")]
    assert len(placeholders) == 1
    assert placeholders[0]["omission_reason"] == "referenced_artifact_not_available_as_of_freeze"
    assert any(gap["code"] == "artifact_not_available_as_of_freeze" for gap in review["metadata"]["gaps"])
    connection.close()


def test_legacy_normal_baseline_uses_frozen_full_anchor_range_and_never_rolls_forward() -> None:
    connection = _connection(ledger=False, artifacts=False, events=True)
    events = [
        (1, "FULL_RESET", None, "2026-08-01T00:00:00Z", None, "post_time_proxy", "unknown", "completed"),
        (2, "FULL_RESET", None, "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", "post_time_proxy", "unknown", "completed"),
        (3, "SPECIAL_RESET", "BANKED", "2026-09-20T00:00:00Z", None, "explicit_text", "unknown", "completed"),
        (4, "FULL_RESET", None, "2026-10-08T00:00:00Z", None, "explicit_text", "unknown", "completed"),
    ]
    for event_id, event_type, special, start, end, basis, scope, stage in events:
        created = "2026-10-06T10:00:00Z" if event_id == 4 else "2026-09-30T10:00:00Z"
        connection.execute(
            "INSERT INTO reset_events(id,event_type,special_type,occurred_at,occurred_at_end,time_basis,scope,"
            "execution_stage,evidence_post_ids,title,summary,provenance,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, event_type, special, start, end, basis, scope, stage, "[]", "fixture", "synthetic event",
             "{}", created, created),
        )
    connection.commit()
    before = connection.total_changes

    review = read_review(connection, {
        "start": "2026-09-20T00:00:00Z", "end": "2026-10-01T00:00:00Z", "series_id": None,
    }, "2026-10-01T00:00:00Z")
    baseline = next(item for item in review["forecasts"] if item.get("target") == "NORMAL_WEEKLY")
    assert baseline["record_kind"] == "baseline" and baseline["method"] is None
    assert baseline["basis"] == "user_full_plus_7d"
    assert baseline["predicted_start"] == "2026-09-08T00:00:00Z"
    assert baseline["predicted_end"] == "2026-09-09T00:00:00Z"
    assert baseline["precision"] == "range" and baseline["time_basis"] == "post_time_proxy"
    assert baseline["status"] == "expired" and baseline["output_available_at"] is None
    assert baseline["version_history_complete"] is False
    assert baseline["is_synthetic"] is None
    assert baseline["references"]["truth"]["status"] == "included"
    assert any(row.get("event_id") == "2" and row.get("is_dependency") for row in review["truth_revisions"])
    assert review["metadata"]["capabilities"]["normal_baseline"] == "COMPATIBILITY_VIEW_ONLY"
    assert review["metadata"]["capabilities"]["normal_baseline_history"] == "NOT_BACKFILLED"
    assert connection.total_changes == before
    connection.close()


def test_real_ledger_producers_export_processing_output_and_truth_closure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _connection(events=True)
    connection.execute(
        "CREATE TABLE tibo_posts(id INTEGER PRIMARY KEY,tweet_id TEXT,original_text TEXT,text TEXT,text_hash TEXT,"
        "author_handle TEXT,reply_to_tweet_id TEXT)"
    )
    connection.execute(
        "CREATE TABLE post_content_policies(post_id INTEGER,content_hash TEXT,judge_evidence_allowed INTEGER,"
        "event_promotion_allowed INTEGER,policy_version TEXT)"
    )
    connection.execute("CREATE TABLE reply_context_nodes(tweet_id TEXT,body_json TEXT)")
    tweet_id = "123456789012345678"
    post_hash = "d" * 64
    bait = "sk-production-shaped-test-bait-01"
    body = f"Public historical source body containing {bait}."
    connection.execute(
        "INSERT INTO reset_events(id,event_type,special_type,occurred_at,occurred_at_end,time_basis,scope,"
        "execution_stage,evidence_post_ids,title,summary,provenance,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (42, "SPECIAL_RESET", "BANKED", "2026-09-01T10:00:00Z", None, "explicit_text", "unknown",
         "completed", json.dumps([tweet_id]), "fixture event", "synthetic test event", "{}",
         "2026-09-01T10:00:00Z", "2026-09-01T10:00:00Z"),
    )
    connection.execute(
        "INSERT INTO tibo_posts(id,tweet_id,original_text,text,text_hash,author_handle,reply_to_tweet_id) "
        "VALUES(?,?,?,?,?,?,?)",
        (7, tweet_id, body, body, post_hash, "@Tibo", None),
    )
    connection.execute(
        "INSERT INTO post_content_policies(post_id,content_hash,judge_evidence_allowed,event_promotion_allowed,policy_version) "
        "VALUES(?,?,?,?,?)",
        (7, post_hash, 1, 1, "fixture-policy-v1"),
    )
    connection.execute(
        "INSERT INTO reply_context_nodes(tweet_id,body_json) VALUES(?,?)",
        (tweet_id, json.dumps({"tweet_id": tweet_id, "author": "@Tibo"})),
    )
    connection.commit()

    class SharedDatabase:
        def connect(self):
            return connection

        def get_post_by_tweet_id(self, value):
            row = connection.execute(
                "SELECT id,tweet_id,text_hash FROM tibo_posts WHERE tweet_id=?", (value,),
            ).fetchone()
            return dict(row) if row else None

        def content_policy(self, post_id):
            row = connection.execute(
                "SELECT policy_version,event_promotion_allowed FROM post_content_policies WHERE post_id=?",
                (post_id,),
            ).fetchone()
            return dict(row) if row else None

    import app.prediction_ledger as prediction_ledger_module

    clock = {"now": "2026-09-30T12:00:00Z"}
    monkeypatch.setattr(prediction_ledger_module, "utc_text", lambda value=None: value if value is not None else clock["now"])
    ledger = PredictionLedger(SharedDatabase(), owner={"runtime_id": "private-test-runtime"})
    ledger.record_runtime_identity(
        {"runtime_id": "private-test-runtime", "app_version": "focused-producer-test"},
        is_synthetic=True,
    )
    with connection:
        ledger.append_reset_event_snapshot(connection, 42, {
            "event_key": "fixture-event-key", "event_type": "SPECIAL_RESET", "special_type": "BANKED",
            "occurred_at": "2026-09-01T10:00:00Z", "occurred_at_end": None,
            "time_basis": "explicit_text", "scope": "unknown", "execution_stage": "completed",
            "source_post_id": 7, "title": "fixture event", "summary": "synthetic test event",
            "provenance": {}, "evidence_post_ids": [tweet_id],
            "created_at": "2026-09-01T10:00:00Z", "updated_at": "2026-09-01T10:00:00Z",
        }, reason="focused producer integration fixture", is_synthetic=True)
    ledger.append_truth(
        42, 1,
        {"actual_event_type": "SPECIAL_RESET", "special_type": "BANKED", "actual_start": "2026-09-01T10:00:00Z",
         "truth_status": "fixture_adjudicated"},
        [], "second frozen truth revision", is_synthetic=True,
    )

    # The selected processing run carries an explicit event reference in the
    # frozen input; its older truth chain must be pulled as dependency closure.
    clock["now"] = "2026-10-06T12:00:00Z"
    run = ledger.begin_processing_run(
        {"input": {"event_id": 42, "tweet_id": tweet_id, "text": body},
         "processing_identity": {"algorithm": "fixture-v1"}},
        "post_analysis", "private-test-runtime", "focused_fixture", is_synthetic=True,
    )
    tracker = AttemptTracker(
        ledger, run.run_id, {"stage": "post_analysis", "model": "offline-test-model"},
        {"runtime_id": "private-test-runtime"}, is_synthetic=True,
    )
    attempt = tracker.begin_attempt()
    response_stamp = "2026-10-06T11:59:00Z"
    tracker.append_event(attempt.attempt_id, "response_received", received_at=response_stamp, http={"status_code": 200})
    tracker.append_event(
        attempt.attempt_id, "response_model_reported", received_at=response_stamp,
        reported_model="offline-provider-model", reported_model_source="deepseek_api_response.model",
        reported_model_missing_reason=None,
    )
    tracker.append_event(
        attempt.attempt_id, "response_model_reported", received_at=response_stamp,
        reported_model=None, reported_model_source="deepseek_api_response.model",
        reported_model_missing_reason="model_field_missing",
    )
    tracker.append_event(
        attempt.attempt_id, "usage_reported",
        usage={"prompt_tokens": 12, "completion_tokens": 4, "private_provider_payload": "do not export"},
        usage_source="deepseek_api_response.usage",
    )
    generated_output = ledger_processing_output("post_analysis", {
        "tweet_id": tweet_id, "category": "full_reset", "event_type": "FULL_RESET",
        "summary": f"Validated output {bait}", "evidence_quote": "Public quote",
        "reasoning_content": f"private chain of thought {bait}",
        "effects": [{"event_type": "FULL_RESET", "summary": "structured producer effect"}],
    })
    tracker.record_processing_output("post_analysis", generated_output)
    second_attempt = tracker.begin_attempt()
    tracker.record_processing_output("post_analysis", generated_output)
    ledger.record_cache_reused(
        stage="post_analysis", input_hash=run.input_hash, output=generated_output,
        runtime_id="private-test-runtime", processing_identity={"algorithm": "fixture-v1"},
        input_material={"event_id": 42, "tweet_id": tweet_id, "text": body},
    )
    ledger.append_run_event(
        run.run_id, "cache_reused", operation="post_translation", source_status="UNKNOWN",
        source_run_id=None, source_attempt_id=None,
        reason_summary="Legacy cache lineage is unknown in this focused fixture.",
    )
    before_changes = connection.total_changes

    staging = tmp_path / "staging"
    staging.mkdir()
    package = tmp_path / "producer-output-and-truth.zip"
    result = export_review(
        connection, WINDOW, FREEZE, package, staging,
        generated_at="2026-10-07T01:00:00Z",
    )
    verified = verify_review(package)
    assert verified["valid"]
    assert result["manifest"]["synthetic_provenance"]["status"] == "SYNTHETIC"
    assert result["manifest"]["counts_in_window"].get("truth_revision", 0) == 0
    assert result["manifest"]["dependency_counts"]["truth_revision"] == 2
    with zipfile.ZipFile(package) as archive:
        outputs = [json.loads(line) for line in archive.read("outputs.jsonl").decode("utf-8").splitlines()]
        attempts = [json.loads(line) for line in archive.read("attempts.jsonl").decode("utf-8").splitlines()]
        truths = [json.loads(line) for line in archive.read("truth-revisions.jsonl").decode("utf-8").splitlines()]
        evidence = [json.loads(line) for line in archive.read("public-evidence.jsonl").decode("utf-8").splitlines()]
        package_bytes = b" ".join(archive.read(name) for name in archive.namelist())

    processing = [item for item in outputs if item.get("output_kind") == "processing_output"]
    assert len(processing) == 2
    assert len({item["id"] for item in processing}) == 2
    assert {item["attempt_id"] for item in processing} == {attempt.attempt_id, second_attempt.attempt_id}
    assert all(item["operation"] == "post_analysis" for item in processing)
    assert all(item["processing_output"]["output"]["summary"].find("[redacted-secret]") >= 0 for item in processing)
    assert all(item.get("evidence_refs") for item in processing)
    assert all("reasoning_content" not in json.dumps(item) for item in outputs)
    usage_events = [event for attempt_item in attempts for event in attempt_item.get("events", []) if event.get("event_type") == "usage_reported"]
    assert usage_events[0]["usage"] == {"completion_tokens": 4, "prompt_tokens": 12}
    response_events = [event for item in attempts for event in item.get("events", []) if event.get("event_type") == "response_received"]
    assert response_events[0]["response_received_at"] == response_stamp
    assert response_events[0]["clock_anomaly"] == "wall_clock_reversed"
    assert response_events[0]["time_limitation"] == "timestamps_retained_without_ordering"
    model_events = [event for item in attempts for event in item.get("events", []) if event.get("event_type") == "response_model_reported"]
    assert any(event.get("reported_model") == "offline-provider-model" for event in model_events)
    assert any(event.get("reported_model_missing_reason") == "model_field_missing" for event in model_events)
    cache_events = [event for item in attempts for event in item.get("events", []) if event.get("event_type") == "cache_reused"]
    assert cache_events and cache_events[0]["source_status"] == "KNOWN"
    assert cache_events[0]["source_attempt_ref"]["status"] == "included"
    assert cache_events[0]["source_attempt_ref"]["id"] == second_attempt.attempt_id
    assert any(event.get("source_status") == "UNKNOWN" and event.get("source_attempt_ref") is None
               for item in attempts for event in item.get("events", []))

    event_truths = [item for item in truths if str(item.get("event_id")) == "42"]
    assert len(event_truths) == 2
    assert all(item.get("source_mode") != "legacy_reset_events" for item in event_truths)
    assert all(item.get("is_dependency") is True for item in event_truths)
    assert event_truths[0]["source_snapshot"]["special_type"] == "BANKED"
    assert all(item.get("is_synthetic") is True for item in event_truths)
    assert any(ref.get("role") == "event_evidence_post" and ref.get("status") == "included"
               for ref in event_truths[0].get("evidence_refs", []))
    body_rows = [item for item in evidence if item.get("text")]
    assert body_rows and all(bait not in item["text"] for item in body_rows)
    evidence_metadata = [item for item in evidence if item.get("tweet_id") == tweet_id and item.get("body_ref")]
    assert evidence_metadata and evidence_metadata[0]["body_ref"]["status"] == "included"
    with zipfile.ZipFile(package) as archive:
        snapshots = [json.loads(line) for line in archive.read("input-snapshots.jsonl").decode("utf-8").splitlines()]
        runtimes = [json.loads(line) for line in archive.read("runtime-identities.jsonl").decode("utf-8").splitlines()]
    assert all(item.get("is_synthetic") is True for item in snapshots if not item.get("placeholder"))
    assert all(item.get("is_synthetic") is True for item in runtimes if not item.get("placeholder"))
    assert all(item.get("is_synthetic") is True for item in evidence if not item.get("placeholder"))
    assert bait.encode() not in package_bytes
    assert b"private_provider_payload" not in package_bytes
    assert connection.total_changes == before_changes
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1

    # A current restriction on any frozen source in the run (including a
    # parent/ancestor) suppresses derived output text while preserving facts and refs.
    connection.execute("PRAGMA query_only=OFF")
    connection.execute(
        "UPDATE post_content_policies SET event_promotion_allowed=0 WHERE post_id=? AND content_hash=?",
        (7, post_hash),
    )
    connection.commit()
    restricted_review = read_review(connection, WINDOW, FREEZE)
    restricted_outputs = [item for item in restricted_review["outputs"] if item.get("output_kind") == "processing_output"]
    assert len(restricted_outputs) == 2
    assert all(item["source_content_status"] == "restricted_by_current_policy" for item in restricted_outputs)
    assert all(item["processing_output"]["output"]["category"] == "full_reset" for item in restricted_outputs)
    assert all("summary" not in item["processing_output"]["output"] for item in restricted_outputs)
    assert all(item.get("evidence_refs") for item in restricted_outputs)
    assert bait not in _all_public_json(restricted_review)
    connection.close()


@pytest.mark.parametrize(
    ("run_marker", "truth_marker", "expected"),
    [(True, True, True), (False, False, False), (True, False, None), (True, None, None), (None, None, None)],
)
def test_reader_provenance_uses_ref_closure_consensus(
    run_marker: bool | None, truth_marker: bool | None, expected: bool | None,
) -> None:
    connection = _connection()
    tweet_id = "333333333333333333"
    body = _artifact(connection, "provenance-body", "text_content", {"text": "public source text"})
    frame = _artifact(connection, "provenance-frame", "input_frame", {
        "input": {"posts": [{
            "tweet_id": tweet_id,
            "text": {"artifact_ref": body, "source_ref": {
                "post_id": 33, "tweet_id": tweet_id, "author": "@Tibo", "role": "target_post",
            }},
        }]},
    })
    snapshot = _artifact(connection, "provenance-snapshot", "input_snapshot", {
        "input_frame_artifact_ref": frame,
    })
    request = _artifact(connection, "provenance-request", "request_descriptor", {
        "stage": "radar_judge", "model": "offline-focused-model",
    })
    truth_evidence = _artifact(connection, "provenance-truth-evidence", "truth_evidence", {
        "tweet_id": tweet_id, "role": "event_evidence_post", "body_artifact_ref": body,
    })
    run_payload = {"input_artifact_refs": [snapshot, frame], "input_frame_artifact_ref": frame}
    if run_marker is not None:
        run_payload["is_synthetic"] = run_marker
    _ledger(connection, 1, "run_started", run_payload, run_id="provenance-run")
    _ledger(connection, 2, "attempt_started", {
        "request_artifact_ref": request, "stage": "radar_judge",
    }, run_id="provenance-run", attempt_id="provenance-attempt")
    truth_payload = {"event_id": 33, "evidence_refs": [{
        "artifact_ref": truth_evidence, "role": "event_evidence_post",
    }]}
    if truth_marker is not None:
        truth_payload["is_synthetic"] = truth_marker
    _ledger(connection, 3, "truth_revision", truth_payload, event_id=33)
    connection.commit()

    review = read_review(connection, WINDOW, FREEZE)
    frame_row = next(item for item in review["input_snapshots"] if item.get("source_kind") == "ledger_input_frame")
    snapshot_row = next(item for item in review["input_snapshots"] if item.get("source_kind") == "ledger_input_snapshot")
    request_row = next(item for item in review["input_snapshots"] if item.get("source_kind") == "ledger_request_descriptor")
    body_row = next(item for item in review["public_evidence"] if item.get("tweet_id") == tweet_id and item.get("text"))
    truth_row = next(item for item in review["public_evidence"] if item.get("role") == "event_evidence_post")
    assert frame_row["is_synthetic"] is run_marker
    assert snapshot_row["is_synthetic"] is run_marker
    assert request_row["is_synthetic"] is run_marker
    assert body_row["is_synthetic"] is expected
    assert truth_row["is_synthetic"] is truth_marker
    if run_marker is True and truth_marker is False:
        assert any(gap["code"] == "artifact_synthetic_provenance_conflict" for gap in review["metadata"]["gaps"])
    if run_marker is True and truth_marker is None:
        assert any(gap["code"] == "artifact_synthetic_provenance_undeclared" for gap in review["metadata"]["gaps"])
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    connection.close()


@pytest.mark.parametrize(
    ("trusted_marker", "external_marker", "expected", "diagnostic"),
    [
        (True, None, True, None),
        (False, None, False, None),
        (None, True, None, "normal_baseline_untrusted_external_provenance_ignored"),
        (True, False, None, "normal_baseline_synthetic_provenance_conflict"),
    ],
)
def test_normal_baseline_provenance_uses_only_frozen_modern_truth(
    trusted_marker: bool | None, external_marker: bool | None,
    expected: bool | None, diagnostic: str | None,
) -> None:
    connection = _connection(ledger=True, artifacts=True, events=True)
    provenance = {"is_synthetic": external_marker} if external_marker is not None else {}
    connection.execute(
        "INSERT INTO reset_events(id,event_type,special_type,occurred_at,occurred_at_end,time_basis,scope,"
        "execution_stage,evidence_post_ids,title,summary,provenance,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (77, "FULL_RESET", None, "2026-10-03T00:00:00Z", None, "explicit_text", "global", "completed",
         "[]", "fixture", "fixture summary", json.dumps(provenance), "2026-10-03T00:00:00Z", "2026-10-03T00:00:00Z"),
    )
    if trusted_marker is not None:
        _ledger(connection, 1, "truth_revision", {
            "event_id": 77, "is_synthetic": trusted_marker,
        }, event_id=77, occurred_at="2026-10-04T00:00:00Z")
    connection.commit()

    review = read_review(connection, WINDOW, FREEZE)
    baseline = next(item for item in review["forecasts"] if item.get("target") == "NORMAL_WEEKLY")
    assert baseline["is_synthetic"] is expected
    if diagnostic:
        assert any(gap["code"] == diagnostic for gap in review["metadata"]["gaps"])
    connection.close()


def test_processing_output_suppresses_parent_derived_text_but_keeps_facts_and_refs() -> None:
    connection = _connection()
    connection.execute(
        "CREATE TABLE tibo_posts(id INTEGER PRIMARY KEY,tweet_id TEXT,text_hash TEXT)"
    )
    connection.execute(
        "CREATE TABLE post_content_policies(post_id INTEGER,content_hash TEXT,judge_evidence_allowed INTEGER,"
        "event_promotion_allowed INTEGER,policy_version TEXT)"
    )
    target_id, parent_id = "111111111111111111", "222222222222222222"
    target_hash, parent_hash = "a" * 64, "b" * 64
    parent_bait = "parent-derived-private-summary-bait"
    connection.executemany(
        "INSERT INTO tibo_posts(id,tweet_id,text_hash) VALUES(?,?,?)",
        [(11, target_id, target_hash), (22, parent_id, parent_hash)],
    )
    connection.executemany(
        "INSERT INTO post_content_policies(post_id,content_hash,judge_evidence_allowed,event_promotion_allowed,policy_version) "
        "VALUES(?,?,?,?,?)",
        [(11, target_hash, 1, 1, "allowed-v1"), (22, parent_hash, 0, 1, "parent-restricted-v1")],
    )
    target_body = _artifact(connection, "target-body", "text_content", {"text": "Allowed target body"})
    parent_body = _artifact(connection, "parent-body", "text_content", {"text": f"Restricted parent {parent_bait}"})
    frame = _artifact(connection, "parent-aware-frame", "input_frame", {
        "input": {
            "posts": [
                {"tweet_id": target_id, "text": {"artifact_ref": target_body, "source_ref": {
                    "post_id": 11, "tweet_id": target_id, "role": "target_post", "source_version": target_hash,
                }}},
                {"tweet_id": parent_id, "text": {"artifact_ref": parent_body, "source_ref": {
                    "post_id": 22, "tweet_id": parent_id, "role": "parent_or_ancestor_context",
                    "parent_tweet_id": target_id, "source_version": parent_hash,
                }}},
            ],
        },
    })
    run_id, attempt_id = "run-parent-policy", "attempt-parent-policy"
    _ledger(connection, 1, "run_started", {
        "is_synthetic": True, "runtime": {"runtime_id": "fixture-runtime"},
        "input_frame_artifact_ref": frame, "input_artifact_refs": [frame, target_body, parent_body],
    }, run_id=run_id)
    _ledger(connection, 2, "attempt_started", {"stage": "post_analysis"}, run_id=run_id, attempt_id=attempt_id)
    output = _artifact(connection, "parent-policy-output", "processing_output", {
        "operation": "post_analysis",
        "output": {
            "tweet_id": target_id, "category": "full_reset", "event_type": "FULL_RESET",
            "summary": parent_bait, "evidence_quote": parent_bait,
        },
    })
    _ledger(connection, 3, "attempt_event", {
        "event_type": "success", "operation": "post_analysis", "output_artifact_ref": output,
        "artifact_refs": [output],
    }, run_id=run_id, attempt_id=attempt_id)
    connection.commit()

    review = read_review(connection, WINDOW, FREEZE)
    projected = next(item for item in review["outputs"] if item.get("output_kind") == "processing_output")
    assert projected["source_content_status"] == "restricted_by_current_policy"
    assert projected["processing_output"]["output"]["category"] == "full_reset"
    assert projected["processing_output"]["output"]["event_type"] == "FULL_RESET"
    assert "summary" not in projected["processing_output"]["output"]
    assert "evidence_quote" not in projected["processing_output"]["output"]
    assert {ref["role"] for ref in projected["evidence_refs"]} == {"target_post", "parent_or_ancestor_context"}
    assert parent_bait not in _all_public_json(review)
    evidence_by_tweet = {item.get("tweet_id"): item for item in review["public_evidence"] if item.get("tweet_id")}
    assert evidence_by_tweet[target_id]["text"] == "Allowed target body"
    assert evidence_by_tweet[parent_id]["text"] is None
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    connection.close()


def test_frozen_export_datafiles_are_stable_and_package_verifies(tmp_path: Path) -> None:
    connection, _ = _integrated_connection()
    staging = tmp_path / "staging"
    staging.mkdir()
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    one = export_review(connection, WINDOW, FREEZE, first, staging,
                        generated_at="2026-10-07T01:00:00Z")
    two = export_review(connection, WINDOW, FREEZE, second, staging,
                        generated_at="2026-10-07T01:01:00Z")
    assert verify_review(first)["valid"] and verify_review(second)["valid"]
    assert list(staging.iterdir()) == []
    assert one["manifest"]["counts"] == two["manifest"]["counts"]
    with zipfile.ZipFile(first) as first_zip, zipfile.ZipFile(second) as second_zip:
        for name in ("forecasts.jsonl", "outputs.jsonl", "attempts.jsonl", "input-snapshots.jsonl", "runtime-identities.jsonl"):
            assert first_zip.read(name) == second_zip.read(name)
        package_text = b" ".join(first_zip.read(name) for name in first_zip.namelist())
        assert b"sk-private-bait-value-01" not in package_text
        assert b"private full prompt" not in package_text
    assert sha256_json({"test": "uses common canonical hash"})
    connection.close()
