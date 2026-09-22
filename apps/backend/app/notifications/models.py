from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class DeliveryState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    OFFLINE_PASS = "OFFLINE_PASS"
    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    DUPLICATE = "DUPLICATE"
    DOCUMENTATION_UNVERIFIED = "DOCUMENTATION_UNVERIFIED"


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    body: str
    url: str | None = None

    @classmethod
    def test_message(cls) -> "NotificationMessage":
        return cls(
            title="测试，非真实 Reset 预警",
            body=(
                "测试，非真实 Reset 预警。\n\n"
                "这是 Codex Reset Radar 的手动渠道验收消息。"
                "请检查微信内显示、锁屏提示、正文和大致延迟。"
            ),
            url="http://127.0.0.1:5173/",
        )

    def clipped(self, *, title_limit: int, body_limit: int) -> "NotificationMessage":
        return NotificationMessage(
            title=self.title.replace("\r", " ").replace("\n", " ")[:title_limit],
            body=self.body[:body_limit],
            url=self.url,
        )


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    state: DeliveryState
    request_accepted: bool
    provider_message_id: str | None = None
    detail: str = ""
    retryable: bool = False
    user_observation_required: bool = True
    attempts: int = 1

    @property
    def final(self) -> bool:
        return self.state in {
            DeliveryState.SUCCEEDED,
            DeliveryState.FAILED,
            DeliveryState.DUPLICATE,
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
