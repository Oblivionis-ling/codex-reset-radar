from __future__ import annotations

import time
import json

from fastapi.testclient import TestClient

from app.deepseek import DeepSeekError
from app.main import create_app


class FakeDeepSeek:
    model = "fake-deepseek-test"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete_json(self, *, operation: str, system: str, user: str):
        self.calls.append(operation)
        if operation == "post_translation":
            return {"translation_zh": "隔离测试译文"}
        if operation == "radar_judge":
            return {
                "action_level": "GREEN", "horizon_24h": "GREEN", "horizon_48h": "YELLOW", "horizon_72h": "ORANGE",
                "estimated_start": None, "estimated_end": None, "estimate_basis": "隔离测试没有真实时间判断。",
                "reason_summary": "隔离测试合法 Judge 输出。", "evidence_post_ids": [],
            }
        body = json.loads(user.rsplit('\n', 1)[-1])["post"]["text"]
        special = "banked" in body.lower()
        result = {
            "category": "reset_confirmed" if special else "other", "codex_relevant": special,
            "temporal_mode": "present", "explicit_announcement": special,
            "event_status": "confirmed" if special else "none",
            "event_type": "SPECIAL_RESET" if special else "NONE", "special_type": "BANKED" if special else None,
            "canonical_eligible": special, "scope": "banked_only" if special else "unknown",
            "execution_stage": "completed" if special else "unknown", "event_time_start": None, "event_time_end": None,
            "time_basis": "post_time_proxy", "evidence_quote": "banked reset", "summary": "隔离测试分析。", "event_title": "隔离 Special Reset",
        }
        result["effects"] = [{k:v for k,v in result.items() if k != "category"}] if special else []
        return result

    async def close(self) -> None:
        return None


class FailingDeepSeek(FakeDeepSeek):
    async def complete_json(self, *, operation: str, system: str, user: str):
        self.calls.append(operation)
        raise DeepSeekError("synthetic timeout", category="timeout", retryable=True)


class TranslationFailingDeepSeek(FakeDeepSeek):
    async def complete_json(self, *, operation: str, system: str, user: str):
        if operation == "post_translation":
            self.calls.append(operation)
            raise DeepSeekError("synthetic translation timeout", category="timeout", retryable=True)
        return await super().complete_json(operation=operation, system=system, user=user)


def wait_until(predicate, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition was not met before timeout")


def fixture_payload(tweet_id: str, text: str = "Synthetic banked reset fixture.") -> dict:
    return {"tweets": [{"tweet_id": tweet_id, "text": text, "created_at": "2026-09-13T00:00:00Z",
                         "url": f"https://example.invalid/{tweet_id}", "source": "test_fixture"}]}


def test_new_post_runs_pipeline_duplicate_does_not_repeat_model_and_judge_reaches_api(settings):
    fake = FakeDeepSeek()
    with TestClient(create_app(settings, intelligence_client=fake)) as client:
        client.post("/api/v2/collector/heartbeat", json={
            "component": "profile_monitor", "instance_id": "profile-fixture", "sequence": 1,
        })
        client.post("/api/v2/collector/heartbeat", json={
            "component": "replies_monitor", "instance_id": "replies-fixture", "sequence": 1,
        })
        first = client.post("/api/v2/collector/posts", json=fixture_payload("pipeline-fixture-1")).json()
        second = client.post("/api/v2/collector/posts", json=fixture_payload("pipeline-fixture-1")).json()
        assert first["new"] == 1 and first["queued"] == 1
        assert second["duplicate"] == 1 and second["queued"] == 0

        wait_until(lambda: client.get("/api/v2/posts").json()["items"][0]["analysis_status"] == "COMPLETED")
        wait_until(lambda: client.get("/api/v2/radar").json()["judgement_id"] is not None)
        post = client.get("/api/v2/posts").json()["items"][0]
        radar = client.get("/api/v2/radar").json()
        resets = client.get("/api/v2/resets").json()
        assert post["translated_text"] == "隔离测试译文"
        assert post["analysis"]["category"] == "reset_confirmed"
        assert radar["action_level"] == "GREEN"
        assert resets["items"][0]["event_type"] == "SPECIAL_RESET"
        assert resets["last_full_reset"] is None
        assert fake.calls.count("post_analysis") == 1
        assert fake.calls.count("post_translation") == 1
        assert fake.calls.count("radar_judge") == 1


def test_model_failure_does_not_lose_collected_post(settings):
    fake = FailingDeepSeek()
    with TestClient(create_app(settings, intelligence_client=fake)) as client:
        response = client.post("/api/v2/collector/posts", json=fixture_payload("pipeline-failure-1", "Synthetic ordinary fixture."))
        assert response.status_code == 200
        wait_until(lambda: client.get("/api/v2/posts").json()["items"][0]["analysis_status"] == "FAILED")
        post = client.get("/api/v2/posts").json()["items"][0]
        assert post["tweet_id"] == "pipeline-failure-1"
        assert "DeepSeekError" in post["processing_error"]


def test_translation_failure_does_not_erase_completed_analysis(settings):
    fake = TranslationFailingDeepSeek()
    with TestClient(create_app(settings, intelligence_client=fake)) as client:
        client.post("/api/v2/collector/posts", json=fixture_payload("translation-failure-1", "Synthetic ordinary fixture."))
        wait_until(lambda: client.get("/api/v2/posts").json()["items"][0]["translation_status"] == "FAILED")
        post = client.get("/api/v2/posts").json()["items"][0]
        assert post["analysis_status"] == "COMPLETED"
        assert post["analysis"] is not None
