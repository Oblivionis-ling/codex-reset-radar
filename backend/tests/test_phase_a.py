from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.main import create_app


def make_client(tmp_path):
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}", database_path=tmp_path / 'test.db')
    return TestClient(app)


def tweet(tweet_id: str, source: str):
    return {
        "tweet_id": tweet_id,
        "author": "thsottiaux",
        "text": "A collector test Tweet",
        "created_at": "2026-08-28T00:00:00Z",
        "url": f"https://x.com/thsottiaux/status/{tweet_id}",
        "is_reply": source == "with_replies",
        "source": source,
    }


def test_profile_search_replies_are_one_tweet_with_three_sources(tmp_path):
    with make_client(tmp_path) as client:
        first = client.post("/api/ingest/tweets", json={"tweets": [tweet("123", "profile_dom")]})
        second = client.post("/api/ingest/tweets", json={"tweets": [tweet("123", "search")]})
        third = client.post("/api/ingest/tweets", json={"tweets": [tweet("123", "with_replies")]})

        assert first.json()["created"] == 1
        assert second.json()["created"] == 0
        assert third.json()["created"] == 0
        rows = client.get("/api/tweets").json()
        assert len(rows) == 1
        assert set(rows[0]["sources"]) == {"profile_dom", "search", "with_replies"}
        assert rows[0]["is_reply"] is True


def test_health_endpoint_and_heartbeat_are_observable(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/health").json()["status"] == "ok"
        response = client.post(
            "/api/heartbeat",
            json={"component": "profile_monitor", "state": "healthy", "metadata": {"url": "profile"}},
        )
        assert response.json()["ok"] is True
        detail = client.get("/api/health").json()
        assert {entry["component"] for entry in detail} >= {"backend", "profile_monitor"}
        profile = next(entry for entry in detail if entry["component"] == "profile_monitor")
        assert profile["metadata"] == {"url": "profile"}


def test_monitor_diagnostics_are_persisted_and_queryable(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/diagnostics",
            json={
                "component": "profile_monitor",
                "event": "CONTENT_SCRIPT_INIT",
                "observed_at": "2026-08-30T03:00:00Z",
                "details": {
                    "monitor": "profile",
                    "has_target_dom": True,
                    "observer_attached": True,
                    "tab_discarded": False,
                },
            },
        )
        assert response.status_code == 200
        rows = client.get("/api/diagnostics?component=profile_monitor&limit=1").json()
        assert rows[0]["event"] == "CONTENT_SCRIPT_INIT"
        assert rows[0]["details"]["tab_discarded"] is False


def test_phase_a_schema_includes_reserved_phase_tables(tmp_path):
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'schema.db').as_posix()}", database_path=tmp_path / "schema.db")
    expected = {
        "tweets",
        "tweet_sources",
        "classifications",
        "reset_events",
        "status_events",
        "alerts",
        "monitor_health",
        "monitor_diagnostic_events",
        "sync_queue",
    }
    assert expected <= set(inspect(app.state.engine).get_table_names())
    app.state.engine.dispose()
