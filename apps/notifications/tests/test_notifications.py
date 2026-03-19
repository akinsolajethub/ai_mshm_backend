"""
apps/notifications/tests/test_notifications.py
────────────────────────────────────────────────
Tests for REST notification endpoints and the NotificationService.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.notifications.models import Notification
from apps.notifications.services import NotificationService

User = get_user_model()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="patient@test.com",
        full_name="Test Patient",
        password="TestPass1234!",
        role="patient",
        is_email_verified=True,
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        email="other@test.com",
        full_name="Other Patient",
        password="TestPass1234!",
        role="patient",
        is_email_verified=True,
    )


@pytest.fixture
def auth_client(api_client, user):
    url = reverse("v1:accounts:login")
    resp = api_client.post(url, {
        "email": "patient@test.com",
        "password": "TestPass1234!",
    }, format="json")
    token = resp.data["data"]["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


@pytest.fixture
def notification(db, user):
    return Notification.objects.create(
        recipient=user,
        notification_type=Notification.NotificationType.SYSTEM,
        title="Test notification",
        body="This is a test.",
        priority=Notification.Priority.MEDIUM,
    )


# ── NotificationService ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNotificationService:

    def test_send_creates_notification(self, user):
        notif = NotificationService.send(
            recipient=user,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Test",
            body="Test body",
        )
        assert notif.pk is not None
        assert notif.recipient == user
        assert notif.is_read is False

    def test_send_with_extra_data(self, user):
        notif = NotificationService.send(
            recipient=user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
            title="Risk changed",
            body="Your risk score changed.",
            data={"score": 72, "previous": 55},
        )
        assert notif.data["score"] == 72

    def test_send_high_priority(self, user):
        notif = NotificationService.send(
            recipient=user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
            title="Critical alert",
            body="Urgent.",
            priority=Notification.Priority.HIGH,
        )
        assert notif.priority == Notification.Priority.HIGH


# ── REST Endpoints ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNotificationList:

    url = reverse("v1:notifications:list")

    def test_list_own_notifications(self, auth_client, user, notification):
        resp = auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["meta"]["count"] >= 1

    def test_cannot_see_other_users_notifications(self, auth_client, other_user):
        Notification.objects.create(
            recipient=other_user,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Private",
            body="Not yours.",
        )
        resp = auth_client.get(self.url)
        for item in resp.data["data"]:
            assert item["title"] != "Private"

    def test_unread_only_filter(self, auth_client, user):
        # Create one read and one unread
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Read",
            body="Already read.",
            is_read=True,
        )
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Unread",
            body="Not yet read.",
            is_read=False,
        )
        resp = auth_client.get(self.url + "?unread_only=true")
        assert resp.status_code == status.HTTP_200_OK
        for item in resp.data["data"]:
            assert item["is_read"] is False

    def test_list_unauthenticated(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestUnreadCount:

    url = reverse("v1:notifications:unread-count")

    def test_unread_count_correct(self, auth_client, user):
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.NotificationType.SYSTEM,
            title="A", body="B", is_read=False,
        )
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.NotificationType.SYSTEM,
            title="C", body="D", is_read=True,
        )
        resp = auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["unread_count"] == 1


@pytest.mark.django_db
class TestMarkRead:

    def test_mark_single_read(self, auth_client, user, notification):
        url = reverse("v1:notifications:mark-read", kwargs={"pk": notification.pk})
        resp = auth_client.patch(url)
        assert resp.status_code == status.HTTP_200_OK
        notification.refresh_from_db()
        assert notification.is_read is True
        assert notification.read_at is not None

    def test_cannot_mark_others_notification(self, auth_client, other_user):
        other_notif = Notification.objects.create(
            recipient=other_user,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Other", body="Not mine.",
        )
        url = reverse("v1:notifications:mark-read", kwargs={"pk": other_notif.pk})
        resp = auth_client.patch(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_mark_all_read(self, auth_client, user):
        for i in range(3):
            Notification.objects.create(
                recipient=user,
                notification_type=Notification.NotificationType.SYSTEM,
                title=f"Notif {i}", body="Body",
            )
        url = reverse("v1:notifications:mark-all-read")
        resp = auth_client.patch(url)
        assert resp.status_code == status.HTTP_200_OK
        assert Notification.objects.filter(recipient=user, is_read=False).count() == 0


@pytest.mark.django_db
class TestDeleteNotification:

    def test_delete_own_notification(self, auth_client, user, notification):
        url = reverse("v1:notifications:delete", kwargs={"pk": notification.pk})
        resp = auth_client.delete(url)
        assert resp.status_code == status.HTTP_200_OK
        assert not Notification.objects.filter(pk=notification.pk).exists()

    def test_cannot_delete_others_notification(self, auth_client, other_user):
        other_notif = Notification.objects.create(
            recipient=other_user,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Other", body="Not mine.",
        )
        url = reverse("v1:notifications:delete", kwargs={"pk": other_notif.pk})
        resp = auth_client.delete(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND
