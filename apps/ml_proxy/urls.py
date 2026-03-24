from django.urls import path
from .views import (
    MenstrualLogCycleView,
    MenstrualPredictView,
    MenstrualHistoryView,
    MenstrualPredictionHistoryView,
    MenstrualPredictFromLogsView,
    MenstrualFeaturesView,
    MenstrualModelInfoView,
    MoodLogPHQ4View,
    MoodLogAffectView,
    MoodLogFocusView,
    MoodLogSleepView,
    MoodLogCompleteView,
    MoodPredictView,
    MoodHistoryView,
    MoodPredictLatestView,
    MoodPredictMentalHealthView,
    MoodPredictMetabolicView,
    MoodPredictCardioNeuroView,
    MoodPredictReproductiveView,
    RppgSessionView,
    RppgPredictMetabolicCardioView,
    RppgPredictStressReproductiveView,
    RppgPredictAnomalyView,
    RppgSessionsView,
    RppgPredictionsView,
)

urlpatterns = [
    # Menstrual Cycle ML (proxied to Node.js)
    path("menstrual/log-cycle", MenstrualLogCycleView.as_view(), name="menstrual-log-cycle"),
    path("menstrual/predict", MenstrualPredictView.as_view(), name="menstrual-predict"),
    path("menstrual/predict/from-logs", MenstrualPredictFromLogsView.as_view(), name="menstrual-predict-from-logs"),
    path("menstrual/history", MenstrualHistoryView.as_view(), name="menstrual-history"),
    path(
        "menstrual/predictions",
        MenstrualPredictionHistoryView.as_view(),
        name="menstrual-prediction-history",
    ),
    path("menstrual/features", MenstrualFeaturesView.as_view(), name="menstrual-features"),
    path("menstrual/model-info", MenstrualModelInfoView.as_view(), name="menstrual-model-info"),
    # Mood & Cognitive ML (proxied to Node.js)
    path("mood/log/phq4", MoodLogPHQ4View.as_view(), name="mood-log-phq4"),
    path("mood/log/affect", MoodLogAffectView.as_view(), name="mood-log-affect"),
    path("mood/log/focus", MoodLogFocusView.as_view(), name="mood-log-focus"),
    path("mood/log/sleep", MoodLogSleepView.as_view(), name="mood-log-sleep"),
    path("mood/log/complete", MoodLogCompleteView.as_view(), name="mood-log-complete"),
    path("mood/predict", MoodPredictView.as_view(), name="mood-predict"),
    path("mood/history", MoodHistoryView.as_view(), name="mood-history"),
    path(
        "mood/predictions/latest", MoodPredictLatestView.as_view(), name="mood-predictions-latest"
    ),
    # Mood prediction sub-routes
    path(
        "mood/predict/mental-health",
        MoodPredictMentalHealthView.as_view(),
        name="mood-predict-mental-health",
    ),
    path(
        "mood/predict/metabolic", MoodPredictMetabolicView.as_view(), name="mood-predict-metabolic"
    ),
    path(
        "mood/predict/cardio-neuro",
        MoodPredictCardioNeuroView.as_view(),
        name="mood-predict-cardio-neuro",
    ),
    path(
        "mood/predict/reproductive",
        MoodPredictReproductiveView.as_view(),
        name="mood-predict-reproductive",
    ),
    # rPPG (HRV) ML (proxied to Node.js)
    path("rppg/session", RppgSessionView.as_view(), name="rppg-session"),
    path("rppg/predict/metabolic-cardio", RppgPredictMetabolicCardioView.as_view(), name="rppg-predict-metabolic-cardio"),
    path("rppg/predict/stress-reproductive", RppgPredictStressReproductiveView.as_view(), name="rppg-predict-stress-reproductive"),
    path("rppg/predict/anomaly", RppgPredictAnomalyView.as_view(), name="rppg-predict-anomaly"),
    path("rppg/sessions", RppgSessionsView.as_view(), name="rppg-sessions"),
    path("rppg/predictions", RppgPredictionsView.as_view(), name="rppg-predictions"),
]
