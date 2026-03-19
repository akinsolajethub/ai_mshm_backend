"""
apps/predictions/urls.py
Base prefix: /api/v1/predictions/
"""
from django.urls import path
from .views import (
    LatestPredictionView, PredictionHistoryView,
    PredictionDetailView, PredictionFeaturesView, TriggerPredictionView,
)

app_name = "predictions"

urlpatterns = [
    path("latest/",            LatestPredictionView.as_view(),   name="latest"),
    path("history/",           PredictionHistoryView.as_view(),  name="history"),
    path("trigger/",           TriggerPredictionView.as_view(),  name="trigger"),
    path("<uuid:pk>/",         PredictionDetailView.as_view(),   name="detail"),
    path("<uuid:pk>/features/", PredictionFeaturesView.as_view(), name="features"),
]
