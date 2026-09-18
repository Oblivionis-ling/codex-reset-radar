from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app


def policy(tweet_id: str, content_hash: str, **overrides) -> dict:
    value = {
        "policy_version": "content-policy-v1",
        "tweet_id": tweet_id,
        "content_hash": content_hash,
        "policy_status": "INSUFFICIENT_INPUT",
        "analysis_allowed": True,
        "event_promotion_allowed": False,
        "judge_evidence_allowed": False,
        "historical_case_allowed": False,
        "reason": "Synthetic incomplete-input fixture.",
        "decision_ids": ["synthetic-review-decision"],
    }
    value.update(overrides)
    return value


def judgement(evidence_post_ids: list[str], *, valid_until: str = "2099-01-01T02:00:00Z") -> dict:
    return {
        "created_at": "2099-01-01T00:00:00Z",
        "action_level": "GREEN",
        "horizon_24h": "GREEN",
        "horizon_48h": "YELLOW",
        "horizon_72h": "ORANGE",
        "data_health": "HEALTHY",
        "reason_summary": "Synthetic policy fixture.",
        "evidence_post_ids": evidence_post_ids,
        "special_event_ids": [],
        "model": "synthetic",
        "prompt_version": "synthetic",
        "valid_until": valid_until,
        "status": "COMPLETED",
    }


class PolicyFakeDeepSeek:
    model = "fake-policy-model"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete_json(self, *, operation: str, system: str, user: str):
        self.calls.append(operation)
        if operation == "post_translation":
            return {"translation_zh": "隔离策略测试译文"}
        if operation == "radar_judge":
            return judgement([]) | {
                "estimated_start": None,
                "estimated_end": None,
                "estimate_basis": "隔离策略测试。",
            }
        post = json.loads(user.rsplit("\n", 1)[-1])["post"]
        return {
            "category": "reset_confirmed",
            "codex_relevant": True,
            "temporal_mode": "present",
            "explicit_announcement": True,
            "event_status": "confirmed",
            "event_type": "SPECIAL_RESET",
            "special_type": "BANKED",
            "canonical_eligible": True,
            "scope": "banked_only",
            "execution_stage": "completed",
            "event_time_start": None,
            "event_time_end": None,
            "time_basis": "post_time_proxy",
            "evidence_quote": post["text"],
            "summary": "Synthetic restricted event.",
            "event_title": "Synthetic restricted event",
            "effects": [{
                "event_status": "confirmed",
                "event_type": "SPECIAL_RESET",
                "special_type": "BANKED",
                "canonical_eligible": True,
                "scope": "banked_only",
                "execution_stage": "completed",
                "temporal_mode": "present",
                "claim_kind": "occurrence",
                "event_time_start": None,
                "event_time_end": None,
                "time_basis": "post_time_proxy",
                "evidence_quote": post["text"],
                "summary": "Synthetic restricted event.",
            }],
        }

    async def close(self) -> None:
        return None


