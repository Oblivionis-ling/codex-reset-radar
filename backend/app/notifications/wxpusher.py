from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class WxPusherError(RuntimeError):
    """Raised when WxPusher rejects or cannot receive a notification."""


class WxPusherNotifier:
    endpoint = "https://wxpusher.zjiecode.com/api/send/message"

    def __init__(self, app_token: str, uid: str, *, timeout: float = 8.0, endpoint: str | None = None):
        self.app_token = app_token
        self.uid = uid
        self.timeout = timeout
        self.endpoint = endpoint or self.endpoint

    def send(self, title: str, content: str) -> None:
        payload = {
            "appToken": self.app_token,
            "content": content,
            "summary": title[:100],
            "contentType": 1,
            "uids": [self.uid],
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", response.getcode())
                raw = response.read()
        except HTTPError as exc:
            raise WxPusherError(f"HTTP status {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise WxPusherError(f"connection error: {exc.__class__.__name__}") from exc

        if not 200 <= status < 300:
            raise WxPusherError(f"HTTP status {status}")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WxPusherError("invalid JSON response") from exc
        if not isinstance(result, dict) or result.get("code") != 1000:
            raise WxPusherError("WxPusher API error")
