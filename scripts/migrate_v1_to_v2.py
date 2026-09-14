from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db import Database  # noqa: E402


def _column(row: sqlite3.Row, columns: set[str], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in columns:
            return row[name]
    return default


def read_v1_posts(source: Path) -> list[dict[str, Any]]:
    uri = f"file:{source.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(tweets)")}
        if "tweet_id" not in columns or "text" not in columns:
            raise RuntimeError("V1 tweets table does not have the required columns")
        records = []
        for row in connection.execute("SELECT * FROM tweets ORDER BY tweet_id"):
            tweet_id = str(row["tweet_id"])
            records.append(
                {
                    "tweet_id": tweet_id,
                    "posted_at": _column(row, columns, "posted_at", "created_at"),
                    "text": str(row["text"] or ""),
                    "url": _column(
                        row,
                        columns,
                        "url",
                        default=f"https://x.com/thsottiaux/status/{tweet_id}",
                    ),
                    "is_reply": bool(_column(row, columns, "is_reply", default=False)),
                    "reply_to_tweet_id": _column(row, columns, "reply_to_tweet_id", "reply_to"),
                    "collected_at": _column(
                        row,
                        columns,
                        "collected_at",
                        "discovered_at",
                        "created_at",
                    ),
                    "source": "v1_migration",
                }
            )
        return records


def read_reset_candidates(source: Path) -> list[dict[str, Any]]:
    uri = f"file:{source.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "classifications" not in tables:
            return []
        rows = connection.execute(
            """
            SELECT tweet_id, category, reason, created_at
            FROM classifications
            WHERE classifier_type='final' AND category='reset_confirmed'
            ORDER BY created_at, id
            """
        ).fetchall()
    seen: set[str] = set()
    candidates = []
    for row in rows:
        tweet_id = str(row["tweet_id"])
        if tweet_id in seen:
            continue
        seen.add(tweet_id)
        candidates.append(
            {
                "tweet_id": tweet_id,
                "v1_category": row["category"],
                "v1_reason": row["reason"],
                "classified_at": row["created_at"],
                "migration_status": "REQUIRES_PROVENANCE_REVIEW",
            }
        )
    return candidates


def migrate(source: Path, target: Path, candidate_output: Path) -> dict[str, int]:
    if not source.exists():
        raise FileNotFoundError(source)
    posts = read_v1_posts(source)
    candidates = read_reset_candidates(source)
    database = Database(target)
    database.initialize()
    migrated = database.upsert_posts(posts)
    candidate_output.parent.mkdir(parents=True, exist_ok=True)
    candidate_output.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "source": str(source),
                "policy": "Candidates are not canonical reset_events until provenance is verified.",
                "candidates": candidates,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"posts_migrated": migrated, "reset_candidates": len(candidates)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate V1 posts into the isolated V2 core database")
    parser.add_argument("--source", type=Path, default=ROOT / "backend" / "data" / "radar.db")
    parser.add_argument("--target", type=Path, default=ROOT / "runtime" / "data" / "codex-reset-radar-v2.db")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=ROOT / "data" / "analysis" / "v1-reset-migration-candidates.json",
    )
    args = parser.parse_args()
    result = migrate(args.source.resolve(), args.target.resolve(), args.candidates.resolve())
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