def wait_until(predicate, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition was not met before timeout")


def test_content_version_policy_filters_all_downstream_uses(settings):
    database = Database(settings.database_path)
    database.initialize()
    restricted = database.upsert_posts_detailed([{
        "tweet_id": "policy-restricted",
        "text": "Synthetic untrusted body.",
        "posted_at": "2026-09-13T00:00:00Z",
    }])[0]
    allowed = database.upsert_posts_detailed([{
        "tweet_id": "policy-allowed",
        "text": "Synthetic allowed body.",
        "posted_at": "2026-09-13T01:00:00Z",
    }])[0]
    for item in (restricted, allowed):
        database.save_analysis(
            item["post_id"], item["content_hash"], "synthetic", "synthetic",
            {"category": "other", "summary": "Synthetic analysis."},
        )
    database.upsert_content_policy(policy("policy-restricted", restricted["content_hash"]))

    database.register_corpus_source({
        "source_id": "policy-fixture",
        "name": "Policy fixture",
        "entry_url": "https://example.invalid/policy-fixture",
        "provides_tweet_ids": True,
    })
    database.upsert_historical_case({
        "case_id": "restricted-primary-case",
        "tweet_id": "policy-restricted",
        "source_id": "policy-fixture",
        "source_record_key": "restricted-primary-case",
        "posted_at": "2026-01-01T00:00:00Z",
        "original_text": "Synthetic restricted case.",
        "outcome_type": "UNKNOWN",
        "verification_status": "direct_verified",
        "corpus_version": "synthetic",
    })
    database.upsert_historical_case({
        "case_id": "restricted-related-case",
        "tweet_id": "policy-allowed",
        "source_id": "policy-fixture",
        "source_record_key": "restricted-related-case",
        "posted_at": "2026-01-02T00:00:00Z",
        "original_text": "Synthetic related case.",
        "outcome_type": "UNKNOWN",
        "verification_status": "direct_verified",
        "related_tweet_ids": ["policy-restricted"],
        "corpus_version": "synthetic",
    })

    context = database.judgement_context(as_of="2026-09-14T00:00:00Z")
    assert [post["tweet_id"] for post in context["posts"]] == ["policy-allowed"]
    assert context["historical_cases"] == []
    with pytest.raises(ValueError, match="content-policy-ineligible"):
        database.add_judgement(judgement(["policy-restricted"]))


def test_changed_content_stays_quarantined_until_new_version_is_reviewed(settings):
    database = Database(settings.database_path)
    database.initialize()
    first = database.upsert_posts_detailed([{
        "tweet_id": "policy-version-change",
        "text": "Synthetic incomplete body.",
    }])[0]
    database.upsert_content_policy(policy("policy-version-change", first["content_hash"]))
    database.upsert_posts_detailed([{
        "tweet_id": "policy-version-change",
        "text": "Synthetic corrected complete body.",
    }])
    post = database.get_post(first["post_id"])

    assert database.content_policy(first["post_id"])["policy_status"] == "CONTENT_VERSION_CHANGED_REVIEW_REQUIRED"
    assert database.content_use_allowed(post, "judge_evidence") is False

    database.upsert_content_policy(policy(
        "policy-version-change",
        post["text_hash"],
        policy_status="REVIEWED_CURRENT_VERSION",
        analysis_allowed=True,
        event_promotion_allowed=True,
        judge_evidence_allowed=True,
        historical_case_allowed=True,
    ))
    assert database.content_use_allowed(database.get_post(first["post_id"]), "judge_evidence") is True


def test_pipeline_keeps_archive_but_blocks_analysis_or_event_promotion(settings):
    database = Database(settings.database_path)
    database.initialize()
    author_conflict = database.upsert_posts_detailed([{
        "tweet_id": "policy-author-conflict",
        "text": "Synthetic body belongs to another author.",
        "posted_at": "2026-09-13T00:00:00Z",
    }])[0]
    incomplete = database.upsert_posts_detailed([{
        "tweet_id": "policy-incomplete-context",
        "text": "Synthetic banked reset without context.",
        "posted_at": "2026-09-13T01:00:00Z",
    }])[0]
    database.upsert_content_policy(policy(
        "policy-author-conflict", author_conflict["content_hash"], analysis_allowed=False,
    ))
    database.upsert_content_policy(policy("policy-incomplete-context", incomplete["content_hash"]))

    fake = PolicyFakeDeepSeek()
    with TestClient(create_app(settings, intelligence_client=fake)) as client:
        wait_until(lambda: client.get("/api/v2/health").json()["database"]["counts"]["processing_jobs"] == 2)
        wait_until(lambda: all(
            item["analysis_status"] in {"INPUT_RESTRICTED", "COMPLETED"}
            for item in client.get("/api/v2/posts").json()["items"]
        ))
        posts = {item["tweet_id"]: item for item in client.get("/api/v2/posts").json()["items"]}
        assert posts["policy-author-conflict"]["analysis_status"] == "INPUT_RESTRICTED"
        assert posts["policy-incomplete-context"]["analysis_status"] == "COMPLETED"
        assert client.get("/api/v2/resets").json()["items"] == []
        assert fake.calls.count("post_analysis") == 1


def test_expired_judgement_is_not_presented_as_a_current_level(settings):
    database = Database(settings.database_path)
    database.initialize()
    expired = judgement([], valid_until="2000-01-01T00:30:00Z")
    expired["created_at"] = "2000-01-01T00:00:00Z"
    database.add_judgement(expired)

    with TestClient(create_app(settings)) as client:
        payload = client.get("/api/v2/radar").json()
    assert payload["judgement_id"] is not None
    assert payload["judgement_state"] == "stale"
    assert payload["action_level"] == "UNKNOWN"
    assert payload["horizon_72h"] == "UNKNOWN"
