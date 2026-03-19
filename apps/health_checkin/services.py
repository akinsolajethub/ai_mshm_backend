"""
apps/health_checkin/services.py
═════════════════════════════════
All business logic for check-in session management.
Views call these services — nothing else.

Key responsibilities:
  1. get_or_create_session()    — idempotent session bootstrap
  2. save_partial()             — auto-save without completing
  3. complete_session()         — mark done + assemble daily summary
  4. assemble_daily_summary()   — merge morning evening into one ML row
  5. check_missed_sessions()    — called by Celery beat to flag + notify misses
  6. get_today_status()         — dashboard status snapshot
"""
import logging
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction

from .models import (
    CheckinSession, SessionPeriod, SessionStatus,
    MorningCheckin, EveningCheckin, HirsutismMFGCheckin, 
    DailyCheckinSummary, CheckinStreak,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# Session management
# ─────────────────────────────────────────────────────────────────────────────

class CheckinSessionService:

    @staticmethod
    def get_or_create_session(user: User, period: str, checkin_date: date = None) -> CheckinSession:
        """
        Idempotent — safe to call on every screen open.
        Returns existing session or creates a new PENDING one.
        Mobile calls this on screen entry so the session_id is known
        before any slider is touched.
        """
        today = checkin_date or timezone.localdate()
        session, created = CheckinSession.objects.get_or_create(
            user=user,
            period=period,
            checkin_date=today,
            defaults={"status": SessionStatus.PENDING},
        )
        if created:
            logger.info("Created %s session for %s on %s", period, user.email, today)
        return session

    @staticmethod
    def save_partial(session: CheckinSession):
        """
        Mark session as PARTIAL (auto-save mid-session).
        Called automatically by the autosave endpoint.
        """
        if session.status == SessionStatus.PENDING:
            session.status = SessionStatus.PARTIAL
            session.save(update_fields=["status", "last_saved_at"])

    @staticmethod
    @transaction.atomic
    def complete_session(session: CheckinSession) -> DailyCheckinSummary:
        """
        Mark session as COMPLETE then assemble / update the daily summary.
        Returns the DailyCheckinSummary for this date.
        Triggers prediction if both morning + evening are now complete.
        """
        session.mark_complete()
        logger.info("Completed %s session for %s on %s", session.period, session.user.email, session.checkin_date)

        summary = DailySummaryService.assemble_or_update(session.user, session.checkin_date)

        # Update streak
        StreakService.update(session.user, session.checkin_date)

        # Notify user check-in is complete
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService
    
        period_label = "Morning" if session.period == SessionPeriod.MORNING else "Evening"
        NotificationService.send(
            recipient=session.user,
            notification_type=Notification.NotificationType.MORNING_CHECKIN
            if session.period == SessionPeriod.MORNING
            else Notification.NotificationType.EVENING_CHECKIN,
            title=f"{period_label} check-in complete ✅",
            body=(
                f"Your {period_label.lower()} check-in for today has been recorded. "
                f"{'Complete your evening check-in later to unlock your prediction.' if session.period == SessionPeriod.MORNING else 'Great job staying consistent!'}"
            ),
            priority=Notification.Priority.LOW,
            data={
                "session_id": str(session.id),
                "period": session.period,
                "date": str(session.checkin_date),
                "action": "open_dashboard",
            },
        )

        # Queue prediction if ready
        if summary.is_ready_for_prediction and not summary.prediction_run:
            from core.utils.celery_helpers import run_task
            from apps.predictions.tasks import run_prediction_task
            run_task(run_prediction_task, str(summary.id))

        return summary

    @staticmethod
    def submit_hrv(session_id: str, hrv_sdnn_ms: float = None, hrv_rmssd_ms: float = None, skipped: bool = False):
        """
        Update HRV readings on a session after rPPG capture.
        """
        try:
            session = CheckinSession.objects.get(pk=session_id)
        except CheckinSession.DoesNotExist:
            raise ValueError(f"Session {session_id} not found.")

        session.hrv_sdnn_ms    = hrv_sdnn_ms
        session.hrv_rmssd_ms   = hrv_rmssd_ms
        session.hrv_captured_at = timezone.now() if not skipped else None
        session.hrv_skipped    = skipped
        session.save(update_fields=["hrv_sdnn_ms", "hrv_rmssd_ms", "hrv_captured_at", "hrv_skipped"])

        # Update summary HRV fields too
        try:
            summary = DailyCheckinSummary.objects.get(user=session.user, summary_date=session.checkin_date)
            if not skipped:
                summary.hrv_sdnn_ms  = hrv_sdnn_ms
                summary.hrv_rmssd_ms = hrv_rmssd_ms
                summary.save(update_fields=["hrv_sdnn_ms", "hrv_rmssd_ms", "updated_at"])
        except DailyCheckinSummary.DoesNotExist:
            pass

    @staticmethod
    def get_today_status(user: User) -> dict:
        """Dashboard snapshot of today's session states."""
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        def session_info(period, day=today):
            try:
                s = CheckinSession.objects.get(user=user, period=period, checkin_date=day)
                return s.status, str(s.id)
            except CheckinSession.DoesNotExist:
                return SessionStatus.PENDING, None

        morning_status,   morning_id   = session_info(SessionPeriod.MORNING)
        evening_status,   evening_id   = session_info(SessionPeriod.EVENING)

        # Missed yesterday check
        ym_status, _ = session_info(SessionPeriod.MORNING,   yesterday)
        ye_status, _ = session_info(SessionPeriod.EVENING,   yesterday)

        streak = CheckinStreak.objects.filter(user=user).first()
        streak_days = streak.current_streak if streak else 0

        done = sum([
            morning_status   == SessionStatus.COMPLETE,
            evening_status   == SessionStatus.COMPLETE,
        ])

        return {
            "date":              today,
            "morning_status":    morning_status,
            "evening_status":    evening_status,
            "morning_session_id":    morning_id,
            "evening_session_id":    evening_id,
            "completeness_pct":  round(done / 2 * 100),
            "streak_days":       streak_days,
            "missed_yesterday_morning": ym_status == SessionStatus.MISSED,
            "missed_yesterday_evening": ye_status == SessionStatus.MISSED,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Daily Summary assembly
# ─────────────────────────────────────────────────────────────────────────────

class DailySummaryService:

    @staticmethod
    @transaction.atomic
    def assemble_or_update(user: User, summary_date: date) -> DailyCheckinSummary:
        """
        Merge all available sessions for the day into a DailyCheckinSummary.
        Called every time a session is completed.
        Idempotent — safe to call multiple times.
        """
        summary, _ = DailyCheckinSummary.objects.get_or_create(
            user=user, summary_date=summary_date,
        )

        # Fetch completed sessions
        sessions = CheckinSession.objects.filter(
            user=user, checkin_date=summary_date, status=SessionStatus.COMPLETE,
        ).select_related("morning_data", "evening_data")

        session_map = {s.period: s for s in sessions}

        morning_s   = session_map.get(SessionPeriod.MORNING)
        evening_s   = session_map.get(SessionPeriod.EVENING)

        # ── Fatigue VAS: of morning ──────
        fatigue_values = []
        pelvic_values  = []
        if morning_s and hasattr(morning_s, "morning_data"):
            md = morning_s.morning_data
            if md.fatigue_vas is not None:
                fatigue_values.append(md.fatigue_vas)
            if md.pelvic_pressure_vas is not None:
                pelvic_values.append(md.pelvic_pressure_vas)
            summary.painful_touch_vas  = md.hyperalgesia_index
            summary.morning_session    = morning_s
            summary.morning_complete   = True
            summary.cycle_phase        = morning_s.cycle_phase
            summary.cycle_day          = morning_s.cycle_day
            summary.hrv_sdnn_ms        = morning_s.hrv_sdnn_ms
            summary.hrv_rmssd_ms       = morning_s.hrv_rmssd_ms

        if fatigue_values:
            summary.fatigue_mfi5_vas = round(sum(fatigue_values) / len(fatigue_values), 4)
        if pelvic_values:
            summary.pelvic_pressure_vas = round(sum(pelvic_values) / len(pelvic_values), 4)

        if evening_s and hasattr(evening_s, "evening_data"):
            evd = evening_s.evening_data
            summary.breast_soreness_vas  = evd.breast_soreness_vas
            summary.acne_severity_likert = evd.acne_severity_likert
            summary.bloating_delta_cm    = evd.bloating_delta_cm
            summary.unusual_bleeding     = evd.unusual_bleeding
            summary.evening_session      = evening_s
            summary.evening_complete     = True
            # Use evening HRV if morning had none
            if not summary.hrv_sdnn_ms and evening_s.hrv_sdnn_ms:
                summary.hrv_sdnn_ms  = evening_s.hrv_sdnn_ms
                summary.hrv_rmssd_ms = evening_s.hrv_rmssd_ms

        # Most recent mFG score (within last 7 days)
        recent_mfg = HirsutismMFGCheckin.objects.filter(
            user=user,
            assessed_date__gte=summary_date - timedelta(days=7),
        ).order_by("-assessed_date").first()
        if recent_mfg:
            summary.hirsutism_mfg_score = float(recent_mfg.mfg_total_score or 0)

        summary.save()
        logger.info(
            "Daily summary assembled for %s on %s — morning=%s evening=%s",
            user.email, summary_date,
            summary.morning_complete, summary.evening_complete,
        )
        return summary

    @staticmethod
    def get_28_day_data(user: User, reference_date: date = None) -> list[dict]:
        """
        Returns list of DailyCheckinSummary dicts for the last 28 days.
        Used by the prediction service to build the aggregated feature vector.
        """
        end   = reference_date or timezone.localdate()
        start = end - timedelta(days=27)
        rows  = DailyCheckinSummary.objects.filter(
            user=user,
            summary_date__gte=start,
            summary_date__lte=end,
        ).order_by("summary_date")

        return [
            {
                "summary_date":        r.summary_date.isoformat(),
                "Pelvic_Pressure_VAS": r.pelvic_pressure_vas,
                "Fatigue_MFI5_VAS":    r.fatigue_mfi5_vas,
                "Painful_Touch_VAS":   r.painful_touch_vas,
                "Breast_Soreness_VAS": r.breast_soreness_vas,
                "Acne_Severity_Likert": r.acne_severity_likert,
                "Hirsutism_mFG_Score": r.hirsutism_mfg_score,
                "Bloating_Delta_cm":   r.bloating_delta_cm,
                "Cycle_Phase":         r.cycle_phase,
                "hrv_sdnn_ms":         r.hrv_sdnn_ms,
            }
            for r in rows
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Missed Session Check (called by Celery beat)
# ─────────────────────────────────────────────────────────────────────────────

class MissedSessionService:

    MORNING_CUTOFF_HOUR   = 12   # sessions not completed by 12:00 are missed
    EVENING_CUTOFF_HOUR   = 23

    CUTOFFS = {
        SessionPeriod.MORNING:   MORNING_CUTOFF_HOUR,
        SessionPeriod.EVENING:   EVENING_CUTOFF_HOUR,
    }

    @staticmethod
    def run_missed_check(check_date: date = None):
        """
        Mark PENDING/PARTIAL sessions as MISSED if past cutoff.
        Notify the user if missed.
        Called by: Celery beat every hour.
        """
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService

        now  = timezone.localtime()
        today = check_date or now.date()

        period_to_cutoff = MissedSessionService.CUTOFFS

        for period, cutoff_hour in period_to_cutoff.items():
            if now.hour < cutoff_hour:
                continue  # Not past cutoff yet for this period today

            stale_sessions = CheckinSession.objects.filter(
                checkin_date=today,
                period=period,
                status__in=[SessionStatus.PENDING, SessionStatus.PARTIAL],
                missed_reminder_sent=False,
            )

            for session in stale_sessions:
                session.mark_missed()
                session.missed_reminder_sent = True
                session.save(update_fields=["missed_reminder_sent"])

                period_label = session.get_period_display()
                NotificationService.send(
                    recipient=session.user,
                    notification_type=Notification.NotificationType.MORNING_CHECKIN
                    if period == SessionPeriod.MORNING
                    else Notification.NotificationType.EVENING_CHECKIN,
                    title=f"You missed your {period_label} check-in",
                    body=(
                        f"Your {period_label.lower()} check-in for today was not completed. "
                        "Regular check-ins give the model more accurate results. "
                        "Don't worry — you can still complete your evening check-in."
                    ),
                    priority=Notification.Priority.MEDIUM,
                    data={
                        "session_id": str(session.id),
                        "period":     period,
                        "date":       str(today),
                        "action":     "open_checkin",
                    },
                )
                logger.info("Missed %s session for %s on %s", period, session.user.email, today)

    @staticmethod
    def notify_yesterday_misses(user: User):
        """
        Called on morning app open — check if yesterday had misses
        and return them so the UI can show the banner.
        """
        yesterday = timezone.localdate() - timedelta(days=1)
        missed = CheckinSession.objects.filter(
            user=user,
            checkin_date=yesterday,
            status=SessionStatus.MISSED,
        ).values("period")
        return [m["period"] for m in missed]


# ─────────────────────────────────────────────────────────────────────────────
# Streak tracking
# ─────────────────────────────────────────────────────────────────────────────

class StreakService:

    @staticmethod
    def update(user: User, completed_date: date):
        """
        Update streak after a day has both morning + evening complete.
        """
        morning_done = CheckinSession.objects.filter(
            user=user, checkin_date=completed_date,
            period=SessionPeriod.MORNING, status=SessionStatus.COMPLETE,
        ).exists()
        evening_done = CheckinSession.objects.filter(
            user=user, checkin_date=completed_date,
            period=SessionPeriod.EVENING, status=SessionStatus.COMPLETE,
        ).exists()

        if not (morning_done and evening_done):
            return  # Not a full day yet

        streak, _ = CheckinStreak.objects.get_or_create(user=user)
        yesterday = completed_date - timedelta(days=1)

        if streak.last_complete_date == yesterday:
            streak.current_streak += 1
        elif streak.last_complete_date != completed_date:
            streak.current_streak = 1

        streak.longest_streak    = max(streak.longest_streak, streak.current_streak)
        streak.last_complete_date = completed_date
        streak.total_days_logged += 1
        streak.save()

        logger.info(
            "Streak updated for %s: current=%d longest=%d",
            user.email, streak.current_streak, streak.longest_streak,
        )
