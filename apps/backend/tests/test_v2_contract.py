from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db import Database, next_reset_baseline


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


def test_duplicate_reset_is_idempotent_and_old_backfill_does_not_replace_current_cycle(settings):
    database = Database(settings.database_path)
    database.initialize()
    newest = database.record_reset_event(event("FULL_RESET", "2026-09-08T00:00:00Z"))
    database.record_reset_event(event("FULL_RESET", "2026-09-01T00:00:00Z"))
    database.record_reset_event(event("FULL_RESET", "2026-09-01T00:00:00Z"))
    assert database.last_full_reset()["id"] == newest["id"]
    assert len(database.list_reset_events()) == 2
    assert database.current_cycle()["opened_by_reset_event_id"] == newest["id"]


def test_two_explicitly_linked_reports_of_same_reset_merge_evidence(settings):
    database = Database(settings.database_path)
    database.initialize()
    first = event("FULL_RESET", "2026-09-01T02:29:00Z") | {"scope": "all_paid", "evidence_post_ids": ["fixture-a"]}
    second = event("FULL_RESET", "2026-09-01T02:34:00Z") | {"scope": "work_and_codex", "evidence_post_ids": ["fixture-b"]}
    saved = database.record_reset_event(first)
    # Linking is an explicit event decision, not an inference from five minutes.
    second['event_key'] = saved['event_key']
    merged = database.record_reset_event(second)
    assert len(database.list_reset_events()) == 1
    assert merged["evidence_post_ids"] == ["fixture-a", "fixture-b"]


def test_reviewed_event_range_prevents_reprocessing_its_evidence_as_a_duplicate(settings):
    database = Database(settings.database_path)
    database.initialize()
    reviewed = event("FULL_RESET", "2026-09-01T02:29:00Z") | {
        "event_key": "reviewed-existing-event",
        "occurred_at_end": "2026-09-01T02:34:00Z",
        "scope": "all_paid",
        "evidence_post_ids": ["fixture-a", "fixture-b"],
    }
    existing = database.record_reset_event(reviewed)
    replayed = event("FULL_RESET", "2026-09-01T02:34:00Z") | {
        "scope": "all_paid",
        "evidence_post_ids": ["fixture-b"],
    }

    merged = database.record_reset_event(replayed)

    assert merged["id"] == existing["id"]
    assert merged["evidence_post_ids"] == ["fixture-a", "fixture-b"]
    assert len(database.list_reset_events()) == 1
    assert len(database.cycles()) == 1


def test_nearby_distinct_resets_survive_restarts_without_cycle_id_changes(settings):
    database = Database(settings.database_path)
    database.initialize()
    first = database.record_reset_event(event('FULL_RESET','2026-01-01T01:00:00Z') |
                                        {'evidence_post_ids':['synthetic-first']})
    first_cycle_id = database.current_cycle()['id']
    second = database.record_reset_event(event('FULL_RESET','2026-01-01T02:00:00Z') |
                                         {'evidence_post_ids':['synthetic-second']})
    cycles = database.cycles()
    assert len(cycles)==2 and cycles[0]['id']==first_cycle_id
    database.initialize()
    assert database.cycles()==cycles
    assert len(database.list_reset_events())==2
    assert database.last_full_reset()['id']==second['id']
    assert database.cycles()[0]['opened_by_reset_event_id']==first['id']


def test_same_timestamp_different_evidence_is_not_automatic_event_equivalence(settings):
    database = Database(settings.database_path)
    database.initialize()
    for evidence in ('synthetic-a','synthetic-b'):
        database.record_reset_event(event('FULL_RESET','2026-01-01T01:00:00Z') |
                                    {'evidence_post_ids':[evidence]})
    database.initialize()
    assert len(database.list_reset_events())==2


def test_legacy_key_and_repeated_report_keep_event_id(settings):
    database = Database(settings.database_path)
    database.initialize()
    payload=event('FULL_RESET','2026-01-01T01:00:00Z') | {'evidence_post_ids':['synthetic-legacy']}
    saved=database.record_reset_event(payload)
    with database.connect() as connection:
        connection.execute('UPDATE reset_events SET event_key=? WHERE id=?',('legacy-existing',saved['id']))
    database.initialize()
    assert database.record_reset_event(payload)['id']==saved['id']
    assert len(database.list_reset_events())==1


def test_expired_default_date_is_not_rolled_forward():
    baseline = next_reset_baseline({"occurred_at": "2026-01-01T00:00:00Z"})
    assert baseline["status"] == "expired"
    assert baseline["estimated_at"] == "2026-01-08T00:00:00Z"


def test_browser_translation_cannot_overwrite_preserved_english_original(settings):
    database = Database(settings.database_path)
    database.initialize()
    first = database.upsert_posts_detailed([{"tweet_id": "language-fixture", "text": "Reset has landed.", "source": "test_fixture"}])[0]
    second = database.upsert_posts_detailed([{"tweet_id": "language-fixture", "text": "重置已经生效。", "source": "test_fixture"}])[0]
    post = database.get_post(first["post_id"])
    assert second["status"] == "updated"
    assert second["queue"] is False
    assert post["original_text"] == "Reset has landed."
    assert post["translated_text"] == "重置已经生效。"
