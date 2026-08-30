from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CATEGORIES = (
    "unrelated",
    "codex_related",
    "quota_information",
    "reset_hint",
    "reset_announcement",
    "reset_in_progress",
    "reset_confirmed",
    "reset_denial",
)
URGENCIES = ("now", "within_6h", "within_24h", "within_3d", "unknown")
EXPLICITNESS = ("explicit", "implicit", "unclear")


TweetSourceName = Literal["profile_dom", "with_replies", "search", "manual"]


class TweetPayload(BaseModel):
    tweet_id: str = Field(min_length=1, max_length=64)
    author: str = Field(default="thsottiaux", min_length=1, max_length=64)
    text: str = Field(default="", max_length=10000)
    created_at: datetime | None = None
    url: str = Field(default="", max_length=512)
    is_reply: bool = False
    reply_to: str | None = Field(default=None, max_length=64)
    discovered_at: datetime | None = None
    source: TweetSourceName = "manual"


class TweetBatch(BaseModel):
    tweets: list[TweetPayload] = Field(default_factory=list, max_length=500)


class HeartbeatPayload(BaseModel):
    component: str = Field(min_length=1, max_length=64)
    observed_at: datetime | None = None
    last_tweet_seen: datetime | None = None
    state: Literal["healthy", "warning", "offline"] = "healthy"
    error: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiagnosticPayload(BaseModel):
    component: str = Field(min_length=1, max_length=64)
    event: str = Field(min_length=1, max_length=64)
    observed_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ClassificationOutput(BaseModel):
    category: Literal[
        "unrelated",
        "codex_related",
        "quota_information",
        "reset_hint",
        "reset_announcement",
        "reset_in_progress",
        "reset_confirmed",
        "reset_denial",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    urgency: Literal["now", "within_6h", "within_24h", "within_3d", "unknown"] = "unknown"
    explicitness: Literal["explicit", "implicit", "unclear"] = "unclear"
    reason: str = Field(min_length=1, max_length=1000)


class RuleClassification(ClassificationOutput):
    requires_ai: bool = False
