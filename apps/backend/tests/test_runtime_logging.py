from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from app.logging_runtime import MAX_DAILY_SHARDS, RuntimeLog


def test_runtime_log_is_valid_jsonl_and_bounds_daily_shards(tmp_path):
    runtime_log = RuntimeLog(tmp_path, retention_days=5, max_bytes=220)
    for sequence in range(80):
        runtime_log.write(
            "collector",
            "SYNTHETIC_LOG_FIXTURE",
            metadata={"sequence": sequence, "fixture": "x" * 40},
        )

    paths = sorted(tmp_path.glob("collector-*.jsonl"))
    assert len(paths) <= MAX_DAILY_SHARDS
    assert all(path.stat().st_size < 440 for path in paths)
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert json.loads(line)["event"] == "SYNTHETIC_LOG_FIXTURE"


def test_runtime_log_prunes_files_older_than_retention(tmp_path):
    old = tmp_path / "app-2000-01-01.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    old_time = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    os.utime(old, (old_time, old_time))

    RuntimeLog(tmp_path, retention_days=5).write("app", "SYNTHETIC_CURRENT_FIXTURE")

    assert not old.exists()
