"""
apps/accounts/tests/test_signals.py
─────────────────────────────────────
Tests for Django signals across all apps.
"""
import pytest
from django.contrib.auth import get_user_model
from unittest.mock import patch

User = get_user_model()


@pytest.mark.django_db
class TestUserCreationSignals:
    """
    When a user is created, accounts.signals.create_user_defaults
    should auto-provision all related settings documents.
    """

    def test_notification_preferences_created_on_user_save(self, db):
        from apps.settings_app.models import NotificationPreferences
        user = User.objects.create_user(
            email="signal_test@test.com",
            full_name="Signal Test",
            password="TestPass1234!",
        )
        assert NotificationPreferences.objects.filter(user=user).exists()

    def test_privacy_settings_created_on_user_save(self, db):
        from apps.settings_app.models import PrivacySettings
        user = User.objects.create_user(
            email="privacy_signal@test.com",
            full_name="Privacy Signal",
            password="TestPass1234!",
        )
        assert PrivacySettings.objects.filter(user=user).exists()

    def test_onboarding_profile_created_on_user_save(self, db):
        from apps.onboarding.models import OnboardingProfile
        user = User.objects.create_user(
            email="onboard_signal@test.com",
            full_name="Onboard Signal",
            password="TestPass1234!",
        )
        assert OnboardingProfile.objects.filter(user=user).exists()

    def test_all_three_provisioned_atomically(self, db):
        from apps.settings_app.models import NotificationPreferences, PrivacySettings
        from apps.onboarding.models import OnboardingProfile
        user = User.objects.create_user(
            email="all_three@test.com",
            full_name="All Three",
            password="TestPass1234!",
        )
        assert NotificationPreferences.objects.filter(user=user).exists()
        assert PrivacySettings.objects.filter(user=user).exists()
        assert OnboardingProfile.objects.filter(user=user).exists()

    def test_signal_idempotent_on_update(self, db):
        """Saving an existing user again should not duplicate settings records."""
        from apps.settings_app.models import NotificationPreferences
        user = User.objects.create_user(
            email="idempotent@test.com",
            full_name="Idempotent",
            password="TestPass1234!",
        )
        # Save again (triggers post_save with created=False)
        user.full_name = "Updated Name"
        user.save(update_fields=["full_name"])
        # Should still have exactly one NotificationPreferences
        count = NotificationPreferences.objects.filter(user=user).count()
        assert count == 1


@pytest.mark.django_db
class TestEmailVerifiedSignal:
    """
    When is_email_verified flips to True, a welcome notification should fire.
    """

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_welcome_notification_sent_on_verify(self, mock_push, db):
        from apps.notifications.models import Notification
        user = User.objects.create_user(
            email="welcome_signal@test.com",
            full_name="Welcome Signal",
            password="TestPass1234!",
            is_email_verified=False,
        )
        # Simulate email verification
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])

        assert Notification.objects.filter(
            recipient=user,
            title="Welcome to AI-MSHM 🎉",
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_welcome_notification_not_duplicated(self, mock_push, db):
        """Saving user twice with is_email_verified=True should not double-send."""
        from apps.notifications.models import Notification
        user = User.objects.create_user(
            email="noduplicate@test.com",
            full_name="No Duplicate",
            password="TestPass1234!",
            is_email_verified=False,
        )
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])

        # Save again — already verified
        user.save(update_fields=["is_email_verified"])

        count = Notification.objects.filter(
            recipient=user,
            title="Welcome to AI-MSHM 🎉",
        ).count()
        assert count == 1


@pytest.mark.django_db
class TestOnboardingCompleteSignal:
    """
    When onboarding_completed flips to True, a congratulations notification fires.
    """

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_completion_notification_sent(self, mock_push, db):
        from apps.notifications.models import Notification
        user = User.objects.create_user(
            email="complete_signal@test.com",
            full_name="Complete Signal",
            password="TestPass1234!",
            is_email_verified=True,
            onboarding_completed=False,
        )
        user.onboarding_completed = True
        user.save(update_fields=["onboarding_completed"])

        assert Notification.objects.filter(
            recipient=user,
            title="You're all set!",
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_completion_notification_not_duplicated(self, mock_push, db):
        from apps.notifications.models import Notification
        user = User.objects.create_user(
            email="nodup_complete@test.com",
            full_name="No Dup Complete",
            password="TestPass1234!",
            is_email_verified=True,
            onboarding_completed=False,
        )
        user.onboarding_completed = True
        user.save(update_fields=["onboarding_completed"])
        user.save(update_fields=["onboarding_completed"])

        count = Notification.objects.filter(
            recipient=user,
            title="You're all set!",
        ).count()
        assert count == 1
