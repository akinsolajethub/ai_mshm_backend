"""
apps/accounts/signals.py
────────────────────────
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
    When a brand-new user is created:
    1. Auto-provision settings documents
    2. Generate unique_id based on role
    """
    if not created:
        return

    from apps.settings_app.models import NotificationPreferences, PrivacySettings
    from .id_generator import generate_id_for_user

    NotificationPreferences.objects.get_or_create(user=instance)
    PrivacySettings.objects.get_or_create(user=instance)

    if instance.role == "patient":
        from apps.onboarding.models import OnboardingProfile

        OnboardingProfile.objects.get_or_create(user=instance)

    generate_id_for_user(instance)

    logger.info(
        "Provisioned default settings for new user: %s (role=%s, unique_id=%s)",
        instance.email,
        instance.role,
        instance.unique_id,
    )
