from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.corpus_standard import (  # noqa: E402
    apply_content_policy_records,
    read_jsonl,
    validate_content_policy_record,
)
from app.db import Database  # noqa: E402


def inspect(database_path: Path, records: list[dict[str, object]]) -> list[dict[str, object]]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        results = []
        for record in records:
            validate_content_policy_record(record)
            row = connection.execute(
                "SELECT id,text_hash FROM tibo_posts WHERE tweet_id=?",
                (str(record["tweet_id"]),),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown content-policy tweet ID: {record['tweet_id']}")
            results.append({
                "tweet_id": str(record["tweet_id"]),
                "content_hash": str(record["content_hash"]),
                "current_content_hash": str(row["text_hash"]),
                "applies_to_current_content": str(record["content_hash"]) == str(row["text_hash"]),
            })
        return results
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply content-version-scoped review policies without deleting archived data."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--policies", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    database_path = args.database.resolve()
    policy_path = args.policies.resolve()
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    records = list(read_jsonl(policy_path))
    inspected = inspect(database_path, records)
    if not all(item["applies_to_current_content"] for item in inspected):
        raise ValueError("one or more content policies do not match the current content version")

    if args.apply:
        database = Database(database_path)
        database.initialize()
        applied = apply_content_policy_records(database, records)
    else:
        applied = inspected

    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run",
        "database": str(database_path),
        "policies": str(policy_path),
        "records": len(records),
        "all_current_versions_match": True,
        "results": applied,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
