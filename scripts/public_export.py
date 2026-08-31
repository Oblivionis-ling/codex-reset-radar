from __future__ import annotations

"""Build the intentionally small, public-safe data mirror.

This module reads SQLite in read-only mode and never writes to the live
database. It deliberately exports a narrow allow-list of public fields rather
than serializing ORM rows or API responses wholesale.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "backend" / "data" / "radar.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "public-data"
PUBLIC_COMPONENTS = ("backend", "profile_monitor", "replies_monitor", "search_backfill")
STATUS_URL_RE = re.compile(r"^https://x\.com/thsottiaux/status/(\d+)$", re.IGNORECASE)
KNOWN_SECRET_ENV_NAMES = ("DEEPSEEK_API_KEY", "WXPUSHER_APP_TOKEN", "WXPUSHER_UID")

try:
    BEIJING = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:  # Windows runtime may not bundle tzdata; China has no DST.
    BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")

if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.intelligence.forecast import build_forecast, build_reset_history, derive_usage_advice  # noqa: E402


def _configured_db_path() -> Path:
    configured = os.getenv("RADAR_DB_PATH", str(DEFAULT_DB_PATH))
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(" ", "T", 1) if "T" not in text else text
    if text.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", text):
        return text
    # SQLite timestamps in this project are UTC-naive values.
    return f"{text}Z"


def _parse_utc(value: Any) -> datetime | None:
    normalized = _iso(value)
    if normalized is None:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _redact_known_secrets(value: str) -> str:
    redacted = value
    for env_name in KNOWN_SECRET_ENV_NAMES:
        secret = os.getenv(env_name, "").strip()
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _public_url(tweet_id: str, stored_url: str | None) -> str:
    if stored_url and STATUS_URL_RE.fullmatch(stored_url.strip()):
        return stored_url.strip()
    return f"https://x.com/thsottiaux/status/{tweet_id}"


def _open_read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _rows(connection: sqlite3.Connection, query: str, parameters: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return connection.execute(query, tuple(parameters)).fetchall()


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def _latest_final_classifications(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    latest: dict[str, sqlite3.Row] = {}
    for row in _rows(
        connection,
        """
        SELECT tweet_id, category, confidence, urgency, explicitness, reason,
               model_name, prompt_version, created_at
        FROM classifications
        WHERE classifier_type = 'final'
        ORDER BY id DESC
        """,
    ):
        latest.setdefault(str(row["tweet_id"]), row)
    return latest


def _health_snapshot(connection: sqlite3.Connection, generated_at: datetime) -> dict[str, Any]:
    rows = {
        str(row["component"]): row
        for row in _rows(
            connection,
            """
            SELECT component, state, last_heartbeat
            FROM monitor_health
            WHERE component IN (?, ?, ?, ?)
            """,
            PUBLIC_COMPONENTS,
        )
    }
    components: list[dict[str, Any]] = []
    for component in PUBLIC_COMPONENTS:
        row = rows.get(component)
        if row is None:
            components.append({"component": component, "state": "unknown", "last_heartbeat": None})
            continue
        # Preserve the locally reported state. The Dashboard must combine
        # this state with snapshot freshness; an old snapshot cannot prove
        # that a monitor is offline right now.
        state = str(row["state"] or "unknown").strip().lower()
        if state not in {"healthy", "warning", "offline", "unknown"}:
            state = "unknown"
        components.append(
            {
                "component": component,
                "state": state,
                "last_heartbeat": _iso(row["last_heartbeat"]),
            }
        )
    return {"schema_version": 1, "generated_at": generated_at.isoformat().replace("+00:00", "Z"), "components": components}


def _reset_snapshot(
    connection: sqlite3.Connection,
    final_by_tweet: dict[str, sqlite3.Row],
    tweets_by_id: dict[str, dict[str, Any]],
    radar_state: str,
    generated_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    explicit: list[dict[str, Any]] = []
    if "reset_events" in _table_names(connection):
        explicit = [
            {
                "event_time": row["event_time"],
                "source": row["source"],
                "evidence_tweet_id": row["evidence_tweet_id"],
                "notes": row["notes"],
            }
            for row in _rows(
                connection,
                "SELECT event_time, source, evidence_tweet_id, notes FROM reset_events ORDER BY event_time DESC",
            )
        ]
    confirmed: list[dict[str, Any]] = []
    hints: list[dict[str, Any]] = []
    announcements: list[dict[str, Any]] = []
    for tweet_id, classification in final_by_tweet.items():
        tweet = tweets_by_id.get(tweet_id)
        if not tweet:
            continue
        item = {
            "event_time": tweet.get("created_at") or classification["created_at"],
            "evidence_tweet_id": tweet_id,
            "text": tweet.get("text") or "",
            "urgency": classification["urgency"],
        }
        category = str(classification["category"])
        if category == "reset_confirmed":
            confirmed.append(item)
        elif category == "reset_hint":
            hints.append(item)
        elif category == "reset_announcement":
            announcements.append(item)
    history = build_reset_history(explicit, confirmed)
    forecast = build_forecast(history, hints, announcements, now=generated_at)
    advice = derive_usage_advice(radar_state, forecast, now=generated_at)
    buckets = {"00–06": 0, "06–12": 0, "12–18": 0, "18–24": 0}
    for event in history:
        event_time = _parse_utc(event.get("event_time"))
        if not event_time:
            continue
        hour = event_time.astimezone(BEIJING).hour
        bucket = "00–06" if hour < 6 else "06–12" if hour < 12 else "12–18" if hour < 18 else "18–24"
        buckets[bucket] += 1
    resets = {
        "schema_version": 1,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "timezone": "Asia/Shanghai",
        "sample_count": len(history),
        "events": history,
        "time_distribution": buckets,
    }
    return forecast, {"forecast": forecast, "usage_advice": advice, "reset_history": resets}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def build_snapshot(database_path: Path, generated_at: datetime | None = None) -> dict[str, Any]:
    """Return the public mirror payload without exposing private tables/fields."""

    generated_at = generated_at or _now()
    generated_iso = generated_at.isoformat().replace("+00:00", "Z")
    connection = _open_read_only(database_path)
    try:
        final_by_tweet = _latest_final_classifications(connection)
        tweet_columns = _table_columns(connection, "tweets")
        translation_columns = [
            name
            for name in ("translated_zh", "translation_model", "translation_version", "translated_at")
            if name in tweet_columns
        ]
        translation_select = ", " + ", ".join(translation_columns) if translation_columns else ""
        sources_by_tweet: dict[str, list[str]] = {}
        for row in _rows(connection, "SELECT tweet_id, source FROM tweet_sources ORDER BY tweet_id, source"):
            sources_by_tweet.setdefault(str(row["tweet_id"]), []).append(str(row["source"]))

        tweets: list[dict[str, Any]] = []
        tweets_by_id: dict[str, dict[str, Any]] = {}
        for row in _rows(
            connection,
            f"""
            SELECT tweet_id, author, text, created_at, url, is_reply, reply_to, discovered_at{translation_select}
            FROM tweets
            ORDER BY discovered_at DESC, tweet_id DESC
            """,
        ):
            tweet_id = str(row["tweet_id"])
            classification = final_by_tweet.get(tweet_id)
            public_tweet: dict[str, Any] = {
                "tweet_id": tweet_id,
                "author": _redact_known_secrets(str(row["author"] or "")),
                "text": _redact_known_secrets(str(row["text"] or "")),
                "created_at": _iso(row["created_at"]),
                "url": _public_url(tweet_id, row["url"]),
                "is_reply": bool(row["is_reply"]),
                "reply_to": str(row["reply_to"]) if row["reply_to"] is not None else None,
                "discovered_at": _iso(row["discovered_at"]),
                "sources": sources_by_tweet.get(tweet_id, []),
                "translation_zh": _redact_known_secrets(str(row["translated_zh"]))
                if "translated_zh" in tweet_columns and row["translated_zh"]
                else None,
                "translation_model": str(row["translation_model"]) if "translation_model" in tweet_columns and row["translation_model"] else None,
                "translation_version": str(row["translation_version"])
                if "translation_version" in tweet_columns and row["translation_version"]
                else None,
                "translated_at": _iso(row["translated_at"])
                if "translated_at" in tweet_columns
                else None,
                "classification": None,
            }
            if classification is not None:
                public_tweet["classification"] = {
                    "category": str(classification["category"]),
                    "confidence": classification["confidence"],
                    "urgency": str(classification["urgency"] or "unknown"),
                    "explicitness": str(classification["explicitness"] or "unclear"),
                    "reason": _redact_known_secrets(str(classification["reason"] or "")),
                    "model_name": str(classification["model_name"]) if classification["model_name"] else None,
                    "prompt_version": str(classification["prompt_version"]) if classification["prompt_version"] else None,
                    "classified_at": _iso(classification["created_at"]),
                }
            tweets.append(public_tweet)
            tweets_by_id[tweet_id] = public_tweet

        radar_row = connection.execute(
            """
            SELECT state, confidence, urgency, trigger_tweet_id, reason, updated_at, expires_at
            FROM radar_state
            WHERE id = 1
            """
        ).fetchone()
        radar = {
            "schema_version": 1,
            "generated_at": generated_iso,
            "state": str(radar_row["state"]) if radar_row else "QUIET",
            "confidence": radar_row["confidence"] if radar_row else 0.0,
            "urgency": str(radar_row["urgency"]) if radar_row else "unknown",
            "trigger_tweet_id": str(radar_row["trigger_tweet_id"]) if radar_row and radar_row["trigger_tweet_id"] else None,
            "reason": _redact_known_secrets(str(radar_row["reason"])) if radar_row else "No active reset signal.",
            "updated_at": _iso(radar_row["updated_at"]) if radar_row else None,
            "expires_at": _iso(radar_row["expires_at"]) if radar_row else None,
        }
        health = _health_snapshot(connection, generated_at)
        forecast, derived = _reset_snapshot(connection, final_by_tweet, tweets_by_id, radar["state"], generated_at)
        radar.update({"forecast": forecast, "usage_advice": derived["usage_advice"]})
        resets = derived["reset_history"]
    finally:
        connection.close()

    categories: dict[str, int] = {}
    for tweet in tweets:
        classification = tweet["classification"]
        if classification:
            category = str(classification["category"])
            categories[category] = categories.get(category, 0) + 1
    index = {
        "schema_version": 1,
        "generated_at": generated_iso,
        "source": "@thsottiaux",
        "tweet_count": len(tweets),
        "classified_tweet_count": sum(categories.values()),
        "category_counts": dict(sorted(categories.items())),
        "files": ["health.json", "radar.json", "resets.json", "tweets.json"],
    }
    return {"index": index, "radar": radar, "tweets": tweets, "health": health, "resets": resets}


def write_snapshot(snapshot: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "index.json": snapshot["index"],
        "radar.json": snapshot["radar"],
        "tweets.json": snapshot["tweets"],
        "health.json": snapshot["health"],
        "resets.json": snapshot["resets"],
    }
    for filename, payload in payloads.items():
        target = output_dir / filename
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export sanitized Codex Reset Radar data")
    parser.add_argument("--db", type=Path, default=_configured_db_path())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    snapshot = build_snapshot(args.db)
    write_snapshot(snapshot, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "tweet_count": snapshot["index"]["tweet_count"],
                "classified_tweet_count": snapshot["index"]["classified_tweet_count"],
                "radar_state": snapshot["radar"]["state"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
