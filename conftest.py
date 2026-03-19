"""
conftest.py
────────────
Root pytest configuration.
Shared fixtures and factory-boy factories available to all test modules.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


# ── APIClient fixture ─────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    return APIClient()


# ── User factories ────────────────────────────────────────────────────────────

@pytest.fixture
def make_user(db):
    """
    Factory fixture for creating users with sensible defaults.

    Usage:
        def test_something(make_user):
            patient   = make_user()
            clinician = make_user(role="clinician", email="doc@test.com")
            unverified = make_user(is_email_verified=False)
    """
    def factory(
        email: str = "user@test.com",
        full_name: str = "Test User",
        password: str = "TestPass1234!",
        role: str = "patient",
        is_email_verified: bool = True,
        onboarding_completed: bool = False,
        **kwargs,
    ):
        return User.objects.create_user(
            email=email,
            full_name=full_name,
            password=password,
            role=role,
            is_email_verified=is_email_verified,
            onboarding_completed=onboarding_completed,
            **kwargs,
        )

    return factory


@pytest.fixture
def patient(make_user):
    return make_user(email="patient@test.com", role="patient")


@pytest.fixture
def clinician(make_user):
    return make_user(email="clinician@test.com", role="clinician", full_name="Dr. Test")


@pytest.fixture
def unverified_patient(make_user):
    return make_user(
        email="unverified@test.com",
        is_email_verified=False,
    )


# ── Authenticated client fixture ──────────────────────────────────────────────

@pytest.fixture
def auth_client_for(api_client):
    """
    Returns a function that authenticates an APIClient as the given user.

    Usage:
        def test_something(auth_client_for, patient):
            client = auth_client_for(patient, "TestPass1234!")
            resp = client.get("/api/v1/auth/me/")
    """
    from django.urls import reverse

    def _auth(user, password: str = "TestPass1234!"):
        resp = api_client.post(
            reverse("v1:accounts:login"),
            {"email": user.email, "password": password},
            format="json",
        )
        assert resp.status_code == 200, f"Login failed for {user.email}: {resp.data}"
        token = resp.data["data"]["access"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    return _auth


# ── Notification factory ──────────────────────────────────────────────────────

@pytest.fixture
def make_notification(db):
    """
    Factory for creating test notifications.

    Usage:
        def test_something(make_notification, patient):
            notif = make_notification(recipient=patient, title="Hello")
    """
    from apps.notifications.models import Notification

    def factory(
        recipient=None,
        notification_type: str = Notification.NotificationType.SYSTEM,
        title: str = "Test Notification",
        body: str = "Test body.",
        priority: str = Notification.Priority.MEDIUM,
        is_read: bool = False,
        data: dict = None,
    ):
        return Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            body=body,
            priority=priority,
            is_read=is_read,
            data=data or {},
        )

    return factory


# ── Device factory ────────────────────────────────────────────────────────────

@pytest.fixture
def make_device(db):
    """
    Factory for creating connected devices.

    Usage:
        def test_something(make_device, patient):
            device = make_device(user=patient, device_type="apple_watch")
    """
    from apps.settings_app.models import ConnectedDevice

    def factory(
        user=None,
        device_type: str = ConnectedDevice.DeviceType.APPLE_WATCH,
        device_name: str = "Apple Watch",
        sync_frequency: str = ConnectedDevice.SyncFrequency.FIFTEEN_MIN,
        background_sync: bool = True,
        is_connected: bool = True,
    ):
        return ConnectedDevice.objects.create(
            user=user,
            device_type=device_type,
            device_name=device_name,
            sync_frequency=sync_frequency,
            background_sync=background_sync,
            is_connected=is_connected,
        )

    return factory
