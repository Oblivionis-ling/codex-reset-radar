from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ActionLevel = Literal["GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"]
ResetEventType = Literal["FULL_RESET", "SPECIAL_RESET"]
SpecialResetType = Literal["PARTIAL", "BANKED", "RESET_CARD", "STAGED", "EXTRA_CREDIT", "OTHER"]


class CollectorPost(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tweet_id: str
    author: str | None = None
    text: str = ""
    created_at: datetime | None = None
    posted_at: datetime | None = None
    url: str = ""
    is_reply: bool = False
    reply_to: str | None = None
    reply_to_tweet_id: str | None = None
    discovered_at: datetime | None = None
    collected_at: datetime | None = None
    source: str = "collector_adapter"

    def as_record(self) -> dict[str, Any]:
        return {
            "tweet_id": self.tweet_id,
            "posted_at": self.posted_at or self.created_at,
            "text": self.text,
            "url": self.url,
            "is_reply": self.is_reply,
            "reply_to_tweet_id": self.reply_to_tweet_id or self.reply_to,
            "collected_at": self.collected_at or self.discovered_at,
            "source": self.source,
        }


class CollectorBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tweets: list[CollectorPost] = Field(default_factory=list)
    trace_id: str | None = None


class CollectorHeartbeat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    component: str
    instance_id: str | None = None
    sequence: int | None = None
    observed_at: datetime | None = None
    state: str = "healthy"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResetEventCreate(BaseModel):
    event_type: ResetEventType
    special_type: SpecialResetType | None = None
    occurred_at: datetime
    source_post_id: int | None = None
    title: str
    summary: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class DiagnosticPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    component: str = "collector_adapter"
    event: str = "DIAGNOSTIC"


class DiagnosticBatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    events: list[dict[str, Any]] = Field(default_factory=list)
