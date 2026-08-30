from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from scripts.public_export import build_snapshot, write_snapshot


def create_mirror_fixture(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE tweets (
            tweet_id TEXT PRIMARY KEY,
            author TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT,
            url TEXT NOT NULL,
            is_reply INTEGER NOT NULL,
            reply_to TEXT,
            discovered_at TEXT NOT NULL
        );
        CREATE TABLE tweet_sources (
            id INTEGER PRIMARY KEY,
            tweet_id TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE classifications (
            id INTEGER PRIMARY KEY,
            tweet_id TEXT NOT NULL,
            classifier_type TEXT NOT NULL,
            category TEXT NOT NULL,
            confidence REAL,
            urgency TEXT,
            explicitness TEXT,
            reason TEXT,
            model_name TEXT,
            prompt_version TEXT,
            created_at TEXT
        );
        CREATE TABLE radar_state (
            id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            confidence REAL NOT NULL,
            urgency TEXT NOT NULL,
            trigger_tweet_id TEXT,
            reason TEXT NOT NULL,
            updated_at TEXT,
            expires_at TEXT
        );
        CREATE TABLE monitor_health (
            component TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            last_heartbeat TEXT NOT NULL
        );
        CREATE TABLE alerts (id INTEGER PRIMARY KEY, error TEXT);
        CREATE TABLE monitor_diagnostic_events (id INTEGER PRIMARY KEY, details_json TEXT);
        INSERT INTO tweets VALUES
            ('123', 'thsottiaux', 'A public signal with secret-uid', '2026-08-30 01:00:00',
             'http://localhost/private', 0, NULL, '2026-08-30 01:01:00');
        INSERT INTO tweet_sources VALUES (1, '123', 'profile_dom');
        INSERT INTO classifications VALUES
            (1, '123', 'rule', 'unrelated', 0.2, 'unknown', 'unclear', 'old', NULL, NULL, '2026-08-30 01:02:00'),
            (2, '123', 'final', 'reset_hint', 0.8, 'within_24h', 'implicit', 'secret-uid reason',
             'deepseek-v4-flash', 'tibo-classifier-v1', '2026-08-30 01:03:00');
        INSERT INTO radar_state VALUES
            (1, 'WATCH', 0.8, 'within_24h', '123', 'Public radar reason', '2026-08-30 01:04:00', NULL);
        INSERT INTO monitor_health VALUES
            ('backend', 'healthy', '2026-08-30 01:04:00');
        INSERT INTO alerts VALUES (1, 'must not be exported');
        INSERT INTO monitor_diagnostic_events VALUES (1, '{"tab_id": 42}');
        """
    )
    connection.commit()
    connection.close()


def test_public_export_uses_allow_list_and_redacts_known_secret(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "radar.db"
    create_mirror_fixture(database_path)
    monkeypatch.setenv("WXPUSHER_UID", "secret-uid")
    generated_at = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)

    snapshot = build_snapshot(database_path, generated_at=generated_at)
    tweet = snapshot["tweets"][0]

    assert snapshot["index"]["tweet_count"] == 1
    assert snapshot["radar"]["state"] == "WATCH"
    assert tweet["url"] == "https://x.com/thsottiaux/status/123"
    assert tweet["text"].endswith("[redacted]")
    assert tweet["classification"]["category"] == "reset_hint"
    assert "alerts" not in json.dumps(snapshot, ensure_ascii=False)
    assert "tab_id" not in json.dumps(snapshot, ensure_ascii=False)
    assert "must not be exported" not in json.dumps(snapshot, ensure_ascii=False)


def test_public_export_writes_only_contract_files(tmp_path) -> None:
    database_path = tmp_path / "radar.db"
    output_dir = tmp_path / "public-data"
    create_mirror_fixture(database_path)

    write_snapshot(build_snapshot(database_path), output_dir)

    assert sorted(path.name for path in output_dir.iterdir()) == [
        "health.json",
        "index.json",
        "radar.json",
        "tweets.json",
    ]
