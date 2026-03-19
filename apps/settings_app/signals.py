"""
apps/settings_app/signals.py
─────────────────────────────
Signals for the settings_app.
Currently: fires a notification when the user completes onboarding.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def onboarding_complete_notification(sender, instance: User, created: bool, update_fields, **kwargs):
    """
    When onboarding_completed flips to True, send a congratulations notification
    and schedule the first morning check-in reminder.
    """
    if created:
        return

    if update_fields and "onboarding_completed" not in update_fields:
        return

    if not instance.onboarding_completed:
        return

    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService

    already_sent = Notification.objects.filter(
        recipient=instance,
        notification_type=Notification.NotificationType.SYSTEM,
        title="You're all set!",
    ).exists()

    if already_sent:
        return

    NotificationService.send(
        recipient=instance,
        notification_type=Notification.NotificationType.SYSTEM,
        title="You're all set!",
        body=(
            "Your baseline has been saved. Your first morning check-in "
            "will be available tomorrow at 8 AM."
        ),
        priority=Notification.Priority.HIGH,
        data={"action": "go_to_dashboard"},
    )
    logger.info("Onboarding complete notification sent to %s", instance.email)
