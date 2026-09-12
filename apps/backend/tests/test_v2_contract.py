from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db import Database


def event(event_type: str, occurred_at: str, special_type: str | None = None) -> dict:
    return {
        "event_type": event_type,
        "special_type": special_type,
        "occurred_at": occurred_at,
        "source_post_id": None,
        "title": f"Synthetic {event_type} contract fixture",
        "summary": "Synthetic fixture only; not historical evidence.",
        "provenance": {"source": "test_fixture"},
    }


def test_full_reset_closes_previous_cycle_and_opens_new_cycle(settings):
    database = Database(settings.database_path)
    database.initialize()
    first = database.record_reset_event(event("FULL_RESET", "2026-09-01T00:00:00Z"))
    second = database.record_reset_event(event("FULL_RESET", "2026-09-08T00:00:00Z"))
    cycles = database.cycles()

    assert len(cycles) == 2
    assert cycles[0]["ended_at"] == "2026-09-08T00:00:00Z"
    assert cycles[0]["closed_by_reset_event_id"] == second["id"]
    assert cycles[1]["ended_at"] is None
    assert database.last_full_reset()["id"] == second["id"]
    assert first["display_tone"] == "EVENT"


def test_special_reset_is_purple_and_does_not_change_last_full_reset(settings):
    database = Database(settings.database_path)
    database.initialize()
    full = database.record_reset_event(event("FULL_RESET", "2026-09-01T00:00:00Z"))
    special = database.record_reset_event(
        event("SPECIAL_RESET", "2026-09-02T00:00:00Z", "BANKED")
    )

    assert special["display_tone"] == "PURPLE"
    assert special["special_type"] == "BANKED"
    assert database.last_full_reset()["id"] == full["id"]
    assert len(database.cycles()) == 1
    assert database.cycles()[0]["ended_at"] is None


def test_horizons_accept_four_levels_and_unknown(settings):
    database = Database(settings.database_path)
    database.initialize()
    database.add_judgement(
        {
            "created_at": datetime.now(UTC),
            "action_level": "GREEN",
            "horizon_24h": "UNKNOWN",
            "horizon_48h": "YELLOW",
            "horizon_72h": "ORANGE",
            "data_health": "HEALTHY",
            "reason_summary": "Synthetic contract fixture.",
            "evidence_post_ids": [],
            "special_event_ids": [],
            "model": None,
            "prompt_version": "test",
        }
    )
    latest = database.latest_judgement()
    assert latest["action_level"] == "GREEN"
    assert latest["horizon_24h"] == "UNKNOWN"
    assert latest["horizon_48h"] == "YELLOW"
    assert latest["horizon_72h"] == "ORANGE"

    with pytest.raises(ValueError):
        database.add_judgement(
            {
                "action_level": "CONFIRMED",
                "horizon_24h": "UNKNOWN",
                "horizon_48h": "UNKNOWN",
                "horizon_72h": "UNKNOWN",
                "reason_summary": "invalid",
            }
        )
