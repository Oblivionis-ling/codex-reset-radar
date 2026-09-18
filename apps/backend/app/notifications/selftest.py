from __future__ import annotations

import httpx

from .adapters import (
    IyuuAdapter,
    PushPlusAdapter,
    ServerChanAdapter,
    ShowDocAdapter,
    WPushAdapter,
    WxPusherAdapter,
)
from .email import SmtpEmailAdapter
from .models import DeliveryState, NotificationMessage
from .transport import HttpTransport


class _FakeSmtp:
    messages: list[object] = []

    def __init__(self, *_: object, **__: object) -> None:
        self.closed = False

    def ehlo(self) -> None:
        pass

    def starttls(self, **_: object) -> None:
        pass

    def login(self, *_: object) -> None:
        pass

    def send_message(self, message: object) -> None:
        self.messages.append(message)

    def quit(self) -> None:
        self.closed = True


async def run_offline_selftest() -> dict[str, str]:
    """Exercise every adapter against in-memory transports only."""

    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if host == "www.pushplus.plus":
            return httpx.Response(200, json={"code": 200, "msg": "accepted", "data": "pp-1"})
        if host == "sctapi.ftqq.com":
            return httpx.Response(200, json={"code": 0, "message": "success", "data": {"pushid": "sc-1"}})
        if host == "iyuu.cn":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "data": []})
        if host == "api.wpush.cn" and path.endswith("/send"):
            return httpx.Response(200, json={"code": 0, "message": "success", "data": "wp-1", "success": True})
        if host == "api.wpush.cn" and path.endswith("/query"):
            return httpx.Response(200, json={"code": 0, "message": "success", "data": {"status": 1}, "success": True})
        if host == "wxpusher.zjiecode.com" and path.endswith("/message"):
            return httpx.Response(200, json={"code": 1000, "msg": "ok", "data": [{"sendRecordId": 41, "status": "PENDING"}]})
        if host == "wxpusher.zjiecode.com" and path.endswith("/status"):
            return httpx.Response(200, json={"code": 1000, "msg": "ok", "data": {"status": "SUCCESS"}})
        if host == "push.showdoc.com.cn":
            return httpx.Response(200, json={"error_code": 0, "error_message": "ok", "data": {}})
        raise AssertionError(f"offline selftest blocked unexpected target: {request.url}")

    message = NotificationMessage.test_message()
    statuses: dict[str, str] = {}
    mock = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=mock) as client:
        transport = HttpTransport(network_enabled=True, retries=1, client=client)
        adapters = [
            PushPlusAdapter(transport, "pp_test"),
            PushPlusAdapter(transport, "pp_test", channel_name="clawbot", channel="pushplus_clawbot"),
            ServerChanAdapter(transport, "SCT_test"),
            IyuuAdapter(transport, "IYUU_test"),
            WPushAdapter(transport, "WPUSH_test"),
            WPushAdapter(transport, "WPUSH_test", channel_name="clawbot", channel="wpush_clawbot"),
            WxPusherAdapter(transport, "AT_test", "UID_test"),
            ShowDocAdapter(transport, "showdoc_test"),
        ]
        for adapter in adapters:
            result = await adapter.send(message)
            if result.state == DeliveryState.PENDING and hasattr(adapter, "query"):
                result = await adapter.query(result.provider_message_id or "missing")
            if result.state not in {DeliveryState.ACCEPTED, DeliveryState.PENDING, DeliveryState.SUCCEEDED}:
                raise AssertionError(f"{adapter.channel} offline result was {result.state}")
            statuses[adapter.channel] = DeliveryState.OFFLINE_PASS.value

    smtp = SmtpEmailAdapter(
        host="smtp.invalid",
        port=587,
        username="test-user",
        password="test-password",
        sender="sender@example.invalid",
        recipient="recipient@example.invalid",
        network_enabled=True,
        smtp_factory=_FakeSmtp,
    )
    email_result = await smtp.send(message)
    if email_result.state != DeliveryState.ACCEPTED:
        raise AssertionError("SMTP offline fixture failed")
    statuses[smtp.channel] = DeliveryState.OFFLINE_PASS.value
    return statuses
