"""
apps/notifications/tasks.py
────────────────────────────
Celery tasks for scheduled and triggered notifications.

Periodic tasks are registered via Django Celery Beat.
Register them in config/beat_schedule.py or via Django Admin → Periodic Tasks.

TASK LIST:
  Scheduled (Celery Beat):
    send_morning_checkin_reminders       — every minute, matches user pref time
    send_evening_checkin_reminders       — every minute, matches user pref time
    send_weekly_tool_prompts             — every Monday 09:00 UTC
    check_stale_wearable_syncs           — every 6 hours
    remind_unassigned_cases              — every 6 hours (FMC cases open 24hr+ with no clinician)

  On-demand (called with .delay() or run_task()):
    notify_risk_score_change             — called by ML pipeline on score change
    remind_patient_to_set_phc_task       — called after onboarding complete if no PHC set
    notify_change_request_status_update  — called when admin updates a ChangeRequest status
"""
import logging
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()


# ── Scheduled: Morning Check-in Reminder ─────────────────────────────────────

@shared_task(name="notifications.send_morning_checkin_reminders")
def send_morning_checkin_reminders():
    """
    Run every minute (Celery Beat).
    Sends a morning check-in reminder to users whose preferred morning_time
    matches the current UTC minute and have the toggle enabled.
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService
    from apps.settings_app.models import NotificationPreferences

    current_time = timezone.now().strftime("%H:%M")
    prefs_qs = NotificationPreferences.objects.filter(
        morning_time=current_time,
        morning_checkin_enabled=True,
        do_not_disturb=False,
        user__is_active=True,
        user__is_email_verified=True,
        user__onboarding_completed=True,
    ).select_related("user")

    count = 0
    for pref in prefs_qs:
        NotificationService.send(
            recipient=pref.user,
            notification_type=Notification.NotificationType.MORNING_CHECKIN,
            title="Good morning! ☀️",
            body="Time for your morning check-in. It only takes 2 minutes.",
            priority=Notification.Priority.MEDIUM,
            data={"action": "open_morning_checkin"},
        )
        count += 1

    logger.info("Morning check-in reminders sent: %d", count)
    return count


# ── Scheduled: Evening Check-in Reminder ─────────────────────────────────────

@shared_task(name="notifications.send_evening_checkin_reminders")
def send_evening_checkin_reminders():
    """
    Run every minute (Celery Beat).
    Mirrors morning reminder for evening preferences.
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService
    from apps.settings_app.models import NotificationPreferences

    current_time = timezone.now().strftime("%H:%M")
    prefs_qs = NotificationPreferences.objects.filter(
        evening_time=current_time,
        evening_checkin_enabled=True,
        do_not_disturb=False,
        user__is_active=True,
        user__is_email_verified=True,
        user__onboarding_completed=True,
    ).select_related("user")

    count = 0
    for pref in prefs_qs:
        NotificationService.send(
            recipient=pref.user,
            notification_type=Notification.NotificationType.EVENING_CHECKIN,
            title="Evening check-in 🌙",
            body="How was your day? Complete your evening check-in.",
            priority=Notification.Priority.MEDIUM,
            data={"action": "open_evening_checkin"},
        )
        count += 1

    logger.info("Evening check-in reminders sent: %d", count)
    return count


# ── Scheduled: Weekly Tool Prompts ───────────────────────────────────────────

