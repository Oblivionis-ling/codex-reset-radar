from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .models import DeliveryState, NotificationMessage, NotificationResult
from .security import safe_detail
from .transport import HttpTransport


class NotificationAdapter(Protocol):
    channel: str

    async def send(self, message: NotificationMessage) -> NotificationResult: ...


class QueryableAdapter(NotificationAdapter, Protocol):
    async def query(self, provider_message_id: str) -> NotificationResult: ...


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _http_failure(channel: str, response: httpx.Response, attempts: int, secrets: tuple[str, ...]) -> NotificationResult:
    return NotificationResult(
        channel=channel,
        state=DeliveryState.FAILED,
        request_accepted=False,
        detail=safe_detail(f"HTTP {response.status_code}: {response.text}", secrets),
        retryable=response.status_code in {408, 409, 429} or response.status_code >= 500,
        attempts=attempts,
    )


@dataclass
class PushPlusAdapter:
    transport: HttpTransport
    token: str
    channel_name: str = "wechat"
    channel: str = "pushplus_wechat"
    endpoint: str = "https://www.pushplus.plus/send"

    async def send(self, message: NotificationMessage) -> NotificationResult:
        current = message.clipped(title_limit=200, body_limit=20_000)
        response, attempts = await self.transport.request(
            "POST",
            self.endpoint,
            json={
                "token": self.token,
                "title": current.title,
                "content": current.body,
                "template": "txt",
                "channel": self.channel_name,
            },
        )
        if not response.is_success:
            return _http_failure(self.channel, response, attempts, (self.token,))
        payload = _json(response)
        if payload.get("code") != 200:
            return NotificationResult(
                self.channel, DeliveryState.FAILED, False,
                detail=safe_detail(payload.get("msg") or "PushPlus business failure", (self.token,)),
                attempts=attempts,
            )
        return NotificationResult(
            self.channel,
            DeliveryState.PENDING,
            True,
            provider_message_id=str(payload.get("data") or "") or None,
            detail="provider accepted the asynchronous request; public polling contract is not verified",
            attempts=attempts,
        )


@dataclass
class ServerChanAdapter:
    transport: HttpTransport
    sendkey: str
    channel: str = "serverchan_wechat"

    async def send(self, message: NotificationMessage) -> NotificationResult:
        current = message.clipped(title_limit=128, body_limit=20_000)
        endpoint = f"https://sctapi.ftqq.com/{quote(self.sendkey, safe='')}.send"
        response, attempts = await self.transport.request(
            "POST", endpoint, data={"title": current.title, "desp": current.body}
        )
        if not response.is_success:
            return _http_failure(self.channel, response, attempts, (self.sendkey,))
        payload = _json(response)
        if payload.get("code") != 0:
            return NotificationResult(
                self.channel, DeliveryState.FAILED, False,
                detail=safe_detail(payload.get("message") or payload.get("msg") or "ServerChan business failure", (self.sendkey,)),
                attempts=attempts,
            )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return NotificationResult(
            self.channel, DeliveryState.ACCEPTED, True,
            provider_message_id=str(data.get("pushid") or data.get("pushId") or "") or None,
            detail="provider accepted request; no per-message query contract",
            attempts=attempts,
        )


@dataclass
class IyuuAdapter:
    transport: HttpTransport
    token: str
    channel: str = "iyuu_wechat"

    async def send(self, message: NotificationMessage) -> NotificationResult:
        current = message.clipped(title_limit=200, body_limit=20_000)
        endpoint = f"https://iyuu.cn/{quote(self.token, safe='')}.send"
        response, attempts = await self.transport.request(
            "POST", endpoint, data={"text": current.title, "desp": current.body}
        )
        if not response.is_success:
            return _http_failure(self.channel, response, attempts, (self.token,))
        payload = _json(response)
        if payload.get("errcode") != 0:
            return NotificationResult(
                self.channel, DeliveryState.FAILED, False,
                detail=safe_detail(payload.get("errmsg") or "IYUU business failure", (self.token,)),
                attempts=attempts,
            )
        return NotificationResult(
            self.channel, DeliveryState.ACCEPTED, True,
            detail="provider accepted request; no per-message query contract",
            attempts=attempts,
        )


