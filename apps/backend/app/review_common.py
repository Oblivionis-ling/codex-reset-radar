from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from .corpus_standard import canonical_json_bytes


def canonical_bytes(value: Any) -> bytes:
    """Canonical UTF-8 JSONL record bytes: sorted keys and exactly one LF."""
    return canonical_json_bytes(value, trailing_newline=True)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def utc_text(value: str | datetime | None = None) -> str:
    """Return a timezone-aware UTC timestamp. None means the actual current time."""
    if value is None:
        current = datetime.now(UTC)
    elif isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")