@shared_task(name="notifications.send_weekly_tool_prompts")
def send_weekly_tool_prompts():
    """
    Run every Monday morning (Celery Beat).
    Reminds patients to complete their weekly mFG score and PHQ-4.
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService
    from apps.settings_app.models import NotificationPreferences

    prefs_qs = NotificationPreferences.objects.filter(
        weekly_prompts_enabled=True,
        do_not_disturb=False,
        user__is_active=True,
        user__onboarding_completed=True,
    ).select_related("user")

    count = 0
    for pref in prefs_qs:
        NotificationService.send(
            recipient=pref.user,
            notification_type=Notification.NotificationType.WEEKLY_PROMPT,
            title="Weekly assessment due 📋",
            body=(
                "Your weekly mFG score and PHQ-4 mood assessment are ready. "
                "These help improve your risk predictions."
            ),
            priority=Notification.Priority.MEDIUM,
            data={"action": "open_weekly_tools"},
        )
        count += 1

    logger.info("Weekly tool prompts sent: %d", count)
    return count


# ── Scheduled: Stale Wearable Sync ───────────────────────────────────────────

@shared_task(name="notifications.check_stale_wearable_syncs")
def check_stale_wearable_syncs():
    """
    Run every 6 hours (Celery Beat).
    Notifies users whose wearable hasn't synced in more than 24 hours.
    Only one notification per user per run even if they have multiple devices.
    """
    from datetime import timedelta
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService
    from apps.settings_app.models import ConnectedDevice, NotificationPreferences

    stale_cutoff  = timezone.now() - timedelta(hours=24)
    stale_devices = ConnectedDevice.objects.filter(
        is_connected=True,
        last_synced_at__lt=stale_cutoff,
        user__is_active=True,
    ).select_related("user")

    notified_users = set()
    for device in stale_devices:
        user = device.user
        if user.pk in notified_users:
            continue

        try:
            prefs = NotificationPreferences.objects.get(user=user)
            if not prefs.wearable_sync_reminders:
                continue
        except NotificationPreferences.DoesNotExist:
            continue

        NotificationService.send(
            recipient=user,
            notification_type=Notification.NotificationType.WEARABLE_SYNC,
            title="Wearable sync needed 📡",
            body=(
                f"Your {device.get_device_type_display()} hasn't synced in over 24 hours. "
                "Open the app to sync your latest health data."
            ),
            priority=Notification.Priority.LOW,
            data={
                "device_type": device.device_type,
                "device_id": str(device.pk),
                "action": "open_devices",
            },
        )
        notified_users.add(user.pk)

    logger.info("Stale wearable sync notifications sent: %d", len(notified_users))
    return len(notified_users)


# ── Scheduled: Unassigned Case Reminder (FMC staff) ──────────────────────────

@shared_task(name="notifications.remind_unassigned_cases")
def remind_unassigned_cases():
    """
    Run every 6 hours (Celery Beat).

    Finds PatientCases that have been OPEN (unassigned) for more than 24 hours
    and sends a reminder notification to the FMC admin and all active FMC staff.

    This ensures critical cases don't fall through the gaps when FMC staff
    miss the initial escalation notification.
    """
    from datetime import timedelta
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService
    from apps.centers.models import PatientCase

    cutoff = timezone.now() - timedelta(hours=24)

    overdue_cases = PatientCase.objects.filter(
        status=PatientCase.CaseStatus.OPEN,
        opened_at__lt=cutoff,
        fhc__isnull=False,
    ).select_related("patient", "fhc", "fhc__admin_user")

    count = 0
    for case in overdue_cases:
        fhc = case.fhc
        patient = case.patient

        reminder_data = {
            "case_id":       str(case.id),
            "patient_name":  patient.full_name,
            "condition":     case.condition,
            "severity":      case.severity,
            "score":         case.opening_score,
            "hours_open":    int((timezone.now() - case.opened_at).total_seconds() / 3600),
            "action":        "open_fmc_queue",
        }

        # Notify FMC admin
        if fhc.admin_user:
            NotificationService.send(
                recipient=fhc.admin_user,
                notification_type=Notification.NotificationType.RISK_UPDATE,
                title=f"Unassigned case: {case.get_severity_display()} {case.get_condition_display()}",
                body=(
                    f"Patient {patient.full_name}'s case has been open for over 24 hours "
                    f"with no clinician assigned. Please review the queue."
                ),
                priority=Notification.Priority.HIGH,
                data=reminder_data,
            )

        # Notify all active FMC staff
        for staff_profile in fhc.get_active_staff():
            NotificationService.send(
                recipient=staff_profile.user,
                notification_type=Notification.NotificationType.RISK_UPDATE,
                title="Unassigned case reminder",
                body=(
                    f"A {case.get_severity_display()} {case.get_condition_display()} case "
                    f"for {patient.full_name} has been waiting over 24 hours. "
                    "Please assign a clinician."
                ),
                priority=Notification.Priority.HIGH,
                data=reminder_data,
            )

        count += 1
        logger.info(
            "Unassigned case reminder sent: case=%s patient=%s fhc=%s",
            case.id, patient.email, fhc.name,
        )

    logger.info("Unassigned case reminders sent for %d cases", count)
    return count


# ── On-demand: Risk Score Change Notification ─────────────────────────────────

@shared_task(name="notifications.notify_risk_score_change")
def notify_risk_score_change(user_id: str, new_score: int, previous_score: int, condition: str):
    """
    Called by the ML pipeline when a risk score changes significantly.

    Args:
        user_id        : Patient UUID string
        new_score      : New risk score (0–100)
        previous_score : Previous score (0–100)
        condition      : 'pcos' | 'maternal' | 'cardiovascular'
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService
    from apps.settings_app.models import NotificationPreferences

    try:
        user = User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        logger.warning("notify_risk_score_change: user %s not found", user_id)
        return

    try:
        prefs = NotificationPreferences.objects.get(user=user)
        if not prefs.risk_score_updates_enabled:
            return
    except NotificationPreferences.DoesNotExist:
        pass  # Send anyway if prefs not found

    delta           = new_score - previous_score
    direction       = "increased" if delta > 0 else "decreased"
    condition_label = {
        "pcos":           "PCOS",
        "maternal":       "Maternal Health",
        "cardiovascular": "Cardiovascular",
    }.get(condition, condition.title())

    NotificationService.send(
        recipient=user,
        notification_type=Notification.NotificationType.RISK_UPDATE,
        title=f"{condition_label} risk score updated",
        body=(
            f"Your {condition_label} risk score has {direction} "
            f"from {previous_score} to {new_score}. Tap to view details."
        ),
        priority=Notification.Priority.HIGH if abs(delta) >= 15 else Notification.Priority.MEDIUM,
        data={
            "condition":      condition,
            "new_score":      new_score,
            "previous_score": previous_score,
            "delta":          delta,
            "action":         "open_risk_details",
        },
    )
    logger.info(
        "Risk score notification sent: user=%s condition=%s %d→%d",
        user_id, condition, previous_score, new_score,
    )


