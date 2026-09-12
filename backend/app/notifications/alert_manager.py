from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.intelligence.radar import RADAR_STATES, STATE_RANK, RadarDecision
from app.models import Alert, Classification, MonitorHealth, NotificationBaseline, RadarState, Tweet
from app.observability import (
    BACKEND_INSTANCE_ID,
    append_event,
    current_environment,
    current_trace_id,
    observability_context,
    redact_secret,
)

from .windows import WindowsToastNotifier
from .wxpusher import WxPusherNotifier, WxPusherSendResult


logger = logging.getLogger("radar.notifications")
NOTIFICATION_DIAGNOSTIC_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "notification-delivery.jsonl"
NOTIFICATION_TEST_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "notification-test.jsonl"
_NOTIFICATION_LOG_LOCK = threading.Lock()

ALERT_TYPES = {
    "reset_likely",
    "reset_imminent",
    "reset_announced",
    "reset_confirmed",
    "monitor_offline",
    "monitor_recovered",
    "test",
}
RADAR_ALERT_TYPES = {
    "LIKELY": "reset_likely",
    "IMMINENT": "reset_imminent",
    "ANNOUNCED": "reset_announced",
    "CONFIRMED": "reset_confirmed",
}
MONITOR_COMPONENTS = ("backend", "profile_monitor", "replies_monitor", "search_backfill")
MONITOR_LABELS = {
    "profile_monitor": "Profile Monitor",
    "replies_monitor": "Replies Monitor",
    "search_backfill": "Search Backfill",
    "backend": "Backend",
}


class Notifier(Protocol):
    def send(self, title: str, content: str) -> Any: ...


@dataclass(frozen=True)
class NotificationPayload:
    title: str
    content: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _notification_timestamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def _safe_notification_text(settings: Settings, value: Any) -> str:
    safe = " ".join(str(value or "").split())
    for secret in (settings.wxpusher_app_token, settings.wxpusher_uid, settings.deepseek_api_key):
        if secret:
            safe = safe.replace(secret, "[redacted]")
    return safe[:500]


def _append_notification_log(event: str, settings: Settings, **fields: Any) -> None:
    """Keep notification diagnostics durable through the shared event writer."""
    environment = fields.pop("environment", None) or current_environment()
    if os.getenv("PYTEST_CURRENT_TEST") and environment == "production":
        environment = "test"
    stream = "notifications" if environment == "production" else f"notifications-{environment}"
    legacy_path = NOTIFICATION_DIAGNOSTIC_LOG_PATH if environment == "production" else NOTIFICATION_TEST_LOG_PATH
    append_event(
        stream,
        event,
        component="notifications",
        instance_id=BACKEND_INSTANCE_ID,
        trace_id=fields.pop("trace_id", None) or current_trace_id(),
        request_id=fields.pop("request_id", None),
        legacy_paths=(legacy_path,),
        source="alert-manager",
        environment=environment,
        **fields,
    )


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def derived_monitor_state(record: MonitorHealth | None, now: datetime | None = None) -> str:
    """Use the same 15/30-minute warning/offline thresholds as /api/health."""
    if record is None:
        return "unknown"
    if record.state == "offline":
        return "offline"
    age_seconds = max(0.0, ((now or utc_now()) - (as_utc(record.last_heartbeat) or utc_now())).total_seconds())
    if age_seconds > 30 * 60:
        return "offline"
    if age_seconds > 15 * 60 and record.state == "healthy":
        return "warning"
    return record.state


