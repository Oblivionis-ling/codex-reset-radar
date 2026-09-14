from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


LOG_CATEGORIES = {"app", "collector", "errors", "llm", "notification"}
MAX_DAILY_SHARDS = 20


class RuntimeLog:
    """Small bounded JSONL logger for actionable V2 events only."""

    def __init__(self, directory: Path, retention_days: int = 5, max_bytes: int = 5_242_880) -> None:
        self.directory = directory
        self.retention_days = retention_days
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._last_prune_date: str | None = None

    def write(
        self,
        category: str,
        event: str,
        *,
        result: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if category not in LOG_CATEGORIES:
            raise ValueError(f"unsupported log category: {category}")
        now = datetime.now(UTC)
        record = {
            "timestamp": now.isoformat().replace("+00:00", "Z"),
            "event": event,
            "category": category,
            "result": result,
            "metadata": metadata or {},
        }
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._prune(now)
            path = self._select_path(category, now, len(encoded.encode("utf-8")))
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)

    def _select_path(self, category: str, now: datetime, incoming_bytes: int) -> Path:
        stem = f"{category}-{now:%Y-%m-%d}"
        base = self.directory / f"{stem}.jsonl"
        if not base.exists() or base.stat().st_size + incoming_bytes <= self.max_bytes:
            return base
        for shard in range(1, MAX_DAILY_SHARDS):
            candidate = self.directory / f"{stem}.{shard}.jsonl"
            if not candidate.exists() or candidate.stat().st_size + incoming_bytes <= self.max_bytes:
                return candidate

        # Cap a pathological single-category logging burst at twenty files per day.
        # Discard the oldest shard and shift the rest down before opening a fresh tail.
        base.unlink(missing_ok=True)
        for shard in range(1, MAX_DAILY_SHARDS):
            source = self.directory / f"{stem}.{shard}.jsonl"
            destination = base if shard == 1 else self.directory / f"{stem}.{shard - 1}.jsonl"
            if source.exists():
                source.replace(destination)
        return self.directory / f"{stem}.{MAX_DAILY_SHARDS - 1}.jsonl"

    def _prune(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self._last_prune_date == today:
            return
        cutoff = now - timedelta(days=self.retention_days)
        for path in self.directory.glob("*.jsonl"):
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                if modified < cutoff:
                    path.unlink()
            except OSError:
                continue
        self._last_prune_date = today
