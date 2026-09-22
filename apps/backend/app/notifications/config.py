from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from ..config import REPOSITORY_ROOT


def _value(name: str) -> str:
    return os.getenv(name, "").strip()


def _port(name: str, default: int) -> int:
    try:
        return max(1, min(65535, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


@dataclass(frozen=True)
class NotificationSettings:
    pushplus_token: str = ""
    serverchan_sendkey: str = ""
    iyuu_token: str = ""
    wpush_api_key: str = ""
    wxpusher_app_token: str = ""
    wxpusher_uid: str = ""
    showdoc_push_token: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_security: str = "starttls"
    timeout_seconds: float = 10.0
    http_retries: int = 1
    ledger_path: Path = REPOSITORY_ROOT / "runtime/notifications/notification-deliveries.db"

    def channel_status(self) -> dict[str, str]:
        configured = lambda value: "CONFIGURED_WAITING_MANUAL_TEST" if value else "NEEDS_USER_SETUP"
        return {
            "pushplus_wechat": configured(self.pushplus_token),
            "pushplus_clawbot": configured(self.pushplus_token),
            "serverchan_wechat": configured(self.serverchan_sendkey),
            "iyuu_wechat": configured(self.iyuu_token),
            "wpush_wechat": configured(self.wpush_api_key),
            "wpush_clawbot": configured(self.wpush_api_key),
            "wxpusher": configured(self.wxpusher_app_token and self.wxpusher_uid),
            "showdoc_wechat": configured(self.showdoc_push_token),
            "smtp_email": configured(
                self.smtp_host and self.smtp_from and self.smtp_to and self.smtp_username and self.smtp_password
            ),
        }

    def validate_smtp(self) -> list[str]:
        missing = [
            name
            for name, value in (
                ("CRR_SMTP_HOST", self.smtp_host),
                ("CRR_SMTP_USERNAME", self.smtp_username),
                ("CRR_SMTP_PASSWORD", self.smtp_password),
                ("CRR_SMTP_FROM", self.smtp_from),
                ("CRR_SMTP_TO", self.smtp_to),
            )
            if not value
        ]
        if self.smtp_security not in {"starttls", "ssl"}:
            missing.append("CRR_SMTP_SECURITY must be starttls or ssl")
        return missing


def load_notification_settings() -> NotificationSettings:
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    ledger = Path(_value("CRR_NOTIFICATION_LEDGER") or "runtime/notifications/notification-deliveries.db")
    if not ledger.is_absolute():
        ledger = REPOSITORY_ROOT / ledger
    try:
        timeout = max(2.0, min(60.0, float(os.getenv("CRR_NOTIFICATION_TIMEOUT_SECONDS", "10"))))
    except ValueError:
        timeout = 10.0
    try:
        retries = max(0, min(2, int(os.getenv("CRR_NOTIFICATION_HTTP_RETRIES", "1"))))
    except ValueError:
        retries = 1
    return NotificationSettings(
        pushplus_token=_value("PUSHPLUS_TOKEN"),
        serverchan_sendkey=_value("SERVERCHAN_SENDKEY"),
        iyuu_token=_value("IYUU_TOKEN"),
        wpush_api_key=_value("WPUSH_API_KEY"),
        wxpusher_app_token=_value("WXPUSHER_APP_TOKEN"),
        wxpusher_uid=_value("WXPUSHER_UID"),
        showdoc_push_token=_value("SHOWDOC_PUSH_TOKEN"),
        smtp_host=_value("CRR_SMTP_HOST"),
        smtp_port=_port("CRR_SMTP_PORT", 587),
        smtp_username=_value("CRR_SMTP_USERNAME"),
        smtp_password=_value("CRR_SMTP_PASSWORD"),
        smtp_from=_value("CRR_SMTP_FROM"),
        smtp_to=_value("CRR_SMTP_TO"),
        smtp_security=(_value("CRR_SMTP_SECURITY") or "starttls").lower(),
        timeout_seconds=timeout,
        http_retries=retries,
        ledger_path=ledger,
    )
