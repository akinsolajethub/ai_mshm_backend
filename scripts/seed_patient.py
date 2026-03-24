"""Seed script for the named patient and symptom data."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

import django  # noqa: E402
from django.utils import timezone  # noqa: E402

django.setup()

from apps.accounts.models import User  # noqa: E402
from apps.health_checkin.models import (  # noqa: E402
    CheckinSession,
    EveningCheckin,
    HirsutismMFGCheckin,
    MorningCheckin,
    SessionPeriod,
    SessionStatus,
)

EMAIL = "owoadeshefiq12@gmail.com"
PASSWORD = "shefiq1234"


def run():
    user, created = User.objects.get_or_create(
        email=EMAIL,
        defaults={"full_name": "Owodase Fiq", "role": User.Role.PATIENT},
    )
    user.set_password(PASSWORD)
    user.is_active = True
    user.is_email_verified = True
    user.onboarding_completed = True
    user.onboarding_step = 5
    user.save()
    print("user", user.pk, "created", created)

    checkin_date = timezone.datetime(2026, 3, 10).date()
    morning_session, _ = CheckinSession.objects.update_or_create(
        user=user,
        period=SessionPeriod.MORNING,
        checkin_date=checkin_date,
        defaults={
            "status": SessionStatus.COMPLETE,
            "cycle_phase": "Luteal",
            "cycle_day": 14,
            "missed_reminder_sent": False,
            "started_at": timezone.datetime(2026, 3, 10, 6, 0),
            "submitted_at": timezone.datetime(2026, 3, 10, 6, 12),
            "last_saved_at": timezone.datetime(2026, 3, 10, 6, 12),
        },
    )
    evening_session, _ = CheckinSession.objects.update_or_create(
        user=user,
        period=SessionPeriod.EVENING,
        checkin_date=checkin_date,
        defaults={
            "status": SessionStatus.COMPLETE,
            "cycle_phase": "Luteal",
            "cycle_day": 14,
            "missed_reminder_sent": False,
            "started_at": timezone.datetime(2026, 3, 10, 18, 45),
            "submitted_at": timezone.datetime(2026, 3, 10, 19, 0),
            "last_saved_at": timezone.datetime(2026, 3, 10, 19, 0),
        },
    )

    MorningCheckin.objects.update_or_create(
        session=morning_session,
        defaults={
            "fatigue_vas": 6.5,
            "pelvic_pressure_vas": 4.1,
            "psq_skin_sensitivity": 5.0,
            "psq_muscle_pressure_pain": 6.0,
            "psq_body_tenderness": 4.5,
            "hyperalgesia_index": 5.167,
            "hyperalgesia_severity": "Moderate",
        },
    )

    EveningCheckin.objects.update_or_create(
        session=evening_session,
        defaults={
            "breast_left_vas": 5.0,
            "breast_right_vas": 6.0,
            "mastalgia_side": "Bilateral",
            "mastalgia_quality": "Pressure",
            "breast_pain_avg": 5.5,
            "cyclic_mastalgia_score": 5.5,
            "breast_soreness_vas": 2.75,
            "mastalgia_severity": "Moderate",
            "acne_forehead": 2,
            "acne_right_cheek": 2,
            "acne_left_cheek": 1,
            "acne_nose": 1,
            "acne_chin": 0,
            "acne_chest_back": 1,
            "gags_score": 14,
            "acne_severity_likert": 0.9545,
            "acne_severity_label": "Mild",
            "bloating_delta_cm": 2.4,
            "unusual_bleeding": False,
        },
    )

    HirsutismMFGCheckin.objects.update_or_create(
        user=user,
        assessed_date=timezone.datetime(2026, 3, 7).date(),
        defaults={
            "mfg_upper_lip": 2,
            "mfg_chin": 1,
            "mfg_chest": 1,
            "mfg_upper_back": 1,
            "mfg_lower_back": 0,
            "mfg_upper_abdomen": 1,
            "mfg_lower_abdomen": 0,
            "mfg_upper_arm": 2,
            "mfg_thigh": 1,
            "mfg_total_score": 9,
            "mfg_severity": "Mild",
        },
    )

    print("sessions", CheckinSession.objects.filter(user=user).count())
    print("morning", MorningCheckin.objects.filter(session__user=user).count())
    print("evening", EveningCheckin.objects.filter(session__user=user).count())
    print("hirsutism", HirsutismMFGCheckin.objects.filter(user=user).count())


if __name__ == "__main__":
    run()
