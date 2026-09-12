from __future__ import annotations

import re
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    BEIJING = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:  # Windows runtime may not bundle tzdata; China has no DST.
    BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
RESET_SIGNAL_CATEGORIES = {
    "reset_hint",
    "reset_announcement",
    "reset_in_progress",
    "reset_confirmed",
}


def as_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _interval_label(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total_hours = max(0, round(seconds / 3600))
    if seconds < 3600:
        return f"{max(1, round(seconds / 60))}分钟"
    days, hours = divmod(total_hours, 24)
    if days:
        return f"{days}天 {hours}小时"
    return f"{hours}小时"


def _beijing_parts(event_time: datetime) -> tuple[str, str]:
    local = event_time.astimezone(BEIJING)
    return local.date().isoformat(), local.strftime("%H:%M")


def build_reset_history(
    explicit_events: Iterable[dict[str, Any]],
    confirmed_tweets: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build public reset history, preferring explicitly recorded events.

    When the event table is empty, the fallback uses only the latest final
    `reset_confirmed` classifications supplied by the caller. Identical
    evidence text is collapsed so repeated classification/repost rows do not
    look like multiple resets.
    """

    explicit = []
    for item in explicit_events:
        event_time = as_utc(item.get("event_time"))
        if event_time:
            explicit.append(
                {
                    "event_time": iso(event_time),
                    "source": str(item.get("source") or "reset_event"),
                    "evidence_tweet_id": item.get("evidence_tweet_id"),
                    "notes": item.get("notes"),
                }
            )
    if explicit:
        events = explicit
    else:
        events = []
        seen_ids: set[str] = set()
        seen_text: set[str] = set()
        for item in sorted(
            (item for item in confirmed_tweets if as_utc(item.get("event_time"))),
            key=lambda item: as_utc(item.get("event_time")) or datetime.min.replace(tzinfo=timezone.utc),
        ):
            evidence_id = str(item.get("evidence_tweet_id") or "")
            text_key = re.sub(r"\s+", " ", str(item.get("text") or "").strip().casefold())
            if evidence_id and evidence_id in seen_ids:
                continue
            if text_key and text_key in seen_text:
                continue
            previous = events[-1] if events else None
            previous_time = as_utc(previous.get("event_time")) if previous else None
            previous_text = str(previous.get("_text_key") or "") if previous else ""
            event_time = as_utc(item.get("event_time"))
            if (
                event_time
                and previous_time
                and event_time - previous_time <= timedelta(hours=6)
                and text_key
                and previous_text
                and SequenceMatcher(None, text_key, previous_text).ratio() >= 0.82
            ):
                events[-1] = {
                    "event_time": iso(event_time),
                    "source": "reset_confirmed_tweet",
                    "evidence_tweet_id": evidence_id or None,
                    "notes": "Derived from the latest final reset_confirmed Tweet; a near-duplicate confirmation was collapsed.",
                    "_text_key": text_key,
                }
                continue
            if evidence_id:
                seen_ids.add(evidence_id)
            if text_key:
                seen_text.add(text_key)
            events.append(
                {
                    "event_time": iso(event_time),
                    "source": "reset_confirmed_tweet",
                    "evidence_tweet_id": evidence_id or None,
                    "notes": "Derived from the latest final reset_confirmed Tweet; no explicit reset_event was recorded.",
                    "_text_key": text_key,
                }
            )

    events.sort(key=lambda item: as_utc(item.get("event_time")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    previous_time: datetime | None = None
    for event in reversed(events):
        event.pop("_text_key", None)
        event_time = as_utc(event["event_time"])
        local_date, beijing_time = _beijing_parts(event_time)
        event["beijing_date"] = local_date
        event["beijing_time"] = beijing_time
        event["interval_seconds"] = (event_time - previous_time).total_seconds() if previous_time else None
        event["interval_label"] = _interval_label(event["interval_seconds"])
        previous_time = event_time
    return events


TIME_RE = re.compile(
    r"(?:at|around|by)\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<ampm>a\.?m\.?|p\.?m\.?)?\s*(?P<zone>PST|PDT|PT)?"
    r"(?:\s+(?P<day>today|tomorrow))?",
    re.IGNORECASE,
)


def parse_announcement_time(text: str, published_at: datetime | str | None) -> datetime | None:
    """Parse a conservative explicit clock announcement into UTC.

    The parser intentionally returns None for vague phrases such as
    "during the day". It supports the common PST/PDT/PT forms in the source
    Tweets and normalizes malformed but unambiguous forms such as "14pm".
    """

    published = as_utc(published_at)
    if not published:
        return None
    match = TIME_RE.search(text or "")
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").lower().replace(".", "")
    if hour > 23 or minute > 59:
        return None
    if hour <= 12 and ampm == "pm":
        hour += 12
    elif hour == 12 and ampm == "am":
        hour = 0
    # A 24-hour value with a stray "pm" is treated as the 24-hour value.
    offset = {"pst": -8, "pdt": -7, "pt": -7}.get((match.group("zone") or "").lower(), 0)
    tz = timezone(timedelta(hours=offset), name=(match.group("zone") or "UTC").upper())
    local_published = published.astimezone(tz)
    target_date = local_published.date()
    day_word = (match.group("day") or "").lower()
    if day_word == "tomorrow":
        target_date += timedelta(days=1)
    target = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=hour, minute=minute)
    if not day_word and target <= local_published:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def build_forecast(
    reset_history: list[dict[str, Any]],
    hints: Iterable[dict[str, Any]],
    announcements: Iterable[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    current = as_utc(now) or datetime.now(timezone.utc)
    last_reset = as_utc(reset_history[0]["event_time"]) if reset_history else None
    baseline = last_reset + timedelta(days=7) if last_reset else None
    announcement_target: datetime | None = None
    announcement_source: dict[str, Any] | None = None
    for item in sorted(
        announcements,
        key=lambda value: as_utc(value.get("event_time")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    ):
        target = parse_announcement_time(str(item.get("text") or ""), item.get("event_time"))
        if target and target > current:
            announcement_target = target
            announcement_source = item
            break

    hint_source: dict[str, Any] | None = None
    for item in sorted(
        hints,
        key=lambda value: as_utc(value.get("event_time")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    ):
        event_time = as_utc(item.get("event_time"))
        if event_time and str(item.get("urgency") or "") == "within_24h" and event_time + timedelta(hours=36) > current:
            hint_source = item
            break

    if announcement_target:
        estimate = announcement_target
        source = "reset_announcement"
        reason = "Explicit reset announcement time parsed from a Tweet."
        signal_window = "explicit_time"
    elif hint_source:
        estimate = max(current, as_utc(hint_source.get("event_time")) or current) + timedelta(hours=24)
        source = "reset_hint"
        reason = "Active reset_hint with within_24h urgency takes priority over the weekly baseline."
        signal_window = "within_24h"
    else:
        estimate = baseline
        source = "weekly_baseline" if baseline else "no_confirmed_reset"
        reason = "Last confirmed reset + 7 days." if baseline else "No confirmed Reset event is available."
        signal_window = None

    return {
        "last_reset_at": iso(last_reset),
        "last_reset_source": reset_history[0].get("source") if reset_history else None,
        "last_reset_evidence_tweet_id": reset_history[0].get("evidence_tweet_id") if reset_history else None,
        "baseline_next_reset_at": iso(baseline),
        "signal_window": signal_window,
        "estimated_next_reset_at": iso(estimate),
        "forecast_source": source,
        "forecast_reason": reason,
        "active_signal_tweet_id": (announcement_source or hint_source or {}).get("evidence_tweet_id"),
    }


def derive_usage_advice(
    radar_state: str | None,
    forecast: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, str]:
    current = as_utc(now) or datetime.now(timezone.utc)
    state = (radar_state or "UNKNOWN").upper()
    estimate = as_utc(forecast.get("estimated_next_reset_at"))
    hours_until = (estimate - current).total_seconds() / 3600 if estimate else None
    if state == "CONFIRMED":
        return {"level": "GREEN", "title_code": "reset_confirmed", "reason_code": "confirmed"}
    if state in {"IMMINENT", "ANNOUNCED"}:
        return {"level": "RED", "title_code": "use_soon", "reason_code": "radar_urgent"}
    if state == "LIKELY" or (hours_until is not None and hours_until <= 24):
        return {"level": "ORANGE", "title_code": "prioritize_usage", "reason_code": "signal_within_24h"}
    if state == "WATCH" or (hours_until is not None and hours_until <= 48):
        return {"level": "YELLOW", "title_code": "speed_up_gently", "reason_code": "watch_or_baseline_near"}
    return {"level": "GREEN", "title_code": "normal_usage", "reason_code": "no_immediate_signal"}


__all__ = [
    "RESET_SIGNAL_CATEGORIES",
    "as_utc",
    "build_forecast",
    "build_reset_history",
    "derive_usage_advice",
    "iso",
    "parse_announcement_time",
]
