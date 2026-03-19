from django.urls import path
from .views import (
    MenstrualLogCycleView,
    MenstrualPredictView,
    MenstrualHistoryView,
    MenstrualPredictionHistoryView,
    MoodLogPHQ4View,
    MoodLogAffectView,
    MoodLogFocusView,
    MoodLogSleepView,
    MoodLogCompleteView,
    MoodPredictView,
)

urlpatterns = [
    # Menstrual Cycle ML (proxied to Node.js)
    path("menstrual/log-cycle", MenstrualLogCycleView.as_view(), name="menstrual-log-cycle"),
    path("menstrual/predict", MenstrualPredictView.as_view(), name="menstrual-predict"),
    path("menstrual/history", MenstrualHistoryView.as_view(), name="menstrual-history"),
    path(
        "menstrual/predictions",
        MenstrualPredictionHistoryView.as_view(),
        name="menstrual-prediction-history",
    ),
    # Mood & Cognitive ML (proxied to Node.js)
    path("mood/log/phq4", MoodLogPHQ4View.as_view(), name="mood-log-phq4"),
    path("mood/log/affect", MoodLogAffectView.as_view(), name="mood-log-affect"),
    path("mood/log/focus", MoodLogFocusView.as_view(), name="mood-log-focus"),
    path("mood/log/sleep", MoodLogSleepView.as_view(), name="mood-log-sleep"),
    path("mood/log/complete", MoodLogCompleteView.as_view(), name="mood-log-complete"),
    path("mood/predict", MoodPredictView.as_view(), name="mood-predict"),
]
