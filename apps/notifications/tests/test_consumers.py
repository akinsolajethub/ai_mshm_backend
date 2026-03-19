"""
apps/notifications/tests/test_consumers.py
────────────────────────────────────────────
Tests for the WebSocket NotificationConsumer.
Uses channels.testing.WebsocketCommunicator.
"""
import json
import pytest
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.notifications.consumers import NotificationConsumer
from apps.notifications.models import Notification

User = get_user_model()

# Use in-memory channel layer for tests (no Redis needed)
TEST_CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}


async def _make_communicator(user=None):
    """Build a WebsocketCommunicator with user injected into scope."""
    communicator = WebsocketCommunicator(
        NotificationConsumer.as_asgi(),
        "/ws/notifications/",
    )
    if user:
        communicator.scope["user"] = user
    return communicator


@pytest.fixture
def patient(db):
    return User.objects.create_user(
        email="ws_patient@test.com",
        full_name="WS Patient",
        password="TestPass1234!",
        role="patient",
        is_email_verified=True,
    )


# ── Connection tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
async def test_authenticated_user_can_connect(patient):
    communicator = await _make_communicator(user=patient)
    connected, _ = await communicator.connect()
    assert connected is True

    # Should immediately receive unread_count message
    response = await communicator.receive_json_from()
    assert response["type"] == "unread_count"
    assert "count" in response

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
async def test_anonymous_user_rejected():
    from django.contrib.auth.models import AnonymousUser
    communicator = await _make_communicator(user=AnonymousUser())
    connected, code = await communicator.connect()
    assert connected is False
    assert code == 4001


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
async def test_no_user_in_scope_rejected():
    communicator = await _make_communicator(user=None)
    connected, code = await communicator.connect()
    assert connected is False


# ── Unread count on connect ───────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
async def test_unread_count_reflects_db(patient):
    # Create 2 unread notifications
    from channels.db import database_sync_to_async

    @database_sync_to_async
    def create_notifications():
        for i in range(2):
            Notification.objects.create(
                recipient=patient,
                notification_type=Notification.NotificationType.SYSTEM,
                title=f"Test {i}",
                body="Body",
                is_read=False,
            )

    await create_notifications()

    communicator = await _make_communicator(user=patient)
    await communicator.connect()
    response = await communicator.receive_json_from()

    assert response["type"] == "unread_count"
    assert response["count"] == 2
    await communicator.disconnect()


# ── Mark read via WebSocket ───────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
async def test_mark_read_action(patient):
    from channels.db import database_sync_to_async

    @database_sync_to_async
    def create_notification():
        return Notification.objects.create(
            recipient=patient,
            notification_type=Notification.NotificationType.SYSTEM,
            title="To be read",
            body="Body",
            is_read=False,
        )

    notif = await create_notification()

    communicator = await _make_communicator(user=patient)
    await communicator.connect()
    await communicator.receive_json_from()  # consume unread_count

    await communicator.send_json_to({
        "action": "mark_read",
        "notification_id": notif.pk,
    })

    response = await communicator.receive_json_from()
    assert response["type"] == "marked_read"
    assert response["notification_id"] == notif.pk

    # Verify DB updated
    @database_sync_to_async
    def check_db():
        return Notification.objects.get(pk=notif.pk).is_read

    assert await check_db() is True
    await communicator.disconnect()


# ── Mark all read via WebSocket ───────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
async def test_mark_all_read_action(patient):
    from channels.db import database_sync_to_async

    @database_sync_to_async
    def create_notifications():
        for i in range(3):
            Notification.objects.create(
                recipient=patient,
                notification_type=Notification.NotificationType.SYSTEM,
                title=f"Notif {i}",
                body="Body",
                is_read=False,
            )

    await create_notifications()

    communicator = await _make_communicator(user=patient)
    await communicator.connect()
    await communicator.receive_json_from()  # consume unread_count

    await communicator.send_json_to({"action": "mark_all_read"})
    response = await communicator.receive_json_from()

    assert response["type"] == "all_marked_read"
    assert response["count"] == 3

    @database_sync_to_async
    def check_unread():
        return Notification.objects.filter(recipient=patient, is_read=False).count()

    assert await check_unread() == 0
    await communicator.disconnect()
