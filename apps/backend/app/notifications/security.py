from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_SECRET_KEYS = {"token", "apikey", "api_key", "apptoken", "sendkey", "password", "authorization"}
_TOKEN_PATHS = (
    re.compile(r"(https://sctapi\.ftqq\.com/)[^/?#]+(?=\.send)", re.IGNORECASE),
    re.compile(r"(https://iyuu\.cn/)[^/?#]+(?=\.send)", re.IGNORECASE),
    re.compile(r"(https://push\.showdoc\.com\.cn/server/api/push/)[^/?#]+", re.IGNORECASE),
    re.compile(r"(https://(?:www\.)?pushplus\.plus/send/)[^/?#]+", re.IGNORECASE),
)


def redact(value: str, secrets: Iterable[str] = ()) -> str:
    """Remove configured secrets and known token-in-path/query forms."""

    safe = str(value)
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        safe = safe.replace(secret, "***")
    for pattern in _TOKEN_PATHS:
        safe = pattern.sub(r"\1***", safe)
    try:
        parts = urlsplit(safe)
        if parts.query:
            query = [
                (key, "***" if key.lower() in _SECRET_KEYS else current)
                for key, current in parse_qsl(parts.query, keep_blank_values=True)
            ]
            safe = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except ValueError:
        pass
    return safe


def safe_detail(value: object, secrets: Iterable[str] = (), limit: int = 500) -> str:
    return " ".join(redact(str(value or ""), secrets).split())[:limit]
