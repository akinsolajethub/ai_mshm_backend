"""
config/beat_schedule.py
────────────────────────
Celery Beat periodic task schedule.
Import this into base.py as:
    from config.beat_schedule import CELERY_BEAT_SCHEDULE
"""
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # ── Check-in reminders: run every minute, filter by user pref time ────────
    "morning-checkin-reminders": {
        "task": "notifications.send_morning_checkin_reminders",
        "schedule": crontab(minute="*"),          # every minute
        "options": {"queue": "notifications"},
    },
    "evening-checkin-reminders": {
        "task": "notifications.send_evening_checkin_reminders",
        "schedule": crontab(minute="*"),
        "options": {"queue": "notifications"},
    },

    # ── Weekly prompts: every Monday at 09:00 UTC ────────────────────────────
    "weekly-tool-prompts": {
        "task": "notifications.send_weekly_tool_prompts",
        "schedule": crontab(hour=9, minute=0, day_of_week="monday"),
        "options": {"queue": "notifications"},
    },

    # ── Stale wearable sync check: every 6 hours ─────────────────────────────
    "check-stale-wearable-syncs": {
        "task": "notifications.check_stale_wearable_syncs",
        "schedule": crontab(minute=0, hour="*/6"),
        "options": {"queue": "notifications"},
    },

    # ── Missed session checker: hourly ────────────────────────────────────
    "check-missed-sessions": {
        "task":    "health_checkin.check_missed_sessions",
        "schedule": crontab(minute=0),         # top of every hour
        "options": {"queue": "default"},
    },

    # ── Check-in reminder nudges ──────────────────────────────────────────
    "morning-checkin-nudge": {
        "task":    "health_checkin.send_checkin_reminders",
        "schedule": crontab(hour=8, minute=0),     # 8:00 AM
        "options": {"queue": "notifications"},
    },
    "morning-checkin-nudge-followup": {
        "task":    "health_checkin.send_checkin_reminders",
        "schedule": crontab(hour=9, minute=0),     # 9:00 AM follow-up
        "options": {"queue": "notifications"},
    },
    "evening-checkin-nudge": {
        "task":    "health_checkin.send_checkin_reminders",
        "schedule": crontab(hour=20, minute=0),    # 8:00 PM
        "options": {"queue": "notifications"},
    },
    "evening-checkin-nudge-followup": {
        "task":    "health_checkin.send_checkin_reminders",
        "schedule": crontab(hour=21, minute=0),    # 9:00 PM follow-up
        "options": {"queue": "notifications"},
    },
}
