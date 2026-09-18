from __future__ import annotations

import asyncio
import json
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import parse_qs

import httpx

from app.notifications.adapters import (
    IyuuAdapter,
    PushPlusAdapter,
    ServerChanAdapter,
    ShowDocAdapter,
    WPushAdapter,
    WxPusherAdapter,
)
from app.notifications.config import NotificationSettings
from app.notifications.email import SmtpEmailAdapter
from app.notifications.ledger import NotificationLedger
from app.notifications.models import DeliveryState, NotificationMessage, NotificationResult
from app.notifications.registry import missing_configuration
from app.notifications.security import redact
from app.notifications.selftest import run_offline_selftest
from app.notifications.service import NotificationDispatcher
from app.notifications.transport import HttpTransport, NetworkDisabledError


def run(coro):
    return asyncio.run(coro)


def transport(handler, *, retries=0):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpTransport(network_enabled=True, retries=retries, client=client), client


def test_offline_selftest_covers_every_prepared_channel():
    result = run(run_offline_selftest())
    assert set(result) == {
        "pushplus_wechat", "pushplus_clawbot", "serverchan_wechat", "iyuu_wechat",
        "wpush_wechat", "wpush_clawbot", "wxpusher", "showdoc_wechat", "smtp_email",
    }
    assert set(result.values()) == {"OFFLINE_PASS"}


def test_pushplus_request_and_async_result_do_not_claim_delivery():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"code": 200, "msg": "ok", "data": "message-1"})

    current, client = transport(handler)
    try:
        result = run(PushPlusAdapter(current, "secret", channel_name="clawbot", channel="pushplus_clawbot").send(NotificationMessage.test_message()))
    finally:
        run(client.aclose())
    assert seen["channel"] == "clawbot"
    assert seen["template"] == "txt"
    assert result.state == DeliveryState.PENDING
    assert result.request_accepted is True
    assert result.user_observation_required is True


def test_serverchan_iyuu_showdoc_use_documented_form_contracts():
    calls = []

    def handler(request: httpx.Request):
        calls.append((str(request.url), parse_qs(request.content.decode())))
        if request.url.host == "sctapi.ftqq.com":
            return httpx.Response(200, json={"code": 0, "message": "success", "data": {"pushid": "1"}})
        if request.url.host == "iyuu.cn":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "data": []})
        return httpx.Response(200, json={"error_code": 0, "error_message": "ok"})

    current, client = transport(handler)
    try:
        message = NotificationMessage.test_message()
        results = run(_send_all([
            ServerChanAdapter(current, "SCT_secret"),
            IyuuAdapter(current, "IYUU_secret"),
            ShowDocAdapter(current, "showdoc_secret"),
        ], message))
    finally:
        run(client.aclose())
    assert all(result.state == DeliveryState.ACCEPTED for result in results)
    assert calls[0][0].endswith("/SCT_secret.send") and set(calls[0][1]) == {"title", "desp"}
    assert calls[1][0].endswith("/IYUU_secret.send") and set(calls[1][1]) == {"text", "desp"}
    assert calls[2][0].endswith("/server/api/push/showdoc_secret") and set(calls[2][1]) == {"title", "content"}


async def _send_all(adapters, message):
    return [await adapter.send(message) for adapter in adapters]


def test_http_200_business_failure_is_failure():
    def handler(_: httpx.Request):
        return httpx.Response(200, json={"code": 999, "msg": "rejected"})

    current, client = transport(handler)
    try:
        result = run(PushPlusAdapter(current, "secret").send(NotificationMessage.test_message()))
    finally:
        run(client.aclose())
    assert result.state == DeliveryState.FAILED
    assert result.request_accepted is False


def test_wpush_send_and_status_distinguish_pending_success_failure_unknown():
    status = {"value": 0}

    def handler(request: httpx.Request):
        if request.url.path.endswith("/send"):
            return httpx.Response(200, json={"code": 0, "success": True, "data": "42"})
        return httpx.Response(200, json={"code": 0, "success": True, "data": {"status": status["value"]}})

    current, client = transport(handler)
    adapter = WPushAdapter(current, "WPUSH_secret")
    try:
        sent = run(adapter.send(NotificationMessage.test_message()))
        assert sent.state == DeliveryState.PENDING and sent.provider_message_id == "42"
        expected = {0: DeliveryState.PENDING, 1: DeliveryState.SUCCEEDED, 2: DeliveryState.FAILED, 9: DeliveryState.UNKNOWN}
        for value, state in expected.items():
            status["value"] = value
            assert run(adapter.query("42")).state == state
    finally:
        run(client.aclose())


def test_wxpusher_uses_current_send_and_query_contract():
    paths = []

    def handler(request: httpx.Request):
        paths.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/message"):
            payload = json.loads(request.content)
            assert payload["appToken"] == "AT_secret"
            assert payload["uids"] == ["UID_secret"]
            return httpx.Response(200, json={"code": 1000, "data": [{"sendRecordId": 7, "status": "PENDING"}]})
        return httpx.Response(200, json={"code": 1000, "data": {"status": "SUCCESS"}})

    current, client = transport(handler)
    adapter = WxPusherAdapter(current, "AT_secret", "UID_secret")
    try:
        sent = run(adapter.send(NotificationMessage.test_message()))
        queried = run(adapter.query(sent.provider_message_id or ""))
    finally:
        run(client.aclose())
    assert queried.state == DeliveryState.SUCCEEDED
    assert paths[-1] == ("/api/send/query/status", {"sendRecordId": "7"})


