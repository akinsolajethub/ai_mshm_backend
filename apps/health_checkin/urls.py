"""
apps/health_checkin/urls.py
Base prefix: /api/v1/checkin/
"""
from django.urls import path
from .views import (
    TodayStatusView, SessionStartView, SessionAutosaveView, SessionSubmitView,
    MorningCheckinView, EveningCheckinView,
    HRVSubmitView, HirsutismMFGView,
    CheckinHistoryView, CheckinDaySummaryView,
)

app_name = "health_checkin"

urlpatterns = [
    # ── Dashboard ─────────────────────────────────────────────────────────────
    path("today/",                          TodayStatusView.as_view(),       name="today-status"),

    # ── Session lifecycle ──────────────────────────────────────────────────────
    path("session/start/",                  SessionStartView.as_view(),      name="session-start"),
    path("session/<uuid:session_id>/autosave/", SessionAutosaveView.as_view(), name="session-autosave"),
    path("session/<uuid:session_id>/submit/",   SessionSubmitView.as_view(),   name="session-submit"),

    # ── Session data by period ────────────────────────────────────────────────
    path("morning/<uuid:session_id>/",      MorningCheckinView.as_view(),    name="morning"),
    path("evening/<uuid:session_id>/",      EveningCheckinView.as_view(),    name="evening"),

    # ── HRV capture ───────────────────────────────────────────────────────────
    path("hrv/",                            HRVSubmitView.as_view(),         name="hrv-submit"),

    # ── Hirsutism (weekly) ────────────────────────────────────────────────────
    path("mfg/",                            HirsutismMFGView.as_view(),      name="mfg"),

    # ── History ───────────────────────────────────────────────────────────────
    path("history/",                        CheckinHistoryView.as_view(),    name="history"),
    path("summary/<str:summary_date>/",     CheckinDaySummaryView.as_view(), name="day-summary"),
]