def short_reason(reason: str | None, limit: int = 360) -> str:
    value = " ".join((reason or "No additional reason.").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def urgency_text(urgency: str | None) -> str:
    return {
        "now": "现在",
        "within_6h": "6小时以内",
        "within_24h": "24小时以内",
        "within_3d": "3天以内",
        "unknown": "未知",
    }.get(urgency or "unknown", urgency or "未知")


class AlertManager:
    """Persist and deliver alerts derived from already-computed Radar/health data."""

    def __init__(
        self,
        settings: Settings,
        *,
        wxpusher: Notifier | None = None,
        windows: Notifier | None = None,
        retry_attempts: int = 3,
        retry_delay: float = 0.2,
    ):
        self.settings = settings
        self.wxpusher = wxpusher or WxPusherNotifier(settings.wxpusher_app_token, settings.wxpusher_uid)
        self.windows = windows or WindowsToastNotifier()
        self.retry_attempts = max(1, retry_attempts)
        self.retry_delay = max(0.0, retry_delay)
        self.last_delivery_details: dict[str, Any] | None = None
        config_fields = {
            "enabled": settings.wxpusher_enabled,
            "alerts_enabled": settings.alerts_enabled,
            "dry_run": settings.alert_dry_run,
            "app_token_configured": bool(settings.wxpusher_app_token),
            "recipient_configured": bool(settings.wxpusher_uid),
            "uid_length": len(settings.wxpusher_uid),
            "windows_enabled": settings.windows_notifications_enabled,
        }
        logger.info(
            "WXPUSHER_CONFIG_CHECK enabled=%s alerts_enabled=%s dry_run=%s app_token_configured=%s "
            "recipient_configured=%s uid_length=%s windows_enabled=%s",
            config_fields["enabled"],
            config_fields["alerts_enabled"],
            config_fields["dry_run"],
            config_fields["app_token_configured"],
            config_fields["recipient_configured"],
            config_fields["uid_length"],
            config_fields["windows_enabled"],
        )
        _append_notification_log("WXPUSHER_CONFIG_CHECK", settings, **config_fields)
        _append_notification_log("WXPUSHER_PROVIDER_INITIALIZED", settings, **config_fields)

    def initialize_baseline(self, session: Session) -> NotificationBaseline:
        """Record the current state on process start without sending notifications."""
        radar = session.get(RadarState, 1)
        monitors = {
            record.component: derived_monitor_state(record)
            for record in session.scalars(select(MonitorHealth)).all()
        }
        baseline = session.get(NotificationBaseline, 1)
        if baseline is None:
            baseline = NotificationBaseline(id=1)
            session.add(baseline)
        baseline.radar_state = radar.state if radar else "QUIET"
        baseline.trigger_tweet_id = radar.trigger_tweet_id if radar else None
        baseline.monitor_states_json = json.dumps(monitors, ensure_ascii=False, sort_keys=True)
        baseline.initialized_at = utc_now()
        baseline.updated_at = baseline.initialized_at
        session.flush()
        logger.info("ALERT_BASELINE_INITIALIZED state=%s trigger_tweet_id=%s", baseline.radar_state, baseline.trigger_tweet_id)
        return baseline

    def handle_radar_transition(self, session: Session, decision: RadarDecision, *, trace_id: str | None = None) -> list[Alert]:
        baseline = session.get(NotificationBaseline, 1)
        if baseline is None:
            self.initialize_baseline(session)
            return []

        previous_state = baseline.radar_state
        alerts: list[Alert] = []
        is_escalation = (
            decision.state in RADAR_ALERT_TYPES
            and STATE_RANK.get(decision.state, -1) > STATE_RANK.get(previous_state, -1)
        )
        is_new_terminal_evidence = (
            decision.state in {"ANNOUNCED", "CONFIRMED"}
            and decision.trigger_tweet_id is not None
            and decision.trigger_tweet_id != baseline.trigger_tweet_id
        )
        should_alert = is_escalation or is_new_terminal_evidence
        if should_alert:
            alert_type = RADAR_ALERT_TYPES[decision.state]
            payload = self.radar_payload(session, decision)
            alerts.extend(
                self._dispatch(
                    session,
                    alert_type=alert_type,
                    tweet_id=decision.trigger_tweet_id or "radar:none",
                    radar_state=decision.state,
                    payload=payload,
                    trace_id=trace_id,
                )
            )
        baseline.radar_state = decision.state
        baseline.trigger_tweet_id = decision.trigger_tweet_id
        baseline.updated_at = utc_now()
        session.flush()
        if should_alert:
            logger.info("ALERT_TRIGGERED alert_type=%s radar_state=%s", RADAR_ALERT_TYPES[decision.state], decision.state)
        return alerts

    def evaluate_monitor_health(self, session: Session, *, now: datetime | None = None) -> list[Alert]:
        current_time = now or utc_now()
        baseline = session.get(NotificationBaseline, 1)
        if baseline is None:
            self.initialize_baseline(session)
            return []
        previous = self._load_monitor_states(baseline.monitor_states_json)
        records = {record.component: record for record in session.scalars(select(MonitorHealth)).all()}
        current = {component: derived_monitor_state(records.get(component), current_time) for component in MONITOR_COMPONENTS}
        alerts: list[Alert] = []
        for component, state in current.items():
            previous_state = previous.get(component)
            if state == "offline" and previous_state != "offline":
                alerts.extend(self._dispatch_monitor(session, "monitor_offline", component, records, current))
                logger.warning("MONITOR_OFFLINE_ALERT component=%s", component)
            elif state == "healthy" and previous_state == "offline":
                alerts.extend(self._dispatch_monitor(session, "monitor_recovered", component, records, current))
                logger.info("MONITOR_RECOVERED_ALERT component=%s", component)
        baseline.monitor_states_json = json.dumps(current, ensure_ascii=False, sort_keys=True)
        baseline.updated_at = utc_now()
        session.flush()
        return alerts

    def send_test_alert(self, session: Session, channel: str) -> Alert | None:
        if channel not in {"wxpusher", "windows"}:
            raise ValueError("channel must be wxpusher or windows")
        beijing_tz = timezone(timedelta(hours=8), name="Asia/Shanghai")
        sent_at_bj = datetime.now(beijing_tz).isoformat(timespec="seconds")
        payload = NotificationPayload(
            title="TEST | Codex Reset Radar 通知测试",
            content=(
                "TEST\n\n"
                "这是一条 Codex Reset Radar 微信通知渠道诊断消息。\n\n"
                f"发送时间（北京时间）：{sent_at_bj}\n\n"
                "如果你在微信中看到这条消息，说明 Radar → WxPusher → 微信的基础投递链路仍然可用。"
            ),
        )
        alerts = self._dispatch(
            session,
            alert_type="test",
            tweet_id=f"test:{uuid.uuid4().hex}",
            radar_state="TEST",
            payload=payload,
            channels=(channel,),
            trace_id=f"alert-test-{uuid.uuid4().hex[:12]}",
            environment="diagnostic",
        )
        return alerts[0] if alerts else None

    def radar_payload(self, session: Session, decision: RadarDecision) -> NotificationPayload:
        tweet = session.get(Tweet, decision.trigger_tweet_id) if decision.trigger_tweet_id else None
        final = None
        if tweet:
            final = session.scalar(
                select(Classification)
                .where(Classification.tweet_id == tweet.tweet_id, Classification.classifier_type == "final")
                .order_by(Classification.created_at.desc(), Classification.id.desc())
                .limit(1)
            )
        confidence = f"{round(max(0.0, min(1.0, decision.confidence)) * 100):.0f}%"
        text = tweet.text if tweet else "（原文暂不可用）"
        url = tweet.url if tweet else ""
        reason = short_reason(final.reason if final else decision.reason)
        category = final.category if final else None
        banked = category in {"reset_announcement", "reset_confirmed"} and "banked reset" in text.lower()
        banked_line = "\nReset Type:\nBanked Reset\n" if banked else ""
        if decision.state == "LIKELY":
            title = "🟡 Codex Reset 信号"
            body = (
                f"当前状态：\nLIKELY\n\nSignal Confidence：\n{confidence}\n\n"
                f"预计时间：\n{urgency_text(decision.urgency)}\n\nTibo：\n{text}\n\n"
                f"判断：\n{reason}\n\n原帖：\n{url}"
            )
        elif decision.state == "IMMINENT":
            title = "🟠 Codex Reset 高概率预警"
            body = (
                f"当前状态：\nIMMINENT\n\nSignal Confidence：\n{confidence}\n\n"
                f"预计时间：\n{urgency_text(decision.urgency)}\n\nTibo：\n{text}\n\n"
                f"判断：\n{reason}\n\n原帖：\n{url}"
            )
        elif decision.state == "ANNOUNCED":
            title = "🔴 Codex Reset 已明确预告"
            body = (
                f"Tibo 已明确宣布 Reset。\n\n预计时间：\n{urgency_text(decision.urgency)}\n"
                f"{banked_line}\n原文：\n{text}\n\n判断：\n{reason}\n\n原帖：\n{url}"
            )
        else:
            title = "🟢 Codex Reset 已确认"
            body = f"检测到 Codex Reset 已执行。\n{banked_line}\nTibo：\n{text}\n\n判断：\n{reason}\n\n原帖：\n{url}"
        return NotificationPayload(title, body)

    def _dispatch_monitor(
        self,
        session: Session,
        alert_type: str,
        component: str,
        records: dict[str, MonitorHealth],
        current: dict[str, str],
    ) -> list[Alert]:
        label = MONITOR_LABELS.get(component, component)
        record = records.get(component)
        last_heartbeat = as_utc(record.last_heartbeat).isoformat() if record else "未知"
        status_lines = "\n".join(
            f"{MONITOR_LABELS.get(name, name)}：{state}" for name, state in current.items()
        )
        if alert_type == "monitor_offline":
            title = "🔴 Codex Radar 监控异常"
            qualification = ""
            if component in {"profile_monitor", "replies_monitor"} and current.get("search_backfill") == "healthy":
                qualification = "⚠️ 实时采集受影响，但 Search Backfill 仍工作。\n\n"
            content = f"{qualification}{label} 已离线。\n\n最后心跳：\n{last_heartbeat}\n\n{status_lines}"
        else:
            title = "🟢 Codex Radar 监控已恢复"
            content = f"{label} 已恢复运行。\n\n最后心跳：\n{last_heartbeat}\n\n{status_lines}"
        return self._dispatch(
            session,
            alert_type=alert_type,
            tweet_id=f"monitor:{component}",
            radar_state="OFFLINE" if alert_type == "monitor_offline" else "HEALTHY",
            payload=NotificationPayload(title, content),
        )

    def _dispatch(
        self,
        session: Session,
        *,
        alert_type: str,
        tweet_id: str,
        radar_state: str,
        payload: NotificationPayload,
        channels: tuple[str, ...] | None = None,
        trace_id: str | None = None,
        environment: str | None = None,
    ) -> list[Alert]:
        with observability_context(
            trace_id=trace_id or current_trace_id() or f"alert-{uuid.uuid4().hex[:12]}",
            environment=environment,
        ):
            return self._dispatch_with_trace(
                session,
                alert_type=alert_type,
                tweet_id=tweet_id,
                radar_state=radar_state,
                payload=payload,
                channels=channels,
            )

    def _dispatch_with_trace(
        self,
        session: Session,
        *,
        alert_type: str,
        tweet_id: str,
        radar_state: str,
        payload: NotificationPayload,
        channels: tuple[str, ...] | None = None,
    ) -> list[Alert]:
        if alert_type not in ALERT_TYPES:
            raise ValueError(f"unsupported alert type: {alert_type}")
        selected_channels = channels or self._configured_channels()
        self.last_delivery_details = None
        _append_notification_log(
            "ALERT_RECEIVED",
            self.settings,
            alert_type=alert_type,
            tweet_id=tweet_id,
            radar_state=radar_state,
            channels=",".join(selected_channels),
        )
        logger.info(
            "ALERT_RECEIVED alert_type=%s tweet_id=%s radar_state=%s channels=%s",
            alert_type,
            tweet_id,
            radar_state,
            ",".join(selected_channels) or "-",
        )
        if not selected_channels:
            reason = "disabled" if not self.settings.alerts_enabled or not self._configured_channels() else "no_recipient"
            _append_notification_log(
                "ALERT_SUPPRESSED",
                self.settings,
                alert_type=alert_type,
                tweet_id=tweet_id,
                radar_state=radar_state,
                reason=reason,
            )
            logger.info("ALERT_SUPPRESSED alert_type=%s reason=%s", alert_type, reason)
            return []
        results: list[Alert] = []
        for channel in selected_channels:
            existing = session.scalar(
                select(Alert).where(
                    Alert.alert_type == alert_type,
                    Alert.tweet_id == tweet_id,
                    Alert.radar_state == radar_state,
                    Alert.channel == channel,
                )
            )
            if existing is not None:
                logger.info(
                    "ALERT_DEDUPLICATED alert_type=%s tweet_id=%s radar_state=%s channel=%s",
                    alert_type,
                    tweet_id,
                    radar_state,
                    channel,
                )
                _append_notification_log(
                    "ALERT_SUPPRESSED",
                    self.settings,
                    alert_type=alert_type,
                    tweet_id=tweet_id,
                    radar_state=radar_state,
                    channel=channel,
                    reason="dedup",
                )
                continue
            _append_notification_log(
                "ALERT_DISPATCH_STARTED",
                self.settings,
                alert_type=alert_type,
                tweet_id=tweet_id,
                radar_state=radar_state,
                channel=channel,
            )
            logger.info(
                "ALERT_DISPATCH_STARTED alert_type=%s tweet_id=%s radar_state=%s channel=%s",
                alert_type,
                tweet_id,
                radar_state,
                channel,
            )
            alert = Alert(
                tweet_id=tweet_id,
                alert_type=alert_type,
                radar_state=radar_state,
                channel=channel,
                status="pending",
                created_at=utc_now(),
            )
            session.add(alert)
            session.flush()
            status, error = self._deliver(channel, payload)
            alert.status = status
            alert.error = error
            if status in {"sent", "dry_run"}:
                alert.sent_at = utc_now()
            session.flush()
            results.append(alert)
        return results

    def _configured_channels(self) -> tuple[str, ...]:
        channels: list[str] = []
        if self.settings.wxpusher_enabled:
            channels.append("wxpusher")
        if self.settings.windows_notifications_enabled:
            channels.append("windows")
        return tuple(channels)

    def _deliver(self, channel: str, payload: NotificationPayload) -> tuple[str, str | None]:
        if self.settings.alert_dry_run:
            logger.info("ALERT_SKIPPED channel=%s reason=dry_run", channel)
            self.last_delivery_details = {"channel": channel, "delivery_status": "not_attempted", "reason": "dry_run"}
            _append_notification_log("ALERT_SUPPRESSED", self.settings, channel=channel, reason="dry_run")
            return "dry_run", None
        if not self.settings.alerts_enabled:
            logger.info("ALERT_SKIPPED channel=%s reason=alerts_disabled", channel)
            self.last_delivery_details = {"channel": channel, "delivery_status": "not_attempted", "reason": "disabled"}
            _append_notification_log("ALERT_SUPPRESSED", self.settings, channel=channel, reason="disabled")
            return "skipped", "alerts_disabled"
        if channel == "wxpusher" and (
            not self.settings.wxpusher_enabled
            or not self.settings.wxpusher_app_token
            or not self.settings.wxpusher_uid
        ):
            self.last_delivery_details = {"channel": channel, "delivery_status": "not_attempted", "reason": "no_recipient"}
            _append_notification_log("ALERT_SUPPRESSED", self.settings, channel=channel, reason="no_recipient")
            return "failed", "wxpusher_not_configured"
        if channel == "windows" and not self.settings.windows_notifications_enabled:
            self.last_delivery_details = {"channel": channel, "delivery_status": "not_attempted", "reason": "disabled"}
            _append_notification_log("ALERT_SUPPRESSED", self.settings, channel=channel, reason="disabled")
            return "failed", "windows_notifications_disabled"
        notifier = self.wxpusher if channel == "wxpusher" else self.windows if channel == "windows" else None
        if notifier is None:
            self.last_delivery_details = {"channel": channel, "delivery_status": "not_attempted", "reason": "unsupported"}
            _append_notification_log("ALERT_SUPPRESSED", self.settings, channel=channel, reason="unsupported")
            return "failed", "unsupported channel"
        last_error: str | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                if channel == "wxpusher":
                    _append_notification_log(
                        "WXPUSHER_REQUEST_STARTED",
                        self.settings,
                        channel=channel,
                        attempt=attempt,
                        content_length=len(payload.content),
                        summary_length=len(payload.title[:100]),
                        recipient_configured=bool(self.settings.wxpusher_uid),
                    )
                provider_result = notifier.send(payload.title, payload.content)
                self.last_delivery_details = self._provider_details(channel, provider_result)
                self.last_delivery_details["attempt"] = attempt
                if channel == "wxpusher" and isinstance(provider_result, WxPusherSendResult):
                    _append_notification_log(
                        "WXPUSHER_REQUEST_SUCCESS",
                        self.settings,
                        channel=channel,
                        attempt=attempt,
                        http_status=provider_result.http_status,
                        response_code=provider_result.response_code,
                        send_record_id=provider_result.send_record_id,
                        duration_ms=provider_result.duration_ms,
                        delivery_status="accepted_async",
                    )
                event_prefix = "WXPUSHER" if channel == "wxpusher" else "WINDOWS_NOTIFICATION"
                logger.info("%s_SENT channel=%s attempt=%s", event_prefix, channel, attempt)
                return "sent", None
            except Exception as exc:  # notifier failures must never escape into Radar
                last_error = self._safe_error(str(exc))
                self.last_delivery_details = self._provider_error_details(channel, exc, attempt)
                if channel == "wxpusher":
                    _append_notification_log(
                        "WXPUSHER_REQUEST_FAILED",
                        self.settings,
                        channel=channel,
                        attempt=attempt,
                        http_status=getattr(exc, "http_status", None),
                        response_code=getattr(exc, "response_code", None),
                        send_record_id=getattr(exc, "send_record_id", None),
                        duration_ms=getattr(exc, "duration_ms", None),
                        error_type=getattr(exc, "error_type", "unknown"),
                        error=last_error,
                    )
                if attempt < self.retry_attempts and self.retry_delay:
                    if channel == "wxpusher":
                        _append_notification_log(
                            "WXPUSHER_RETRY_SCHEDULED",
                            self.settings,
                            channel=channel,
                            attempt=attempt,
                            next_attempt=attempt + 1,
                            retry_delay_seconds=self.retry_delay * attempt,
                            error_type=getattr(exc, "error_type", "unknown"),
                        )
                    time.sleep(self.retry_delay * attempt)
        event_prefix = "WXPUSHER" if channel == "wxpusher" else "WINDOWS_NOTIFICATION"
        logger.warning("%s_FAILED channel=%s error=%s", event_prefix, channel, last_error or "unknown")
        return "failed", last_error or "notification failed"

    @staticmethod
    def _provider_details(channel: str, result: Any) -> dict[str, Any]:
        if isinstance(result, WxPusherSendResult):
            return {
                "channel": channel,
                "http_status": result.http_status,
                "response_code": result.response_code,
                "message": result.message,
                "send_record_id": result.send_record_id,
                "duration_ms": result.duration_ms,
                "delivery_status": "accepted_async",
            }
        return {"channel": channel, "provider_result": "not_available", "delivery_status": "accepted_by_provider"}

    @staticmethod
    def _provider_error_details(channel: str, error: Exception, attempt: int) -> dict[str, Any]:
        return {
            "channel": channel,
            "attempt": attempt,
            "http_status": getattr(error, "http_status", None),
            "response_code": getattr(error, "response_code", None),
            "send_record_id": getattr(error, "send_record_id", None),
            "duration_ms": getattr(error, "duration_ms", None),
            "error_type": getattr(error, "error_type", "unknown"),
            "delivery_status": "not_accepted",
        }

    def _load_monitor_states(self, raw: str | None) -> dict[str, str]:
        try:
            parsed: Any = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _safe_error(self, message: str) -> str:
        safe = _safe_notification_text(self.settings, message)
        for secret in (self.settings.wxpusher_app_token, self.settings.wxpusher_uid):
            if secret:
                safe = safe.replace(secret, "[redacted]")
        return safe[:500]
