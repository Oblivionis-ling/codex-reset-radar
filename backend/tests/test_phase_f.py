from datetime import datetime, timezone

from app.classifiers.providers import TranslationResult
from app.classifiers.service import translate_tweet
from app.config import Settings
from app.database import create_database
from app.intelligence.forecast import build_forecast, build_reset_history, derive_usage_advice, parse_announcement_time
from app.models import Tweet


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def test_forecast_uses_last_confirmed_plus_seven_days() -> None:
    history = build_reset_history(
        [],
        [{"event_time": "2026-08-28T06:00:00Z", "evidence_tweet_id": "r1", "text": "reset landed"}],
    )
    result = build_forecast(history, [], [], now=NOW)
    assert result["last_reset_at"] == "2026-08-28T06:00:00Z"
    assert result["estimated_next_reset_at"] == "2026-09-04T06:00:00Z"
    assert result["forecast_source"] == "weekly_baseline"


def test_within_24h_hint_overrides_baseline() -> None:
    history = build_reset_history([], [{"event_time": "2026-08-26T06:00:00Z", "evidence_tweet_id": "r1", "text": "reset landed"}])
    result = build_forecast(
        history,
        [{"event_time": "2026-08-30T08:00:00Z", "evidence_tweet_id": "h1", "urgency": "within_24h"}],
        [],
        now=NOW,
    )
    assert result["forecast_source"] == "reset_hint"
    assert result["signal_window"] == "within_24h"


def test_explicit_announcement_overrides_hint() -> None:
    target = parse_announcement_time("Reset will land around 2pm PST tomorrow.", "2026-08-30T12:00:00Z")
    assert target == datetime(2026, 8, 31, 22, 0, tzinfo=timezone.utc)
    history = build_reset_history([], [])
    result = build_forecast(
        history,
        [{"event_time": "2026-08-30T08:00:00Z", "evidence_tweet_id": "h1", "urgency": "within_24h"}],
        [{"event_time": "2026-08-30T12:00:00Z", "evidence_tweet_id": "a1", "text": "Reset will land around 2pm PST tomorrow."}],
        now=NOW,
    )
    assert result["forecast_source"] == "reset_announcement"
    assert result["estimated_next_reset_at"] == "2026-08-31T22:00:00Z"


def test_confirmed_advice_is_green_and_does_not_urge_usage() -> None:
    advice = derive_usage_advice("CONFIRMED", {"estimated_next_reset_at": "2026-09-06T00:00:00Z"}, now=NOW)
    assert advice["level"] == "GREEN"
    assert advice["title_code"] == "reset_confirmed"


def test_translation_is_cached_as_an_additional_field(tmp_path) -> None:
    class FakeProvider:
        model_name = "fake-translation"

        async def translate(self, text, *, context=None):
            return TranslationResult("中文翻译：" + text, input_tokens=2, output_tokens=3)

    engine, session_factory = create_database(
        f"sqlite:///{(tmp_path / 'translation.db').as_posix()}", tmp_path / "translation.db"
    )
    settings = Settings(
        database_path=tmp_path / "translation.db",
        host="127.0.0.1",
        port=8787,
        deepseek_api_key="",
        deepseek_model="fake",
        deepseek_base_url="https://example.test",
        prompt_version="test",
        translation_version="translation-v1",
    )
    with session_factory() as session:
        session.add(Tweet(tweet_id="translation", text="reset button", url="https://x.com/translation"))
        session.commit()
        import asyncio

        first = asyncio.run(translate_tweet(session, "translation", provider=FakeProvider(), settings=settings))
        second = asyncio.run(translate_tweet(session, "translation", provider=FakeProvider(), settings=settings))
        row = session.get(Tweet, "translation")
        assert first["translated"] is True
        assert second["reason"] == "cached"
        assert row.translated_zh == "中文翻译：reset button"
        assert row.text == "reset button"
    engine.dispose()
