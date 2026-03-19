"""
apps/notifications/signals.py
───────────────────────────────
Fires a welcome in-app notification the first time a user's email
is verified (is_email_verified flips from False → True).
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def send_welcome_notification(sender, instance: User, created: bool, update_fields, **kwargs):
    """
    Send a one-time welcome notification when the user verifies their email.
    Guard: only fires when is_email_verified has just been set to True.
    """
    if created:
        return  # new user — email not yet verified

    # update_fields is a frozenset or None
    if update_fields and "is_email_verified" not in update_fields:
        return

    if not instance.is_email_verified:
        return

    # Check we haven't already sent the welcome (idempotency guard)
    from apps.notifications.models import Notification
    already_sent = Notification.objects.filter(
        recipient=instance,
        notification_type=Notification.NotificationType.SYSTEM,
        title="Welcome to AI-MSHM 🎉",
    ).exists()

    if already_sent:
        return

    from apps.notifications.services import NotificationService

    NotificationService.send(
        recipient=instance,
        notification_type=Notification.NotificationType.SYSTEM,
        title="Welcome to AI-MSHM 🎉",
        body=(
            f"Hi {instance.display_name}! Your email has been verified. "
            "Complete your onboarding to start your personalised health journey."
        ),
        priority=Notification.Priority.HIGH,
        data={"action": "start_onboarding"},
    )
    logger.info("Welcome notification sent to %s", instance.email)
