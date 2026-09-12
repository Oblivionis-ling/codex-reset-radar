from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


logger = logging.getLogger("radar.notifications.wxpusher")


@dataclass(frozen=True)
class WxPusherSendResult:
    """The provider/API result; it does not claim that WeChat displayed it."""

    http_status: int
    response_code: int | str | None
    message: str | None
    send_record_id: int | str | None
    duration_ms: int


@dataclass(frozen=True)
class WxPusherDeliveryStatus:
    """Status returned by WxPusher for one recipient delivery record."""

    http_status: int
    response_code: int | str | None
    message: str | None
    status: str | int | None
    send_record_id: int | str | None
    duration_ms: int


class WxPusherError(RuntimeError):
    """Raised when WxPusher rejects or cannot receive a notification."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "unknown",
        http_status: int | None = None,
        response_code: int | str | None = None,
        response_message: str | None = None,
        send_record_id: int | str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.http_status = http_status
        self.response_code = response_code
        self.response_message = response_message
        self.send_record_id = send_record_id
        self.duration_ms = duration_ms


class WxPusherNotifier:
    endpoint = "https://wxpusher.zjiecode.com/api/send/message"
    status_endpoint = "https://wxpusher.zjiecode.com/api/send/query/status"

    def __init__(self, app_token: str, uid: str, *, timeout: float = 8.0, endpoint: str | None = None):
        self.app_token = app_token
        self.uid = uid
        self.timeout = timeout
        self.endpoint = endpoint or self.endpoint
        logger.info(
            "WXPUSHER_PROVIDER_INITIALIZED endpoint=%s app_token_configured=%s "
            "recipient_configured=%s uid_length=%s timeout_seconds=%s",
            self.endpoint,
            bool(self.app_token),
            bool(self.uid),
            len(self.uid),
            self.timeout,
        )

    def send(self, title: str, content: str) -> WxPusherSendResult:
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
        started = time.perf_counter()
        logger.info(
            "WXPUSHER_REQUEST_STARTED endpoint=%s content_length=%s summary_length=%s recipient_configured=%s",
            self.endpoint,
            len(content),
            len(title[:100]),
            bool(self.uid),
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                raw = response.read()
        except HTTPError as exc:
            duration_ms = self._duration_ms(started)
            raw = self._read_error_body(exc)
            response_code, response_message, send_record_id = self._response_fields(raw)
            self._log_failed(
                error_type="http_error",
                http_status=exc.code,
                response_code=response_code,
                response_message=response_message,
                send_record_id=send_record_id,
                duration_ms=duration_ms,
            )
            raise WxPusherError(
                f"HTTP status {exc.code}",
                error_type="http_error",
                http_status=exc.code,
                response_code=response_code,
                response_message=response_message,
                send_record_id=send_record_id,
                duration_ms=duration_ms,
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            duration_ms = self._duration_ms(started)
            error_type = self._connection_error_type(exc)
            self._log_failed(error_type=error_type, duration_ms=duration_ms, error=str(exc))
            raise WxPusherError(
                f"connection error: {exc.__class__.__name__}",
                error_type=error_type,
                duration_ms=duration_ms,
            ) from exc

        duration_ms = self._duration_ms(started)
        response_code, response_message, send_record_id = self._response_fields(raw)
        if not 200 <= status < 300:
            self._log_failed(
                error_type="http_error",
                http_status=status,
                response_code=response_code,
                response_message=response_message,
                send_record_id=send_record_id,
                duration_ms=duration_ms,
            )
            raise WxPusherError(
                f"HTTP status {status}",
                error_type="http_error",
                http_status=status,
                response_code=response_code,
                response_message=response_message,
                send_record_id=send_record_id,
                duration_ms=duration_ms,
            )
        if response_code is None:
            self._log_failed(error_type="invalid_json", http_status=status, duration_ms=duration_ms)
            raise WxPusherError("invalid JSON response", error_type="invalid_json", http_status=status, duration_ms=duration_ms)
        if response_code != 1000:
            self._log_failed(
                error_type="api_error",
                http_status=status,
                response_code=response_code,
                response_message=response_message,
                send_record_id=send_record_id,
                duration_ms=duration_ms,
            )
            raise WxPusherError(
                response_message or "WxPusher API error",
                error_type="api_error",
                http_status=status,
                response_code=response_code,
                response_message=response_message,
                send_record_id=send_record_id,
                duration_ms=duration_ms,
            )
        result = WxPusherSendResult(
            http_status=status,
            response_code=response_code,
            message=response_message,
            send_record_id=send_record_id,
            duration_ms=duration_ms,
        )
        logger.info(
            "WXPUSHER_REQUEST_SUCCESS http_status=%s response_code=%s send_record_id=%s duration_ms=%s "
            "delivery_status=accepted_async",
            status,
            response_code,
            send_record_id if send_record_id is not None else "-",
            duration_ms,
        )
        return result

    def query_status(self, send_record_id: int | str) -> WxPusherDeliveryStatus:
        """Query the current WxPusher status for one send record."""
        query = urlencode({"sendRecordId": str(send_record_id)})
        endpoint = f"{self.status_endpoint}?{query}"
        request = Request(endpoint, headers={"Accept": "application/json"}, method="GET")
        started = time.perf_counter()
        logger.info("WXPUSHER_STATUS_QUERY_STARTED endpoint=%s send_record_id=%s", endpoint, send_record_id)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                raw = response.read()
        except HTTPError as exc:
            duration_ms = self._duration_ms(started)
            raw = self._read_error_body(exc)
            response_code, response_message, _ = self._response_fields(raw)
            self._log_status_failed(exc.code, response_code, response_message, duration_ms)
            raise WxPusherError(
                f"HTTP status {exc.code}",
                error_type="http_error",
                http_status=exc.code,
                response_code=response_code,
                response_message=response_message,
                duration_ms=duration_ms,
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            duration_ms = self._duration_ms(started)
            error_type = self._connection_error_type(exc)
            logger.warning(
                "WXPUSHER_STATUS_QUERY_FAILED http_status=- response_code=- error_type=%s duration_ms=%s error=%s",
                error_type,
                duration_ms,
                self._safe_text(str(exc)),
            )
            raise WxPusherError(
                f"connection error: {exc.__class__.__name__}",
                error_type=error_type,
                duration_ms=duration_ms,
            ) from exc

        duration_ms = self._duration_ms(started)
        response_code, response_message, _ = self._response_fields(raw)
        result = self._decode_json(raw)
        delivery_status = self._status_field(result)
        if not 200 <= status < 300 or response_code != 1000:
            self._log_status_failed(status, response_code, response_message, duration_ms)
            raise WxPusherError(
                response_message or f"WxPusher status query failed (HTTP {status})",
                error_type="api_error" if 200 <= status < 300 else "http_error",
                http_status=status,
                response_code=response_code,
                response_message=response_message,
                duration_ms=duration_ms,
            )
        logger.info(
            "WXPUSHER_STATUS_QUERY_SUCCESS http_status=%s response_code=%s send_record_id=%s status=%s duration_ms=%s",
            status,
            response_code,
            send_record_id,
            delivery_status if delivery_status is not None else "-",
            duration_ms,
        )
        return WxPusherDeliveryStatus(
            http_status=status,
            response_code=response_code,
            message=response_message,
            status=delivery_status,
            send_record_id=send_record_id,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _duration_ms(started: float) -> int:
        return int(round((time.perf_counter() - started) * 1000))

    @staticmethod
    def _read_error_body(error: HTTPError) -> bytes:
        try:
            return error.read()
        except (OSError, ValueError):
            return b""

    @classmethod
    def _decode_json(cls, raw: bytes) -> dict:
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WxPusherError("invalid JSON response", error_type="invalid_json") from exc
        if not isinstance(result, dict):
            raise WxPusherError("invalid JSON response", error_type="invalid_json")
        return result

    @classmethod
    def _response_fields(cls, raw: bytes) -> tuple[int | str | None, str | None, int | str | None]:
        try:
            result = cls._decode_json(raw)
        except WxPusherError:
            return None, None, None
        response_code = result.get("code")
        response_message = result.get("msg")
        send_record_id = result.get("sendRecordId")
        data = result.get("data")
        targets = data if isinstance(data, list) else [data]
        for target in targets:
            if isinstance(target, dict):
                if send_record_id is None:
                    send_record_id = target.get("sendRecordId")
                if response_message is None:
                    response_message = target.get("msg") or target.get("message")
                if response_code is None:
                    response_code = target.get("code")
                if send_record_id is not None:
                    break
        return response_code, str(response_message) if response_message is not None else None, send_record_id

    @staticmethod
    def _status_field(result: dict) -> str | int | None:
        data = result.get("data")
        if isinstance(data, dict):
            value = data.get("status")
            return value if isinstance(value, (str, int)) else None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            value = data[0].get("status")
            return value if isinstance(value, (str, int)) else None
        if isinstance(data, (str, int)):
            return data
        value = result.get("status")
        return value if isinstance(value, (str, int)) else None

    @staticmethod
    def _connection_error_type(error: Exception) -> str:
        text = str(error).lower()
        if isinstance(error, TimeoutError) or "timed out" in text or "timeout" in text:
            return "timeout"
        if "reset" in text or "connection aborted" in text:
            return "connection_reset"
        if "name or service not known" in text or "nodename" in text or "getaddrinfo" in text:
            return "dns_error"
        return "connect_error"

    @classmethod
    def _safe_text(cls, value: str | None) -> str:
        return " ".join(str(value or "").split())[:500]

    def _log_failed(self, *, error_type: str, duration_ms: int, http_status: int | None = None,
                    response_code: int | str | None = None, response_message: str | None = None,
                    send_record_id: int | str | None = None, error: str | None = None) -> None:
        logger.warning(
            "WXPUSHER_REQUEST_FAILED http_status=%s response_code=%s send_record_id=%s error_type=%s "
            "duration_ms=%s message=%s",
            http_status if http_status is not None else "-",
            response_code if response_code is not None else "-",
            send_record_id if send_record_id is not None else "-",
            error_type,
            duration_ms,
            self._safe_text(response_message or error) or "-",
        )

    @staticmethod
    def _log_status_failed(http_status: int, response_code: int | str | None,
                           response_message: str | None, duration_ms: int) -> None:
        logger.warning(
            "WXPUSHER_STATUS_QUERY_FAILED http_status=%s response_code=%s error_type=%s duration_ms=%s message=%s",
            http_status,
            response_code if response_code is not None else "-",
            "api_error" if 200 <= http_status < 300 else "http_error",
            duration_ms,
            WxPusherNotifier._safe_text(response_message) or "-",
        )
