from __future__ import annotations

import asyncio
from dataclasses import replace

from .adapters import NotificationAdapter
from .ledger import NotificationLedger
from .models import DeliveryState, NotificationMessage, NotificationResult


class NotificationDispatcher:
    """Deduplicate one primary attempt and, when requested, one email fallback."""

    def __init__(self, ledger: NotificationLedger, *, query_attempts: int = 2, query_delay: float = 1.0) -> None:
        self.ledger = ledger
        self.query_attempts = max(0, min(3, query_attempts))
        self.query_delay = max(0.0, query_delay)

    async def send_once(
        self,
        adapter: NotificationAdapter,
        message: NotificationMessage,
        *,
        dedup_key: str,
    ) -> NotificationResult:
        if not self.ledger.reserve(dedup_key, adapter.channel):
            return NotificationResult(adapter.channel, DeliveryState.DUPLICATE, False, detail="dedup prevented another send")
        try:
            result = await adapter.send(message)
        except Exception as error:
            result = NotificationResult(
                adapter.channel,
                DeliveryState.FAILED,
                False,
                detail=f"{type(error).__name__}: {str(error)[:300]}",
            )
        self.ledger.record(dedup_key, result)
        return result

    async def settle(self, adapter: NotificationAdapter, result: NotificationResult) -> NotificationResult:
        query = getattr(adapter, "query", None)
        if not callable(query) or not result.provider_message_id:
            return result
        current = result
        for _ in range(self.query_attempts):
            if current.final:
                break
            if self.query_delay:
                await asyncio.sleep(self.query_delay)
            try:
                current = await query(result.provider_message_id)
            except Exception as error:
                current = NotificationResult(
                    adapter.channel,
                    DeliveryState.UNKNOWN,
                    True,
                    provider_message_id=result.provider_message_id,
                    detail=f"status query failed: {type(error).__name__}: {str(error)[:200]}",
                )
                break
        return current

    async def send_with_email_fallback(
        self,
        primary: NotificationAdapter,
        email: NotificationAdapter,
        message: NotificationMessage,
        *,
        dedup_key: str,
    ) -> tuple[NotificationResult, NotificationResult | None]:
        primary_result = await self.send_once(primary, message, dedup_key=dedup_key)
        if primary_result.state == DeliveryState.DUPLICATE:
            return primary_result, None
        settled = await self.settle(primary, primary_result)
        self.ledger.record(dedup_key, settled)
        if settled.state == DeliveryState.SUCCEEDED:
            return settled, None
        reason = "微信发送失败" if settled.state == DeliveryState.FAILED else "微信结果未确认"
        fallback_message = replace(message, body=f"{reason}，已转邮件保底。\n\n{message.body}")
        email_result = await self.send_once(email, fallback_message, dedup_key=f"{dedup_key}:email-fallback")
        return settled, email_result
