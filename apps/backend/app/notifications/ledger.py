from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import NotificationResult


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class NotificationLedger:
    """Small local-only delivery ledger; separate from the product database."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS notification_deliveries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedup_key TEXT NOT NULL,
                channel TEXT NOT NULL,
                state TEXT NOT NULL,
                provider_message_id TEXT,
                detail TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(dedup_key, channel))"""
            )

    def reserve(self, dedup_key: str, channel: str) -> bool:
        self.initialize()
        now = _now()
        try:
            with sqlite3.connect(self.path) as connection:
                connection.execute(
                    """INSERT INTO notification_deliveries
                    (dedup_key,channel,state,detail,result_json,created_at,updated_at)
                    VALUES(?,?,?,'','{}',?,?)""",
                    (dedup_key, channel, "RESERVED", now, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def record(self, dedup_key: str, result: NotificationResult) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """UPDATE notification_deliveries
                SET state=?,provider_message_id=?,detail=?,result_json=?,updated_at=?
                WHERE dedup_key=? AND channel=?""",
                (
                    result.state.value,
                    result.provider_message_id,
                    result.detail,
                    json.dumps(result.as_dict(), ensure_ascii=False, default=str),
                    _now(),
                    dedup_key,
                    result.channel,
                ),
            )

    def recent(self, limit: int = 20) -> list[dict[str, object]]:
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT dedup_key,channel,state,provider_message_id,detail,created_at,updated_at
                FROM notification_deliveries ORDER BY id DESC LIMIT ?""",
                (max(1, min(100, limit)),),
            ).fetchall()
        return [dict(row) for row in rows]
