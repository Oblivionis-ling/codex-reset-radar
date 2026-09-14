from __future__ import annotations

import sqlite3

from app.db import Database
from scripts.migrate_v1_to_v2 import migrate


def test_migration_deduplicates_posts_and_only_emits_reset_candidates(tmp_path):
    source = tmp_path / "v1.db"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            CREATE TABLE tweets (
                tweet_id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                created_at TEXT,
                url TEXT,
                is_reply INTEGER,
                reply_to TEXT,
                discovered_at TEXT,
                source TEXT
            );
            CREATE TABLE classifications (
                id INTEGER PRIMARY KEY,
                tweet_id TEXT,
                classifier_type TEXT,
                category TEXT,
                reason TEXT,
                created_at TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO tweets VALUES(?,?,?,?,?,?,?,?)",
            (
                "fixture-post-1",
                "Synthetic migration fixture; not a real Tibo post.",
                "2026-09-01T00:00:00Z",
                "https://example.invalid/fixture-post-1",
                0,
                None,
                "2026-09-01T00:01:00Z",
                "test_fixture",
            ),
        )
        connection.execute(
            "INSERT INTO classifications VALUES(1,?,?,?,?,?)",
            (
                "fixture-post-1",
                "final",
                "reset_confirmed",
                "Synthetic candidate only.",
                "2026-09-01T00:02:00Z",
            ),
        )

    target = tmp_path / "v2.db"
    candidates = tmp_path / "candidates.json"
    result = migrate(source, target, candidates)
    database = Database(target)

    assert result["posts_migrated"] == 1
    assert result["reset_candidates"] == 1
    assert database.counts()["tibo_posts"] == 1
    assert database.counts()["reset_events"] == 0
    assert candidates.exists()
