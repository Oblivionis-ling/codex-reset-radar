from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable

from .models import DeliveryState, NotificationMessage, NotificationResult
from .security import safe_detail
from .transport import NetworkDisabledError


SmtpFactory = Callable[..., smtplib.SMTP]


@dataclass
class SmtpEmailAdapter:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str
    security: str = "starttls"
    timeout_seconds: float = 10.0
    network_enabled: bool = False
    smtp_factory: SmtpFactory = smtplib.SMTP
    smtp_ssl_factory: SmtpFactory = smtplib.SMTP_SSL
    ssl_context_factory: Callable[[], ssl.SSLContext] = ssl.create_default_context
    channel: str = "smtp_email"

    def build_message(self, message: NotificationMessage) -> EmailMessage:
        current = message.clipped(title_limit=255, body_limit=50_000)
        email = EmailMessage()
        email["Subject"] = current.title
        email["From"] = self.sender
        email["To"] = self.recipient
        suffix = f"\n\n本地 Dashboard：{current.url}" if current.url else ""
        email.set_content(current.body + suffix)
        return email

    async def send(self, message: NotificationMessage) -> NotificationResult:
        if not self.network_enabled:
            raise NetworkDisabledError("SMTP network access is disabled")
        if self.security not in {"starttls", "ssl"}:
            return NotificationResult(self.channel, DeliveryState.FAILED, False, detail="plaintext SMTP is forbidden")
        return await asyncio.to_thread(self._send_sync, self.build_message(message))

    def _send_sync(self, message: EmailMessage) -> NotificationResult:
        client: smtplib.SMTP | None = None
        secrets = (self.username, self.password)
        try:
            context = self.ssl_context_factory()
            if self.security == "ssl":
                client = self.smtp_ssl_factory(self.host, self.port, timeout=self.timeout_seconds, context=context)
            else:
                client = self.smtp_factory(self.host, self.port, timeout=self.timeout_seconds)
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            client.login(self.username, self.password)
            client.send_message(message)
            return NotificationResult(
                self.channel,
                DeliveryState.ACCEPTED,
                True,
                detail="SMTP server accepted the message; user receipt still requires observation",
            )
        except smtplib.SMTPAuthenticationError as error:
            detail = f"authentication failed ({getattr(error, 'smtp_code', 'unknown')})"
        except smtplib.SMTPRecipientsRefused:
            detail = "recipient refused"
        except ssl.SSLError as error:
            detail = f"TLS failure: {type(error).__name__}"
        except (TimeoutError, smtplib.SMTPServerDisconnected) as error:
            detail = f"SMTP timeout/disconnect: {type(error).__name__}"
        except (OSError, smtplib.SMTPException) as error:
            detail = f"SMTP failure: {safe_detail(type(error).__name__, secrets)}"
        finally:
            if client is not None:
                try:
                    client.quit()
                except (OSError, smtplib.SMTPException):
                    pass
        return NotificationResult(self.channel, DeliveryState.FAILED, False, detail=detail)
