from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.classifiers.rule_classifier import classify_rule
from app.classifiers.providers import DeepSeekProviderError, ProviderResult
from app.classifiers.service import classify_tweet
from app.database import create_database
from app.intelligence.classification_resolver import resolve_classification
from app.intelligence.context_engine import build_context
from app.intelligence.radar import update_radar
from app.models import Classification, Tweet
from app.schemas import ClassificationOutput, RuleClassification
from app.main import create_app


def test_rule_priority_and_categories():
    assert classify_rule("I am resetting everyone today.").category == "reset_announcement"
    assert classify_rule("We are resetting limits today.").category == "reset_in_progress"
    assert classify_rule("We are not resetting limits today.").category == "reset_denial"
    assert classify_rule("Everyone should have their limits reset now.").category == "reset_confirmed"
    assert classify_rule("Codex now has 2x usage limits.").category == "quota_information"
    assert classify_rule("Codex shipped a new feature today.").category == "codex_related"
    assert classify_rule("The weather is beautiful today.").category == "unrelated"


def test_hint_is_ai_candidate_but_button_alone_is_not():
    hint = classify_rule("Maybe I'll dust off the button tomorrow.")
    assert hint.category == "reset_hint"
    assert 0.60 <= hint.confidence <= 0.80
    assert hint.requires_ai is True
    assert classify_rule("The button on my desk is blue.").category == "unrelated"


def test_calibrated_real_language_boundaries():
    sample_a = classify_rule("There is a place and a time for resets. Soon, but not today.")
    assert sample_a.category == "reset_hint"
    assert sample_a.urgency == "within_3d"
    assert sample_a.requires_ai is True

    sample_b = classify_rule(
        "Never slept better and feeling reseted. Brand new me and brand new usage for all ChatGPT Work and Codex users. Regaining my youth one button press at a time."
    )
    assert sample_b.category == "reset_confirmed"
    assert sample_b.requires_ai is True

    assert classify_rule("Reset has been propagated to accounts and you should feel a positive difference.").category == "reset_confirmed"
    assert classify_rule("Reset will land around 14pm PST tomorrow.").category == "reset_announcement"
    assert classify_rule("The banked reset will be there by 8pm PST for paid users.").category == "reset_announcement"
    assert classify_rule("The banked reset has landed.").category == "reset_confirmed"
    assert classify_rule("We will credit every Codex user with a BANKED reset during the day.").category == "reset_announcement"
    assert classify_rule("Tomorrow we will bring back the 5h limit for Plus accounts.").category == "quota_information"


def test_gold_set_rule_expectations():
    fixture_path = Path(__file__).parent / "fixtures" / "tibo_gold_set.json"
    gold_set = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert len([item for item in gold_set if item["expected_category"] == "unrelated"]) >= 5
    assert len([item for item in gold_set if item["expected_category"] == "codex_related"]) >= 3
    assert len([item for item in gold_set if item["expected_category"] == "quota_information"]) >= 3
    for item in gold_set:
        expected = item.get("rule_expected_category", item["expected_category"])
        assert classify_rule(item["text"]).category == expected, item["tweet_id"]


def test_resolver_keeps_explicit_denial_over_conflicting_ai():
    rule = classify_rule("We are not resetting limits today.")
    ai = ClassificationOutput(
        category="reset_hint",
        confidence=0.86,
        urgency="within_24h",
        explicitness="implicit",
        reason="The wording may be metaphorical.",
    )
    decision = resolve_classification(rule, ai)
    assert decision.result.category == "reset_denial"
    assert decision.conflict is True


def test_resolver_allows_high_confidence_ai_reset_event_over_quota_rule():
    rule = RuleClassification(
        category="quota_information",
        confidence=0.78,
        urgency="unknown",
        explicitness="unclear",
        reason="Quota phrase requires semantic review.",
        requires_ai=True,
    )
    ai = ClassificationOutput(
        category="reset_announcement",
        confidence=0.92,
        urgency="within_24h",
        explicitness="explicit",
        reason="The banked reset is explicitly scheduled for distribution.",
    )
    decision = resolve_classification(rule, ai)
    assert decision.result.category == "reset_announcement"
    assert decision.result.confidence == 0.92
    assert decision.conflict is True


def test_context_engine_prefers_parent_and_related_tweets(tmp_path):
    engine, session_factory = create_database(
        f"sqlite:///{(tmp_path / 'context.db').as_posix()}", tmp_path / "context.db"
    )
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        parent = Tweet(
            tweet_id="parent",
            author="thsottiaux",
            text="Where did I leave the reset button?",
            url="https://x.com/thsottiaux/status/parent",
            created_at=now,
            discovered_at=now,
        )
        reply = Tweet(
            tweet_id="reply",
            author="thsottiaux",
            text="Maybe tomorrow.",
            url="https://x.com/thsottiaux/status/reply",
            is_reply=True,
            reply_to="parent",
            created_at=now,
            discovered_at=now + timedelta(seconds=1),
        )
        session.add_all([parent, reply])
        session.commit()
        context = build_context(session, reply)
        assert context["parent_context"]["tweet_id"] == "parent"
        assert context["recent_related_tweets"][0]["tweet_id"] == "parent"
    engine.dispose()


