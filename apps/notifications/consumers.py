"""
apps/notifications/consumers.py
────────────────────────────────
WebSocket consumer for real-time in-app notifications.
Each authenticated user connects to their personal channel group.

Connection: ws(s)://host/ws/notifications/?token=<access_token>
"""
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


def _user_group_name(user_id) -> str:
    return f"notifications_user_{user_id}"


class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = self.scope.get("user")

        if not user or isinstance(user, AnonymousUser):
            logger.warning("WebSocket connection rejected – unauthenticated")
            await self.close(code=4001)
            return

        self.user     = user
        self.group_name = _user_group_name(user.id)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send unread count immediately on connect
        unread_count = await self._get_unread_count()
        await self.send(text_data=json.dumps({"type": "unread_count", "count": unread_count}))
        logger.info("WS connected: user=%s group=%s", user.email, self.group_name)

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """Handle incoming messages from the client."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        action = data.get("action")

        if action == "mark_read":
            notification_id = data.get("notification_id")
            if notification_id:
                await self._mark_notification_read(notification_id)
                await self.send(text_data=json.dumps({
                    "type": "marked_read",
                    "notification_id": notification_id,
                }))

        elif action == "mark_all_read":
            count = await self._mark_all_read()
            await self.send(text_data=json.dumps({
                "type": "all_marked_read",
                "count": count,
            }))

    # ── Group message handlers (called by channel layer) ──────────────────────

    async def notification_message(self, event):
        """Relay a new notification pushed from server → this user's WebSocket."""
        await self.send(text_data=json.dumps({
            "type": "new_notification",
            "notification": event["notification"],
        }))

    # ── DB helpers (sync → async) ─────────────────────────────────────────────

    @database_sync_to_async
    def _get_unread_count(self) -> int:
        from .models import Notification
        return Notification.objects.filter(recipient=self.user, is_read=False).count()

    @database_sync_to_async
    def _mark_notification_read(self, notification_id: int):
        from .models import Notification
        try:
            n = Notification.objects.get(id=notification_id, recipient=self.user)
            n.mark_read()
        except Notification.DoesNotExist:
            pass

    @database_sync_to_async
    def _mark_all_read(self) -> int:
        from .models import Notification
        from django.utils import timezone
        qs = Notification.objects.filter(recipient=self.user, is_read=False)
        count = qs.count()
        qs.update(is_read=True, read_at=timezone.now())
        return count
