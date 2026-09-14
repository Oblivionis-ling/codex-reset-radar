from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


ACTION_LEVELS = {"GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"}
EVENT_TYPES = {"FULL_RESET", "SPECIAL_RESET"}
SPECIAL_TYPES = {"PARTIAL", "BANKED", "RESET_CARD", "STAGED", "EXTRA_CREDIT", "OTHER"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalise_time(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tibo_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id TEXT NOT NULL UNIQUE,
    posted_at TEXT,
    text TEXT NOT NULL,
    url TEXT NOT NULL,
    is_reply INTEGER NOT NULL DEFAULT 0,
    reply_to_tweet_id TEXT,
    collected_at TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reset_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL CHECK(event_type IN ('FULL_RESET','SPECIAL_RESET')),
    special_type TEXT CHECK(special_type IS NULL OR special_type IN ('PARTIAL','BANKED','RESET_CARD','STAGED','EXTRA_CREDIT','OTHER')),
    occurred_at TEXT NOT NULL,
    source_post_id INTEGER REFERENCES tibo_posts(id),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK((event_type='FULL_RESET' AND special_type IS NULL) OR (event_type='SPECIAL_RESET' AND special_type IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS reset_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    opened_by_reset_event_id INTEGER NOT NULL REFERENCES reset_events(id),
    closed_by_reset_event_id INTEGER REFERENCES reset_events(id),
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_reset_cycles_open
ON reset_cycles((ended_at IS NULL)) WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS post_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES tibo_posts(id),
    analysis_type TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT NOT NULL,
    category TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS radar_judgements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    action_level TEXT NOT NULL CHECK(action_level IN ('GREEN','YELLOW','ORANGE','RED','UNKNOWN')),
    horizon_24h TEXT NOT NULL CHECK(horizon_24h IN ('GREEN','YELLOW','ORANGE','RED','UNKNOWN')),
    horizon_48h TEXT NOT NULL CHECK(horizon_48h IN ('GREEN','YELLOW','ORANGE','RED','UNKNOWN')),
    horizon_72h TEXT NOT NULL CHECK(horizon_72h IN ('GREEN','YELLOW','ORANGE','RED','UNKNOWN')),
    data_health TEXT NOT NULL,
    reason_summary TEXT NOT NULL,
    evidence_post_ids TEXT NOT NULL,
    special_event_ids TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_tibo_posts_posted_at ON tibo_posts(posted_at DESC);
CREATE INDEX IF NOT EXISTS ix_reset_events_occurred_at ON reset_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_post_analysis_post_id ON post_analysis(post_id);
CREATE INDEX IF NOT EXISTS ix_radar_judgements_created_at ON radar_judgements(created_at DESC);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA_SQL)
            connection.execute(
                "INSERT OR IGNORE INTO schema_versions(version, applied_at) VALUES(1, ?)",
                (utc_now(),),
            )

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("tibo_posts", "reset_events", "post_analysis", "radar_judgements")
            }

    def upsert_posts(self, posts: Iterable[dict[str, Any]]) -> int:
        changed = 0
        now = utc_now()
        with self.connect() as connection:
            for post in posts:
                before = connection.total_changes
                connection.execute(
                    """
                    INSERT INTO tibo_posts(
                        tweet_id, posted_at, text, url, is_reply, reply_to_tweet_id,
                        collected_at, source, created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(tweet_id) DO UPDATE SET
                        posted_at=COALESCE(excluded.posted_at, tibo_posts.posted_at),
                        text=excluded.text,
                        url=excluded.url,
                        is_reply=excluded.is_reply,
                        reply_to_tweet_id=COALESCE(excluded.reply_to_tweet_id, tibo_posts.reply_to_tweet_id),
                        collected_at=excluded.collected_at,
                        source=excluded.source
                    """,
                    (
                        str(post["tweet_id"]),
                        normalise_time(post.get("posted_at")),
                        str(post.get("text") or ""),
                        str(post.get("url") or f"https://x.com/thsottiaux/status/{post['tweet_id']}"),
                        1 if post.get("is_reply") else 0,
                        post.get("reply_to_tweet_id"),
                        normalise_time(post.get("collected_at")) or now,
                        str(post.get("source") or "collector_adapter"),
                        now,
                    ),
                )
                changed += int(connection.total_changes > before)
        return changed

    def list_posts(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tibo_posts ORDER BY COALESCE(posted_at, collected_at) DESC, id DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) | {"is_reply": bool(row["is_reply"])} for row in rows]

    def record_reset_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_type = str(event["event_type"]).upper()
        special_type = event.get("special_type")
        if event_type not in EVENT_TYPES:
            raise ValueError("invalid event_type")
        if event_type == "FULL_RESET" and special_type is not None:
            raise ValueError("FULL_RESET cannot have special_type")
        if event_type == "SPECIAL_RESET" and str(special_type).upper() not in SPECIAL_TYPES:
            raise ValueError("SPECIAL_RESET requires a valid special_type")
        special_type = str(special_type).upper() if special_type else None
        occurred_at = normalise_time(event["occurred_at"])
        created_at = utc_now()
        provenance = json.dumps(event.get("provenance") or {}, ensure_ascii=False, separators=(",", ":"))
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reset_events(event_type, special_type, occurred_at, source_post_id, title, summary, provenance, created_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    event_type,
                    special_type,
                    occurred_at,
                    event.get("source_post_id"),
                    event["title"],
                    event["summary"],
                    provenance,
                    created_at,
                ),
            )
            event_id = int(cursor.lastrowid)
            if event_type == "FULL_RESET":
                connection.execute(
                    "UPDATE reset_cycles SET ended_at=?, closed_by_reset_event_id=? WHERE ended_at IS NULL",
                    (occurred_at, event_id),
                )
                connection.execute(
                    "INSERT INTO reset_cycles(started_at, opened_by_reset_event_id, created_at) VALUES(?,?,?)",
                    (occurred_at, event_id, created_at),
                )
            row = connection.execute("SELECT * FROM reset_events WHERE id=?", (event_id,)).fetchone()
        return self._event(row)

    def list_reset_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reset_events ORDER BY occurred_at DESC, id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._event(row) for row in rows]

    def last_full_reset(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reset_events WHERE event_type='FULL_RESET' ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return self._event(row) if row else None

    def cycles(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM reset_cycles ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def add_judgement(self, judgement: dict[str, Any]) -> int:
        values = [
            str(judgement[key]).upper()
            for key in ("action_level", "horizon_24h", "horizon_48h", "horizon_72h")
        ]
        if any(value not in ACTION_LEVELS for value in values):
            raise ValueError("invalid action or horizon level")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO radar_judgements(
                    created_at, action_level, horizon_24h, horizon_48h, horizon_72h,
                    data_health, reason_summary, evidence_post_ids, special_event_ids,
                    model, prompt_version
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    normalise_time(judgement.get("created_at")) or utc_now(),
                    *values,
                    str(judgement.get("data_health") or "UNKNOWN"),
                    str(judgement["reason_summary"]),
                    json.dumps(judgement.get("evidence_post_ids") or []),
                    json.dumps(judgement.get("special_event_ids") or []),
                    judgement.get("model"),
                    str(judgement.get("prompt_version") or "v2-contract-alpha1"),
                ),
            )
            return int(cursor.lastrowid)

    def latest_judgement(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM radar_judgements ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["evidence_post_ids"] = json.loads(result.pop("evidence_post_ids"))
        result["special_event_ids"] = json.loads(result.pop("special_event_ids"))
        return result

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["provenance"] = json.loads(result["provenance"])
        result["display_tone"] = "PURPLE" if result["event_type"] == "SPECIAL_RESET" else "EVENT"
        return result


def next_reset_baseline(last_full_reset: dict[str, Any] | None) -> dict[str, Any]:
    if not last_full_reset:
        return {
            "status": "waiting_for_verified_history",
            "estimated_at": None,
            "basis": "No canonical FULL_RESET exists in the V2 database.",
        }
    occurred = datetime.fromisoformat(str(last_full_reset["occurred_at"]).replace("Z", "+00:00"))
    estimate = (occurred + timedelta(days=7)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "status": "baseline",
        "estimated_at": estimate,
        "basis": "Last canonical FULL_RESET + 7 days; not an intelligent judgement.",
    }
