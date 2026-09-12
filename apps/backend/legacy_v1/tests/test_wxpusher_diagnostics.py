from __future__ import annotations

import json
import logging

from app.notifications import wxpusher as wxpusher_module
from app.notifications.wxpusher import WxPusherNotifier


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


def test_send_records_api_result_without_logging_recipient_secret(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    secret_uid = "UID_private_value"
    secret_token = "AT_private_value"

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(
            {
                "code": 1000,
                "msg": "处理成功",
                "data": [{"uid": secret_uid, "sendRecordId": 123456, "status": "PENDING"}],
            }
        )

    monkeypatch.setattr(wxpusher_module, "urlopen", fake_urlopen)
    notifier = WxPusherNotifier(secret_token, secret_uid, timeout=3)

    result = notifier.send("TEST", "diagnostic body")

    assert result.http_status == 200
    assert result.response_code == 1000
    assert result.send_record_id == 123456
    assert result.duration_ms >= 0
    assert json.loads(calls[0][0].data.decode("utf-8"))["appToken"] == secret_token
    assert secret_token not in caplog.text
    assert secret_uid not in caplog.text
    assert "WXPUSHER_REQUEST_SUCCESS" in caplog.text


def test_query_status_uses_current_official_endpoint(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse(
            {"code": 1000, "msg": "查询成功", "data": {"sendRecordId": 123456, "status": "SUCCESS"}}
        )

    monkeypatch.setattr(wxpusher_module, "urlopen", fake_urlopen)
    notifier = WxPusherNotifier("AT_private_value", "UID_private_value")

    result = notifier.query_status(123456)

    assert result.http_status == 200
    assert result.response_code == 1000
    assert result.send_record_id == 123456
    assert result.status == "SUCCESS"
    assert calls[0][0] == "https://wxpusher.zjiecode.com/api/send/query/status?sendRecordId=123456"
    assert "appToken" not in calls[0][0]
