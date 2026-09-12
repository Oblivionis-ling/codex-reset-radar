from __future__ import annotations


def test_health_exposes_shared_version_and_no_github_runtime(client):
    response = client.get("/api/v2/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "0.1.0-alpha.1"
    assert payload["status"] == "healthy"
    assert payload["runtime"]["github_mirror_enabled"] is False
    assert payload["runtime"]["pages_dependency"] is False


def test_initial_radar_is_white_unknown_without_confidence(client):
    response = client.get("/api/v2/radar")
    assert response.status_code == 200
    payload = response.json()
    assert payload["action_level"] == "UNKNOWN"
    assert payload["horizon_24h"] == "UNKNOWN"
    assert payload["horizon_48h"] == "UNKNOWN"
    assert payload["horizon_72h"] == "UNKNOWN"
    assert payload["next_reset"]["status"] == "waiting_for_verified_history"
    assert "confidence" not in payload
    assert "confidence_percentage" not in payload


def test_transitional_collector_ingests_and_deduplicates_without_persisting_heartbeat(client):
    payload = {
        "tweets": [
            {
                "tweet_id": "fixture-post-1",
                "text": "Synthetic contract fixture; not a real Tibo post.",
                "created_at": "2026-09-13T00:00:00Z",
                "url": "https://example.invalid/fixture-post-1",
                "is_reply": False,
                "source": "test_fixture",
                "discovered_at": "2026-09-13T00:01:00Z",
            }
        ]
    }
    first = client.post("/api/ingest/tweets", json=payload)
    second = client.post("/api/v2/collector/posts", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    posts = client.get("/api/v2/posts").json()
    assert posts["count"] == 1
    assert posts["items"][0]["source"] == "test_fixture"

    heartbeat = client.post(
        "/api/heartbeat",
        json={"component": "profile_monitor", "instance_id": "fixture-instance", "sequence": 1},
    )
    assert heartbeat.json() == {"accepted": True, "persisted": False}
    health = client.get("/api/v2/health").json()
    assert health["collector"]["profile_monitor"]["sequence"] == 1
    assert "heartbeat_history" not in health["database"]["counts"]
