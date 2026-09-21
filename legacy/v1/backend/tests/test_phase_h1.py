from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

import app.observability as observability
from app.database import create_database
from app.main import create_app


def test_tail_jsonl_reads_recent_records_without_read_text(tmp_path, monkeypatch) -> None:
    path = tmp_path / "backend-2026-09-08.jsonl"
    path.write_bytes(b"\n".join(json.dumps({"timestamp": f"2026-09-08T00:00:{index:02d}Z", "event": "E"}).encode() for index in range(100)) + b"\n")

    def fail_read_text(*args, **kwargs):
        raise AssertionError("tail_jsonl must not call Path.read_text")

    monkeypatch.setattr(type(path), "read_text", fail_read_text)
    records = observability.tail_jsonl(path, limit=5)

    assert [record["timestamp"] for record in records] == [
        "2026-09-08T00:00:95Z",
        "2026-09-08T00:00:96Z",
        "2026-09-08T00:00:97Z",
        "2026-09-08T00:00:98Z",
        "2026-09-08T00:00:99Z",
    ]


def test_append_event_uses_daily_shards_and_legacy_file_is_archivable(tmp_path, monkeypatch) -> None:
    events_dir = tmp_path / "events"
    monkeypatch.setattr(observability, "EVENTS_DIR", events_dir)
    legacy = events_dir / "backend.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"event":"old"}\n', encoding="utf-8")

    observability.append_event("backend", "NEW_EVENT", timestamp="2026-09-08T01:02:03Z")
    archived = observability.archive_legacy_event_file(legacy, now=datetime(2026, 9, 8, tzinfo=timezone.utc))

    assert (events_dir / "backend-2026-09-08.jsonl").exists()
    assert archived is not None and archived.name.startswith("backend-events-legacy-2026-09-08")
    assert not legacy.exists()
    assert observability.read_events("backend", 10)[-1]["event"] == "NEW_EVENT"


def test_trace_api_has_time_window_and_bounded_diagnostic_query(tmp_path) -> None:
    database_path = tmp_path / "trace.db"
    app = create_app(
        database_url=f"sqlite:///{database_path.as_posix()}",
        database_path=database_path,
    )
    trace_id = "h1-bounded-trace"
    with TestClient(app) as client:
        response = client.post(
            "/api/diagnostics",
            json={
                "component": "profile_monitor",
                "event": "CONTENT_SCRIPT_INIT",
                "trace_id": trace_id,
                "details": {"trace_id": trace_id},
            },
        )
        assert response.status_code == 200
        assert client.get(f"/api/observability/trace/{trace_id}?limit=999999").status_code == 200
        assert client.get(f"/api/observability/trace/{trace_id}?since=2020-01-01T00:00:00Z").status_code == 400
    app.state.engine.dispose()


def test_database_has_observability_indexes_and_diagnostics_since_is_bounded(tmp_path) -> None:
    database_path = tmp_path / "indexes.db"
    engine, _ = create_database(f"sqlite:///{database_path.as_posix()}", database_path)
    try:
        rows = engine.raw_connection().execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        names = {row[0] for row in rows}
        assert {
            "ix_heartbeat_history_component_received",
            "ix_monitor_diagnostic_events_component_observed",
            "ix_monitor_diagnostic_events_component_created",
            "ix_monitor_diagnostic_events_created_at",
            "ix_health_state_history_component_changed",
            "ix_alerts_created_at",
        }.issubset(names)
        plan = engine.raw_connection().execute(
            "EXPLAIN QUERY PLAN SELECT * FROM heartbeat_history "
            "WHERE component='profile_monitor' AND backend_received_at >= '2026-09-01 00:00:00' "
            "ORDER BY id DESC LIMIT 10"
        ).fetchall()
        assert any("ix_heartbeat_history_component_received" in str(row) for row in plan)
    finally:
        engine.dispose()


def test_retention_prunes_shards_by_date_without_parsing_active_file(tmp_path, monkeypatch) -> None:
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    monkeypatch.setattr(observability, "EVENTS_DIR", events_dir)
    old_path = events_dir / "backend-2026-08-01.jsonl"
    current_path = events_dir / "backend-2026-09-08.jsonl"
    old_path.write_bytes(b"not-json-and-never-parsed\n")
    current_path.write_bytes(b"not-json-and-must-remain\n")

    deleted = observability.prune_event_shards(
        retention_days={"backend": 14},
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    assert deleted == 1
    assert not old_path.exists()
    assert current_path.exists()


def test_diagnostic_lock_is_classified_without_claiming_writer_or_reader(tmp_path, monkeypatch) -> None:
    events_dir = tmp_path / "events"
    monkeypatch.setattr(observability, "EVENTS_DIR", events_dir)
    engine, session_factory = create_database(
        f"sqlite:///{(tmp_path / 'lock.db').as_posix()}",
        tmp_path / "lock.db",
    )
    session = session_factory()
    session.commit = lambda: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked"))
    from app.schemas import DiagnosticPayload

    try:
        with pytest.raises(sqlite3.OperationalError):
            from app.ingestion import record_diagnostic

            record_diagnostic(
                session,
                DiagnosticPayload(component="profile_monitor", event="TEST_LOCK"),
            )
        records = observability.read_events("backend", limit=10)
        lock_records = [record for record in records if record["event"] == "SQLITE_LOCK_DETECTED"]
        assert lock_records
        assert lock_records[-1]["operation"] == "diagnostic_write"
        assert lock_records[-1]["suspected_contention"] == "reader_or_writer_contention"
    finally:
        session.close()
        engine.dispose()