# ── On-demand: PHC Registration Reminder (after onboarding) ──────────────────

@shared_task(name="notifications.remind_patient_to_set_phc_task")
def remind_patient_to_set_phc_task(user_id: str):
    """
    Called 24 hours after a patient completes onboarding if they have
    not set their home PHC (registered_hcc is still null).

    Dispatched from: apps/onboarding/views.py → OnboardingCompleteView
    using run_task() so it works on both free tier and with Celery workers.

    The task is delayed by 24 hours:
      Free tier  → task.run() is called inline (no delay — acceptable)
      Celery     → task.apply_async(args=[user_id], countdown=86400)
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService

    try:
        user = User.objects.get(pk=user_id, is_active=True, role="patient")
    except User.DoesNotExist:
        logger.warning("remind_patient_to_set_phc_task: user %s not found", user_id)
        return

    # Check if they've set their PHC since onboarding completed
    try:
        if user.onboarding_profile.registered_hcc is not None:
            logger.info(
                "remind_patient_to_set_phc_task: user %s already has a PHC set — skipping",
                user_id,
            )
            return
    except Exception:
        pass  # No profile yet — still send the reminder

    NotificationService.send(
        recipient=user,
        notification_type=Notification.NotificationType.SYSTEM,
        title="Complete your health profile",
        body=(
            "You haven't added your nearest health centre yet. "
            "Adding a Primary Health Centre (PHC) lets us connect you with "
            "local care if your health risk score needs attention. "
            "Tap here to add your PHC in your profile settings."
        ),
        priority=Notification.Priority.MEDIUM,
        data={"action": "set_phc_reminder"},
    )
    logger.info("PHC registration reminder sent to patient %s", user_id)


# ── On-demand: Change Request Status Update ───────────────────────────────────

@shared_task(name="notifications.notify_change_request_status_update")
def notify_change_request_status_update(request_id: str):
    """
    Called when Platform Admin or a facility admin updates a ChangeRequest status.
    Notifies the patient of the status change.

    Args:
        request_id : UUID string of the ChangeRequest
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService
    from apps.centers.models import ChangeRequest

    try:
        change_request = ChangeRequest.objects.select_related("patient").get(pk=request_id)
    except ChangeRequest.DoesNotExist:
        logger.warning("notify_change_request_status_update: request %s not found", request_id)
        return

    patient = change_request.patient

    status_messages = {
        ChangeRequest.RequestStatus.REVIEWED: (
            "Your request is being reviewed",
            "Your change request is now under review. We'll update you once a decision is made.",
        ),
        ChangeRequest.RequestStatus.RESOLVED: (
            "Your request has been resolved",
            "Good news — your change request has been resolved. Check your profile for updates.",
        ),
        ChangeRequest.RequestStatus.REJECTED: (
            "Your request could not be fulfilled",
            (
                "Unfortunately your change request could not be fulfilled at this time. "
                + (f"Reason: {change_request.admin_notes}" if change_request.admin_notes else "")
            ),
        ),
    }

    title, body = status_messages.get(
        change_request.status,
        ("Change request update", f"Your request status has been updated to: {change_request.get_status_display()}"),
    )

    NotificationService.send(
        recipient=patient,
        notification_type=Notification.NotificationType.SYSTEM,
        title=title,
        body=body,
        priority=Notification.Priority.MEDIUM,
        data={
            "request_id":   str(change_request.id),
            "request_type": change_request.request_type,
            "status":       change_request.status,
            "action":       "open_change_requests",
        },
    )
    logger.info(
        "Change request status notification sent: request=%s patient=%s status=%s",
        request_id, patient.email, change_request.status,
    )