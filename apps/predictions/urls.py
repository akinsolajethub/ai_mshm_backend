"""
apps/predictions/urls.py
Base prefix: /api/v1/predictions/
"""

from django.urls import path
from .views import (
    LatestPredictionView,
    PredictionHistoryView,
    PredictionDetailView,
    PredictionFeaturesView,
    TriggerPredictionView,
    PCOSRiskScoreView,
    ComprehensivePredictionView,
    MoodEscalationView,
    MenstrualEscalationView,
    RPPGEscalationView,
    EnsembleWeightConfigListView,
    EnsembleWeightConfigDetailView,
    EnsembleWeightConfigResetView,
)

app_name = "predictions"

urlpatterns = [
    path("latest/", LatestPredictionView.as_view(), name="latest"),
    path("history/", PredictionHistoryView.as_view(), name="history"),
    path("trigger/", TriggerPredictionView.as_view(), name="trigger"),
    path("pcos/", PCOSRiskScoreView.as_view(), name="pcos"),
    # Comprehensive prediction endpoint
    path("comprehensive/", ComprehensivePredictionView.as_view(), name="comprehensive"),
    # Per-model escalation endpoints
    path("escalate/mood/", MoodEscalationView.as_view(), name="escalate-mood"),
    path("escalate/menstrual/", MenstrualEscalationView.as_view(), name="escalate-menstrual"),
    path("escalate/rppg/", RPPGEscalationView.as_view(), name="escalate-rppg"),
    # Ensemble weight configuration (admin only)
    path("ensemble-config/", EnsembleWeightConfigListView.as_view(), name="ensemble-config-list"),
    path(
        "ensemble-config/reset/",
        EnsembleWeightConfigResetView.as_view(),
        name="ensemble-config-reset",
    ),
    path(
        "ensemble-config/<str:disease_name>/",
        EnsembleWeightConfigDetailView.as_view(),
        name="ensemble-config-detail",
    ),
    path("<uuid:pk>/", PredictionDetailView.as_view(), name="detail"),
    path("<uuid:pk>/features/", PredictionFeaturesView.as_view(), name="features"),
]
