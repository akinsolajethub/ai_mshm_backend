"""
apps/predictions/tasks.py
═══════════════════════════
Celery tasks for async prediction execution and missed session checks.
"""
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="predictions.run_prediction",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def run_prediction_task(self, summary_id: str):
    """
    Triggered by complete_session() once morning + evening are both done.
    Runs the full ML pipeline and persists the result.
    """
    from .services import PredictionService
    try:
        result = PredictionService.run_for_summary(summary_id)
        logger.info("Prediction task complete: summary=%s result=%s", summary_id, result.id)
        return {"status": "success", "result_id": str(result.id)}
    except Exception as exc:
        logger.error("Prediction task failed for summary %s: %s", summary_id, exc)
        raise self.retry(exc=exc)


@shared_task(name="health_checkin.check_missed_sessions")
def check_missed_sessions_task():
    """
    Run hourly via Celery Beat.
    Marks PENDING/PARTIAL sessions past their cutoff as MISSED and notifies users.
    """
    from apps.health_checkin.services import MissedSessionService
    MissedSessionService.run_missed_check()
    logger.info("Missed session check completed at %s", timezone.now())


@shared_task(name="health_checkin.send_checkin_reminders")
def send_checkin_reminders_task():
    """
    Runs every 30 minutes via Celery Beat.
    Sends nudge notifications to users who haven't started today's check-ins.
    """
    from django.contrib.auth import get_user_model
    from apps.health_checkin.models import CheckinSession, SessionPeriod, SessionStatus
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService
    from apps.settings_app.models import NotificationPreferences
    from django.utils import timezone as tz

    User = get_user_model()
    now   = tz.localtime()
    today = now.date()
    hour  = now.hour

    # Morning reminder: 8–9 AM if no morning session
    if 8 <= hour <= 9:
        period = SessionPeriod.MORNING
        title  = "Good morning! ☀️ Time for your check-in"
        body   = "Your morning check-in takes just 2 minutes. Track your fatigue and pain levels."
    # Evening reminder: 8–9 PM if no evening session
    elif 20 <= hour <= 21:
        period = SessionPeriod.EVENING
        title  = "Evening check-in time 🌙"
        body   = "Complete your evening check-in to log today's symptoms and keep your risk scores up to date."
    else:
        return  # Not a reminder window

    # Find users with notification pref on + no session yet today
    users_with_prefs = NotificationPreferences.objects.filter(
        **{f"{'morning' if period == SessionPeriod.MORNING else 'evening'}_checkin_enabled": True},
        do_not_disturb=False,
        user__is_active=True,
        user__is_email_verified=True,
        user__onboarding_completed=True,
        user__role="patient",
    ).values_list("user_id", flat=True)

    already_started = CheckinSession.objects.filter(
        checkin_date=today,
        period=period,
        status__in=[SessionStatus.PARTIAL, SessionStatus.COMPLETE],
    ).values_list("user_id", flat=True)

    users_to_remind = set(users_with_prefs) - set(already_started)

    notif_type = (
        Notification.NotificationType.MORNING_CHECKIN
        if period == SessionPeriod.MORNING
        else Notification.NotificationType.EVENING_CHECKIN
    )

    count = 0
    for user_id in users_to_remind:
        try:
            user = User.objects.get(pk=user_id)
            NotificationService.send(
                recipient=user,
                notification_type=notif_type,
                title=title,
                body=body,
                priority=Notification.Priority.MEDIUM,
                data={"period": period, "action": "open_checkin"},
            )
            count += 1
        except Exception as e:
            logger.warning("Failed to remind user %s: %s", user_id, e)

    logger.info("Sent %s check-in reminders for %s", count, period)
