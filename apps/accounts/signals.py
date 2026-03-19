"""
apps/accounts/signals.py
─────────────────────────
Django signals for the accounts app.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def create_user_defaults(sender, instance: User, created: bool, **kwargs):
    """
    When a brand-new user is created, auto-provision their settings documents
    so every GET on settings endpoints always finds an existing record.
    """
    if not created:
        return

    # Import here to avoid circular imports at module load time
    from apps.settings_app.models import NotificationPreferences, PrivacySettings

    # All roles get notification prefs and privacy settings
    NotificationPreferences.objects.get_or_create(user=instance)
    PrivacySettings.objects.get_or_create(user=instance)

    # Onboarding profile only for patients
    if instance.role == "patient":
        from apps.onboarding.models import OnboardingProfile
        OnboardingProfile.objects.get_or_create(user=instance)

    logger.info("Provisioned default settings for new user: %s (role=%s)", instance.email, instance.role)