def test_network_is_blocked_by_default_even_with_real_looking_credentials():
    called = False

    def handler(_: httpx.Request):
        nonlocal called
        called = True
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    current = HttpTransport(client=client)
    try:
        try:
            run(PushPlusAdapter(current, "real-looking-token").send(NotificationMessage.test_message()))
            raise AssertionError("network guard did not raise")
        except NetworkDisabledError:
            pass
    finally:
        run(client.aclose())
    assert called is False


def test_transport_has_one_bounded_retry_owner():
    calls = 0

    def handler(_: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="temporary")
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    async def no_sleep(_: float):
        pass

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    current = HttpTransport(network_enabled=True, retries=1, client=client, sleep=no_sleep)
    try:
        result = run(IyuuAdapter(current, "token").send(NotificationMessage.test_message()))
    finally:
        run(client.aclose())
    assert result.attempts == 2
    assert calls == 2


def test_tokens_are_redacted_from_paths_queries_and_plain_text():
    value = (
        "https://sctapi.ftqq.com/SCT_secret.send?token=abc "
        "https://iyuu.cn/IYUU_secret.send "
        "https://push.showdoc.com.cn/server/api/push/showdoc_secret WPUSH_secret"
    )
    safe = redact(value, ("WPUSH_secret",))
    for secret in ("SCT_secret", "IYUU_secret", "showdoc_secret", "WPUSH_secret", "abc"):
        assert secret not in safe


def test_missing_notification_configuration_does_not_change_backend_settings(settings):
    assert settings.host == "127.0.0.1"
    empty = NotificationSettings()
    assert missing_configuration("pushplus_wechat", empty) == ["PUSHPLUS_TOKEN"]
    assert "CRR_SMTP_PASSWORD" in missing_configuration("smtp_email", empty)


class FakeSmtp:
    error = None
    last_message: EmailMessage | None = None
    quit_called = False

    def __init__(self, *_args, **_kwargs):
        type(self).quit_called = False

    def ehlo(self):
        pass

    def starttls(self, **_kwargs):
        if isinstance(self.error, ssl.SSLError):
            raise self.error

    def login(self, *_args):
        if isinstance(self.error, smtplib.SMTPAuthenticationError):
            raise self.error

    def send_message(self, message):
        if self.error is not None:
            raise self.error
        type(self).last_message = message

    def quit(self):
        type(self).quit_called = True


def smtp_adapter(error=None):
    FakeSmtp.error = error
    return SmtpEmailAdapter(
        "smtp.example.invalid", 587, "user", "password", "from@example.invalid", "to@example.invalid",
        network_enabled=True, smtp_factory=FakeSmtp,
    )


def test_smtp_builds_chinese_message_with_verified_tls_and_closes():
    result = run(smtp_adapter().send(NotificationMessage.test_message()))
    assert result.state == DeliveryState.ACCEPTED
    assert FakeSmtp.last_message is not None
    assert str(FakeSmtp.last_message["Subject"]) == "测试，非真实 Reset 预警"
    assert FakeSmtp.quit_called is True


def test_smtp_failure_classes_are_explicit_and_close_resources():
    failures = [
        smtplib.SMTPAuthenticationError(535, b"bad auth"),
        smtplib.SMTPRecipientsRefused({"to@example.invalid": (550, b"refused")}),
        ssl.SSLError("certificate verify failed"),
        TimeoutError("timed out"),
    ]
    for error in failures:
        result = run(smtp_adapter(error).send(NotificationMessage.test_message()))
        assert result.state == DeliveryState.FAILED
        assert FakeSmtp.quit_called is True


class StubAdapter:
    def __init__(self, channel, state, calls):
        self.channel = channel
        self.state = state
        self.calls = calls

    async def send(self, _message):
        self.calls.append(self.channel)
        return NotificationResult(self.channel, self.state, self.state != DeliveryState.FAILED)


def test_failure_and_unknown_each_queue_exactly_one_email_fallback(tmp_path):
    for primary_state in (DeliveryState.FAILED, DeliveryState.UNKNOWN, DeliveryState.PENDING):
        calls = []
        ledger = NotificationLedger(tmp_path / f"{primary_state}.db")
        dispatcher = NotificationDispatcher(ledger, query_attempts=0, query_delay=0)
        primary = StubAdapter("wechat", primary_state, calls)
        email = StubAdapter("smtp_email", DeliveryState.FAILED, calls)
        first = run(dispatcher.send_with_email_fallback(primary, email, NotificationMessage.test_message(), dedup_key="same"))
        second = run(dispatcher.send_with_email_fallback(primary, email, NotificationMessage.test_message(), dedup_key="same"))
        assert calls == ["wechat", "smtp_email"]
        assert first[1] is not None and first[1].state == DeliveryState.FAILED
        assert second[0].state == DeliveryState.DUPLICATE and second[1] is None


def test_plaintext_smtp_is_refused_before_connecting():
    adapter = smtp_adapter()
    adapter.security = "plain"
    result = run(adapter.send(NotificationMessage.test_message()))
    assert result.state == DeliveryState.FAILED
    assert "plaintext" in result.detail
