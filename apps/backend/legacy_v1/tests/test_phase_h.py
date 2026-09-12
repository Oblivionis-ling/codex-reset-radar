from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

import app.main as backend_main
import app.observability as observability
from app.main import create_app


def test_health_endpoints_are_read_only_for_business_state(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{(tmp_path / 'health.db').as_posix()}",
        database_path=tmp_path / "health.db",
    )
    with TestClient(app) as client:
        before = client.get("/api/health").json()
        connection = app.state.engine.raw_connection()
        try:
            before_count = connection.execute("SELECT COUNT(*) FROM heartbeat_history").fetchone()[0]
        finally:
            connection.close()
        assert client.get("/health").status_code == 200
        assert client.get("/api/health").status_code == 200
        connection = app.state.engine.raw_connection()
        try:
            after_count = connection.execute("SELECT COUNT(*) FROM heartbeat_history").fetchone()[0]
        finally:
            connection.close()
        assert after_count == before_count
        assert client.get("/api/health").json() == before
    app.state.engine.dispose()


def test_heartbeat_history_and_trace_are_queryable(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{(tmp_path / 'trace.db').as_posix()}",
        database_path=tmp_path / "trace.db",
    )
    trace_id = "hb-profile-test-trace"
    with TestClient(app) as client:
        response = client.post(
            "/api/heartbeat",
            headers={"X-Trace-ID": trace_id},
            json={
                "component": "profile_monitor",
                "instance_id": "profile-cs-test",
                "sequence": 1,
                "trace_id": trace_id,
                "state": "healthy",
                "metadata": {"url": "https://x.com/thsottiaux"},
            },
        )
        assert response.status_code == 200
        trace = client.get(f"/api/observability/trace/{trace_id}").json()
        names = {item["event"] for item in trace}
        assert "HEARTBEAT_BACKEND_RECEIVED" in names
        assert "HEARTBEAT_DB_COMMITTED" in names
    app.state.engine.dispose()


def test_task_supervisor_records_failed_task(tmp_path, monkeypatch):
    monkeypatch.setattr(observability, "EVENTS_DIR", tmp_path / "events")

    async def scenario():
        supervisor = observability.TaskSupervisor()

        async def crash():
            raise RuntimeError("diagnostic crash")

        task = supervisor.create_task(crash(), "test-crashing-task")
        await asyncio.gather(task, return_exceptions=True)
        return supervisor.snapshot()

    records = asyncio.run(scenario())
    assert records[0]["status"] == "failed"
    events = observability.read_events("backend", limit=20)
    assert any(event["event"] == "TASK_FAILED" for event in events)