def test_radar_transitions_and_signal_expiry(tmp_path):
    engine, session_factory = create_database(
        f"sqlite:///{(tmp_path / 'radar.db').as_posix()}", tmp_path / "radar.db"
    )
    signal_time = datetime(2026, 8, 28, tzinfo=timezone.utc)
    with session_factory() as session:
        session.add(Tweet(tweet_id="t1", author="thsottiaux", text="hint", url="https://x.com/t1"))
        session.add(
            Classification(
                tweet_id="t1",
                classifier_type="final",
                category="reset_hint",
                confidence=0.80,
                urgency="unknown",
                explicitness="implicit",
                reason="hint",
                created_at=signal_time,
            )
        )
        session.commit()
        assert update_radar(session, signal_time + timedelta(hours=1)).state == "LIKELY"
        session.commit()
        assert update_radar(session, signal_time + timedelta(hours=73)).state == "QUIET"
        session.commit()
    engine.dispose()


def test_ai_failure_fallback_is_representable():
    # The resolver is the pure failure boundary used by the async service.
    rule = classify_rule("Maybe I'll dust off the button tomorrow.")
    fallback = resolve_classification(rule, None)
    assert fallback.result.category == "reset_hint"
    assert "AI unavailable" in fallback.result.reason


def test_explicit_rule_without_ai_does_not_claim_ai_fallback():
    rule = classify_rule("The banked reset has landed.")
    decision = resolve_classification(rule, None)
    assert decision.result.category == "reset_confirmed"
    assert "AI unavailable" not in decision.result.reason
    assert decision.reason == "rule_only"


class MockProvider:
    model_name = "mock-deepseek"

    async def classify(self, context, rule_result):
        return ProviderResult(
            result=ClassificationOutput(
                category="reset_hint",
                confidence=0.91,
                urgency="within_24h",
                explicitness="implicit",
                reason="Mock semantic result using the supplied context.",
            ),
            input_tokens=12,
            output_tokens=8,
        )


class FailingProvider:
    model_name = "mock-deepseek"

    async def classify(self, context, rule_result):
        raise DeepSeekProviderError("mock timeout")


def test_mock_provider_preserves_rule_ai_and_final_audit_rows(tmp_path):
    engine, session_factory = create_database(
        f"sqlite:///{(tmp_path / 'pipeline.db').as_posix()}", tmp_path / "pipeline.db"
    )
    with session_factory() as session:
        session.add(
            Tweet(
                tweet_id="pipeline",
                author="thsottiaux",
                text="Maybe I'll dust off the button tomorrow.",
                url="https://x.com/pipeline",
            )
        )
        session.commit()
        result = asyncio.run(classify_tweet(session, "pipeline", provider=MockProvider()))
        rows = session.query(Classification).filter(Classification.tweet_id == "pipeline").order_by(Classification.id).all()
        assert [row.classifier_type for row in rows] == ["rule", "ai", "final"]
        assert result["final"]["category"] == "reset_hint"
        assert result["classification_pending"] is False
    engine.dispose()


def test_mock_provider_failure_keeps_rule_result_and_pending_flag(tmp_path):
    engine, session_factory = create_database(
        f"sqlite:///{(tmp_path / 'failure.db').as_posix()}", tmp_path / "failure.db"
    )
    with session_factory() as session:
        session.add(
            Tweet(
                tweet_id="failure",
                author="thsottiaux",
                text="Maybe I'll dust off the button tomorrow.",
                url="https://x.com/failure",
            )
        )
        session.commit()
        result = asyncio.run(classify_tweet(session, "failure", provider=FailingProvider()))
        final = session.query(Classification).filter(
            Classification.tweet_id == "failure", Classification.classifier_type == "final"
        ).one()
        assert result["classification_pending"] is True
        assert final.classification_pending is True
        assert "AI unavailable" in final.reason
    engine.dispose()


def test_phase_b_api_exposes_classification_and_radar(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}", database_path=tmp_path / "api.db")
    with TestClient(app) as client:
        response = client.post(
            "/api/ingest/tweets",
            json={
                "tweets": [
                    {
                        "tweet_id": "api-hint",
                        "author": "thsottiaux",
                        "text": "Maybe I'll dust off the button tomorrow.",
                        "url": "https://x.com/thsottiaux/status/api-hint",
                        "source": "profile_dom",
                    }
                ]
            },
        )
        assert response.status_code == 200
        classification = client.get("/api/tweets/api-hint/classification").json()
        assert [row["classifier_type"] for row in classification["classifications"]] == ["rule", "final"]
        assert classification["classifications"][-1]["classification_pending"] is True
        assert client.get("/api/radar").json()["state"] == "WATCH"
    app.state.engine.dispose()
