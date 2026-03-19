"""
apps/notifications/services.py
───────────────────────────────
Centralised service for creating and dispatching notifications.
Call NotificationService.send() from anywhere — it persists the
notification to DB and immediately pushes it over WebSocket.
"""
import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model

from .models import Notification

logger = logging.getLogger(__name__)
User = get_user_model()


def _user_group_name(user_id) -> str:
    return f"notifications_user_{user_id}"


class NotificationService:

    @staticmethod
    def send(
        recipient: User,
        notification_type: str,
        title: str,
        body: str,
        priority: str = Notification.Priority.MEDIUM,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        """
        Persist a notification and push it to the user's WebSocket channel.
        Safe to call from sync code (Celery tasks, views, signals).
        """
        notif = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            body=body,
            priority=priority,
            data=data or {},
        )

        # Push over WebSocket (non-blocking — fires and forgets)
        NotificationService._push_to_channel(notif)
        logger.info("Notification sent: type=%s user=%s", notification_type, recipient.email)
        return notif

    @staticmethod
    def _push_to_channel(notif: Notification):
        """Fire notification over WebSocket channel layer."""
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = _user_group_name(notif.recipient_id)
        payload = {
            "type": "notification.message",
            "notification": {
                "id": notif.id,
                "notification_type": notif.notification_type,
                "priority": notif.priority,
                "title": notif.title,
                "body": notif.body,
                "data": notif.data,
                "is_read": notif.is_read,
                "created_at": notif.created_at.isoformat(),
            },
        }
        try:
            async_to_sync(channel_layer.group_send)(group_name, payload)
        except Exception as e:
            logger.warning("WebSocket push failed for user %s: %s", notif.recipient_id, e)
