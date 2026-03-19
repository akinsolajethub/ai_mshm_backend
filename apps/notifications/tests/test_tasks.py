"""
apps/notifications/tests/test_tasks.py
────────────────────────────────────────
Tests for Celery notification tasks.
Uses @pytest.mark.django_db and mocks the channel layer push.
"""
import pytest
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.tasks import (
    send_morning_checkin_reminders,
    send_evening_checkin_reminders,
    send_weekly_tool_prompts,
    notify_risk_score_change,
    check_stale_wearable_syncs,
)
from apps.settings_app.models import NotificationPreferences, ConnectedDevice

User = get_user_model()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def active_patient(db):
    return User.objects.create_user(
        email="patient@test.com",
        full_name="Test Patient",
        password="TestPass1234!",
        role="patient",
        is_email_verified=True,
        onboarding_completed=True,
    )


@pytest.fixture
def prefs(db, active_patient):
    now_time = timezone.now().strftime("%H:%M")
    prefs, _ = NotificationPreferences.objects.get_or_create(
        user=active_patient,
        defaults={
            "morning_time": now_time,
            "evening_time": now_time,
            "morning_checkin_enabled": True,
            "evening_checkin_enabled": True,
            "weekly_prompts_enabled": True,
            "risk_score_updates_enabled": True,
            "wearable_sync_reminders": True,
            "do_not_disturb": False,
        },
    )
    return prefs


# ── Morning check-in ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestMorningCheckinTask:

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_sends_to_eligible_users(self, mock_push, prefs, active_patient):
        count = send_morning_checkin_reminders()
        assert count >= 1
        assert Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.MORNING_CHECKIN,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_skips_dnd_users(self, mock_push, prefs, active_patient):
        prefs.do_not_disturb = True
        prefs.save()
        initial_count = Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.MORNING_CHECKIN,
        ).count()
        send_morning_checkin_reminders()
        final_count = Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.MORNING_CHECKIN,
        ).count()
        assert final_count == initial_count  # no new notification

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_skips_unverified_users(self, mock_push, db):
        user = User.objects.create_user(
            email="unverified@test.com",
            full_name="Unverified",
            password="Pass1234!",
            is_email_verified=False,
            onboarding_completed=True,
        )
        now_time = timezone.now().strftime("%H:%M")
        NotificationPreferences.objects.create(
            user=user,
            morning_time=now_time,
            morning_checkin_enabled=True,
            do_not_disturb=False,
        )
        count = send_morning_checkin_reminders()
        # Unverified user should not get notification
        assert not Notification.objects.filter(
            recipient=user,
            notification_type=Notification.NotificationType.MORNING_CHECKIN,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_skips_incomplete_onboarding(self, mock_push, db):
        user = User.objects.create_user(
            email="incomplete@test.com",
            full_name="Incomplete",
            password="Pass1234!",
            is_email_verified=True,
            onboarding_completed=False,
        )
        now_time = timezone.now().strftime("%H:%M")
        NotificationPreferences.objects.create(
            user=user,
            morning_time=now_time,
            morning_checkin_enabled=True,
            do_not_disturb=False,
        )
        send_morning_checkin_reminders()
        assert not Notification.objects.filter(
            recipient=user,
            notification_type=Notification.NotificationType.MORNING_CHECKIN,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_wrong_time_not_triggered(self, mock_push, active_patient):
        prefs, _ = NotificationPreferences.objects.get_or_create(
            user=active_patient,
            defaults={
                "morning_time": "03:00",   # middle of night — won't match now
                "morning_checkin_enabled": True,
                "do_not_disturb": False,
            },
        )
        prefs.morning_time = "03:00"
        prefs.save()
        count = send_morning_checkin_reminders()
        assert not Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.MORNING_CHECKIN,
        ).exists()


# ── Evening check-in ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestEveningCheckinTask:

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_sends_to_eligible_users(self, mock_push, prefs, active_patient):
        count = send_evening_checkin_reminders()
        assert count >= 1
        assert Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.EVENING_CHECKIN,
        ).exists()