@dataclass
class WPushAdapter:
    transport: HttpTransport
    api_key: str
    channel_name: str = "wechat"
    channel: str = "wpush_wechat"
    endpoint: str = "https://api.wpush.cn/api/v1/send"
    query_endpoint: str = "https://api.wpush.cn/api/v1/query"

    async def send(self, message: NotificationMessage) -> NotificationResult:
        current = message.clipped(title_limit=255, body_limit=10_000)
        payload: dict[str, str] = {
            "apikey": self.api_key,
            "title": current.title,
            "content": current.body,
            "channel": self.channel_name,
        }
        if current.url:
            payload["url"] = current.url[:512]
        response, attempts = await self.transport.request("POST", self.endpoint, data=payload)
        if not response.is_success:
            return _http_failure(self.channel, response, attempts, (self.api_key,))
        body = _json(response)
        if body.get("code") != 0 or body.get("success") is False:
            return NotificationResult(
                self.channel, DeliveryState.FAILED, False,
                detail=safe_detail(body.get("message") or "WPush business failure", (self.api_key,)),
                attempts=attempts,
            )
        return NotificationResult(
            self.channel, DeliveryState.PENDING, True,
            provider_message_id=str(body.get("data") or "") or None,
            detail="provider accepted request; status query available",
            attempts=attempts,
        )

    async def query(self, provider_message_id: str) -> NotificationResult:
        response, attempts = await self.transport.request(
            "POST", self.query_endpoint, data={"apikey": self.api_key, "id": provider_message_id}
        )
        if not response.is_success:
            return _http_failure(self.channel, response, attempts, (self.api_key,))
        body = _json(response)
        if body.get("code") != 0 or body.get("success") is False:
            return NotificationResult(
                self.channel, DeliveryState.FAILED, False, provider_message_id,
                safe_detail(body.get("message") or "WPush status query failed", (self.api_key,)),
                attempts=attempts,
            )
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        status = data.get("status")
        state = {0: DeliveryState.PENDING, 1: DeliveryState.SUCCEEDED, 2: DeliveryState.FAILED,
                 "0": DeliveryState.PENDING, "1": DeliveryState.SUCCEEDED, "2": DeliveryState.FAILED}.get(
            status, DeliveryState.UNKNOWN
        )
        return NotificationResult(
            self.channel, state, True, provider_message_id,
            detail=f"provider status={status}", attempts=attempts,
        )


@dataclass
class WxPusherAdapter:
    transport: HttpTransport
    app_token: str
    uid: str
    channel: str = "wxpusher"
    endpoint: str = "https://wxpusher.zjiecode.com/api/send/message"
    query_endpoint: str = "https://wxpusher.zjiecode.com/api/send/query/status"

    async def send(self, message: NotificationMessage) -> NotificationResult:
        current = message.clipped(title_limit=100, body_limit=40_000)
        response, attempts = await self.transport.request(
            "POST",
            self.endpoint,
            json={
                "appToken": self.app_token,
                "content": current.body,
                "summary": current.title,
                "contentType": 1,
                "uids": [self.uid],
                **({"url": current.url[:1000]} if current.url else {}),
            },
        )
        secrets = (self.app_token, self.uid)
        if not response.is_success:
            return _http_failure(self.channel, response, attempts, secrets)
        body = _json(response)
        if body.get("code") != 1000:
            return NotificationResult(
                self.channel, DeliveryState.FAILED, False,
                detail=safe_detail(body.get("msg") or "WxPusher business failure", secrets),
                attempts=attempts,
            )
        targets = body.get("data") if isinstance(body.get("data"), list) else []
        target = targets[0] if targets and isinstance(targets[0], dict) else {}
        return NotificationResult(
            self.channel,
            DeliveryState.PENDING,
            True,
            provider_message_id=str(target.get("sendRecordId") or body.get("sendRecordId") or "") or None,
            detail="provider accepted request; status query available",
            attempts=attempts,
        )

    async def query(self, provider_message_id: str) -> NotificationResult:
        response, attempts = await self.transport.request(
            "GET", self.query_endpoint, params={"sendRecordId": provider_message_id}
        )
        secrets = (self.app_token, self.uid)
        if not response.is_success:
            return _http_failure(self.channel, response, attempts, secrets)
        body = _json(response)
        if body.get("code") != 1000:
            return NotificationResult(
                self.channel, DeliveryState.FAILED, False, provider_message_id,
                safe_detail(body.get("msg") or "WxPusher status query failed", secrets),
                attempts=attempts,
            )
        data = body.get("data")
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        if not isinstance(data, dict):
            data = {"status": data}
        status = str(data.get("status") or "").upper()
        if status in {"SUCCESS", "SUCCEEDED", "DELIVERED", "2"}:
            state = DeliveryState.SUCCEEDED
        elif status in {"FAIL", "FAILED", "3"}:
            state = DeliveryState.FAILED
        elif status in {"PENDING", "SENDING", "0", "1"}:
            state = DeliveryState.PENDING
        else:
            state = DeliveryState.UNKNOWN
        return NotificationResult(
            self.channel, state, True, provider_message_id,
            detail=f"provider status={status or 'missing'}", attempts=attempts,
        )


@dataclass
class ShowDocAdapter:
    transport: HttpTransport
    token: str
    channel: str = "showdoc_wechat"

    async def send(self, message: NotificationMessage) -> NotificationResult:
        current = message.clipped(title_limit=255, body_limit=20_000)
        endpoint = f"https://push.showdoc.com.cn/server/api/push/{quote(self.token, safe='')}"
        response, attempts = await self.transport.request(
            "POST", endpoint, data={"title": current.title, "content": current.body}
        )
        if not response.is_success:
            return _http_failure(self.channel, response, attempts, (self.token,))
        body = _json(response)
        if body.get("error_code") != 0:
            return NotificationResult(
                self.channel, DeliveryState.FAILED, False,
                detail=safe_detail(body.get("error_message") or "ShowDoc business failure", (self.token,)),
                attempts=attempts,
            )
        return NotificationResult(
            self.channel, DeliveryState.ACCEPTED, True,
            detail="provider accepted request; no per-message query contract",
            attempts=attempts,
        )
