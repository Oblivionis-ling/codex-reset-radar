from __future__ import annotations

from .adapters import (
    IyuuAdapter,
    NotificationAdapter,
    PushPlusAdapter,
    ServerChanAdapter,
    ShowDocAdapter,
    WPushAdapter,
    WxPusherAdapter,
)
from .config import NotificationSettings
from .email import SmtpEmailAdapter
from .transport import HttpTransport


CHANNELS = (
    "pushplus_wechat",
    "pushplus_clawbot",
    "serverchan_wechat",
    "iyuu_wechat",
    "wpush_wechat",
    "wpush_clawbot",
    "wxpusher",
    "showdoc_wechat",
    "smtp_email",
)


def missing_configuration(channel: str, settings: NotificationSettings) -> list[str]:
    fields = {
        "pushplus_wechat": [("PUSHPLUS_TOKEN", settings.pushplus_token)],
        "pushplus_clawbot": [("PUSHPLUS_TOKEN", settings.pushplus_token)],
        "serverchan_wechat": [("SERVERCHAN_SENDKEY", settings.serverchan_sendkey)],
        "iyuu_wechat": [("IYUU_TOKEN", settings.iyuu_token)],
        "wpush_wechat": [("WPUSH_API_KEY", settings.wpush_api_key)],
        "wpush_clawbot": [("WPUSH_API_KEY", settings.wpush_api_key)],
        "wxpusher": [
            ("WXPUSHER_APP_TOKEN", settings.wxpusher_app_token),
            ("WXPUSHER_UID", settings.wxpusher_uid),
        ],
        "showdoc_wechat": [("SHOWDOC_PUSH_TOKEN", settings.showdoc_push_token)],
    }
    if channel == "smtp_email":
        return settings.validate_smtp()
    if channel not in fields:
        return [f"unsupported channel: {channel}"]
    return [name for name, value in fields[channel] if not value]


def build_adapter(
    channel: str,
    settings: NotificationSettings,
    transport: HttpTransport | None,
    *,
    network_enabled: bool,
) -> NotificationAdapter:
    missing = missing_configuration(channel, settings)
    if missing:
        raise ValueError("missing configuration: " + ", ".join(missing))
    if channel == "smtp_email":
        return SmtpEmailAdapter(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=settings.smtp_from,
            recipient=settings.smtp_to,
            security=settings.smtp_security,
            timeout_seconds=settings.timeout_seconds,
            network_enabled=network_enabled,
        )
    if transport is None:
        raise ValueError("HTTP transport is required")
    if channel == "pushplus_wechat":
        return PushPlusAdapter(transport, settings.pushplus_token)
    if channel == "pushplus_clawbot":
        return PushPlusAdapter(
            transport, settings.pushplus_token, channel_name="clawbot", channel="pushplus_clawbot"
        )
    if channel == "serverchan_wechat":
        return ServerChanAdapter(transport, settings.serverchan_sendkey)
    if channel == "iyuu_wechat":
        return IyuuAdapter(transport, settings.iyuu_token)
    if channel == "wpush_wechat":
        return WPushAdapter(transport, settings.wpush_api_key)
    if channel == "wpush_clawbot":
        return WPushAdapter(
            transport, settings.wpush_api_key, channel_name="clawbot", channel="wpush_clawbot"
        )
    if channel == "wxpusher":
        return WxPusherAdapter(transport, settings.wxpusher_app_token, settings.wxpusher_uid)
    if channel == "showdoc_wechat":
        return ShowDocAdapter(transport, settings.showdoc_push_token)
    raise ValueError(f"unsupported channel: {channel}")
