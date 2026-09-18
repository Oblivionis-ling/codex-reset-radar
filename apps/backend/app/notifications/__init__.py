"""Notification preparation primitives for the V2 Backend.

The package is deliberately not wired to Reset/Judge events yet.  The only
live entry point is the explicit, interactive local test command.
"""

from .config import NotificationSettings, load_notification_settings
from .models import DeliveryState, NotificationMessage, NotificationResult
from .service import NotificationDispatcher

__all__ = [
    "DeliveryState",
    "NotificationDispatcher",
    "NotificationMessage",
    "NotificationResult",
    "NotificationSettings",
    "load_notification_settings",
]
