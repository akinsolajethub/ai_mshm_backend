from django.contrib import admin
from .models import (
    CheckinSession, MorningCheckin,
    EveningCheckin, HirsutismMFGCheckin, DailyCheckinSummary, CheckinStreak,
)


@admin.register(CheckinSession)
class CheckinSessionAdmin(admin.ModelAdmin):
    list_display  = ("user", "period", "status", "checkin_date", "hrv_skipped", "last_saved_at")
    list_filter   = ("period", "status", "cycle_phase")
    search_fields = ("user__email",)
    date_hierarchy = "checkin_date"
    readonly_fields = ("id", "started_at", "submitted_at")


@admin.register(MorningCheckin)
class MorningCheckinAdmin(admin.ModelAdmin):
    list_display  = ("session", "fatigue_vas", "pelvic_pressure_vas", "hyperalgesia_index", "hyperalgesia_severity")
    readonly_fields = ("id", "hyperalgesia_index", "hyperalgesia_severity")


@admin.register(EveningCheckin)
class EveningCheckinAdmin(admin.ModelAdmin):
    list_display  = (
        "session", "gags_score", "acne_severity_label",
        "breast_soreness_vas", "mastalgia_severity",
        "bloating_delta_cm", "unusual_bleeding",
    )
    readonly_fields = (
        "id", "breast_pain_avg", "cyclic_mastalgia_score",
        "breast_soreness_vas", "mastalgia_severity",
        "gags_score", "acne_severity_likert", "acne_severity_label",
    )


@admin.register(HirsutismMFGCheckin)
class HirsutismMFGAdmin(admin.ModelAdmin):
    list_display  = ("user", "assessed_date", "mfg_total_score", "mfg_severity")
    list_filter   = ("mfg_severity",)
    search_fields = ("user__email",)
    readonly_fields = ("id", "mfg_total_score", "mfg_severity")


@admin.register(DailyCheckinSummary)
class DailyCheckinSummaryAdmin(admin.ModelAdmin):
    list_display  = (
        "user", "summary_date",
        "morning_complete", "evening_complete",
        "prediction_run",
    )
    list_filter   = ("morning_complete", "evening_complete", "prediction_run")
    search_fields = ("user__email",)
    readonly_fields = (
        "id", "created_at", "updated_at",
        "prediction_run_at",
    )
    date_hierarchy = "summary_date"


@admin.register(CheckinStreak)
class CheckinStreakAdmin(admin.ModelAdmin):
    list_display = ("user", "current_streak", "longest_streak", "total_days_logged", "last_complete_date")
    search_fields = ("user__email",)