# ── Weekly prompts ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestWeeklyPromptsTask:

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_sends_weekly_prompt(self, mock_push, prefs, active_patient):
        count = send_weekly_tool_prompts()
        assert count >= 1
        assert Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.WEEKLY_PROMPT,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_skips_users_with_toggle_off(self, mock_push, prefs, active_patient):
        prefs.weekly_prompts_enabled = False
        prefs.save()
        send_weekly_tool_prompts()
        assert not Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.WEEKLY_PROMPT,
        ).exists()


# ── Risk score change ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRiskScoreChangeTask:

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_sends_risk_notification(self, mock_push, active_patient, prefs):
        notify_risk_score_change(
            user_id=active_patient.pk,
            new_score=72,
            previous_score=45,
            condition="pcos",
        )
        notif = Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.RISK_UPDATE,
        ).first()
        assert notif is not None
        assert notif.data["new_score"] == 72
        assert notif.data["previous_score"] == 45
        assert notif.data["condition"] == "pcos"

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_high_priority_on_large_delta(self, mock_push, active_patient, prefs):
        notify_risk_score_change(
            user_id=active_patient.pk,
            new_score=80,
            previous_score=50,   # delta = 30 → HIGH priority
            condition="cardiovascular",
        )
        notif = Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.RISK_UPDATE,
        ).first()
        assert notif.priority == Notification.Priority.HIGH

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_medium_priority_on_small_delta(self, mock_push, active_patient, prefs):
        notify_risk_score_change(
            user_id=active_patient.pk,
            new_score=52,
            previous_score=45,   # delta = 7 → MEDIUM priority
            condition="maternal",
        )
        notif = Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.RISK_UPDATE,
        ).first()
        assert notif.priority == Notification.Priority.MEDIUM

    def test_silently_ignores_unknown_user(self):
        """Should not raise, just log and return."""
        result = notify_risk_score_change(
            user_id=99999,
            new_score=60,
            previous_score=40,
            condition="pcos",
        )
        assert result is None

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_skips_user_with_toggle_off(self, mock_push, active_patient, prefs):
        prefs.risk_score_updates_enabled = False
        prefs.save()
        notify_risk_score_change(
            user_id=active_patient.pk,
            new_score=75,
            previous_score=50,
            condition="pcos",
        )
        assert not Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.RISK_UPDATE,
        ).exists()


# ── Stale wearable sync ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStaleWearableSyncTask:

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_notifies_stale_device_users(self, mock_push, active_patient, prefs):
        from datetime import timedelta
        prefs.wearable_sync_reminders = True
        prefs.save()

        ConnectedDevice.objects.create(
            user=active_patient,
            device_type=ConnectedDevice.DeviceType.APPLE_WATCH,
            device_name="Apple Watch",
            is_connected=True,
            last_synced_at=timezone.now() - timedelta(hours=25),  # stale
        )

        count = check_stale_wearable_syncs()
        assert count >= 1
        assert Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.WEARABLE_SYNC,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_skips_recently_synced(self, mock_push, active_patient, prefs):
        from datetime import timedelta
        prefs.wearable_sync_reminders = True
        prefs.save()

        ConnectedDevice.objects.create(
            user=active_patient,
            device_type=ConnectedDevice.DeviceType.FITBIT,
            device_name="Fitbit",
            is_connected=True,
            last_synced_at=timezone.now() - timedelta(hours=2),  # recent — not stale
        )

        check_stale_wearable_syncs()
        assert not Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.WEARABLE_SYNC,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_only_one_notification_per_user_per_run(self, mock_push, active_patient, prefs):
        """Even with 3 stale devices, user only gets 1 notification per run."""
        from datetime import timedelta
        prefs.wearable_sync_reminders = True
        prefs.save()

        stale_time = timezone.now() - timedelta(hours=30)
        for device_type in [
            ConnectedDevice.DeviceType.APPLE_WATCH,
            ConnectedDevice.DeviceType.FITBIT,
            ConnectedDevice.DeviceType.GARMIN,
        ]:
            ConnectedDevice.objects.create(
                user=active_patient,
                device_type=device_type,
                device_name=device_type,
                is_connected=True,
                last_synced_at=stale_time,
            )

        check_stale_wearable_syncs()
        notif_count = Notification.objects.filter(
            recipient=active_patient,
            notification_type=Notification.NotificationType.WEARABLE_SYNC,
        ).count()
        assert notif_count == 1  # only one, not three
