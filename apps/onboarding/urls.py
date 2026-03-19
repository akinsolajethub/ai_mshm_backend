"""
apps/onboarding/urls.py
Base prefix: /api/v1/onboarding/

ENDPOINTS:
  GET   /api/v1/onboarding/profile/      — full onboarding profile (read-only)
  PATCH /api/v1/onboarding/step/1/       — personal info
  PATCH /api/v1/onboarding/step/2/       — physical measurements
  PATCH /api/v1/onboarding/step/3/       — skin changes
  PATCH /api/v1/onboarding/step/4/       — menstrual history
  PATCH /api/v1/onboarding/step/5/       — wearable setup
  POST  /api/v1/onboarding/step/6/rppg/  — rPPG baseline
  PATCH /api/v1/onboarding/step/7/       — PHC registration (optional, also used from P9 settings)
  POST  /api/v1/onboarding/complete/     — mark onboarding complete
"""
from django.urls import path
from .views import (
    OnboardingStep1View,
    OnboardingStep2View,
    OnboardingStep3View,
    OnboardingStep4View,
    OnboardingStep5View,
    OnboardingRppgView,
    OnboardingStep7View,
    OnboardingCompleteView,
    OnboardingProfileView,
)

app_name = "onboarding"

urlpatterns = [
    path("profile/",     OnboardingProfileView.as_view(),  name="profile"),
    path("step/1/",      OnboardingStep1View.as_view(),    name="step-1"),
    path("step/2/",      OnboardingStep2View.as_view(),    name="step-2"),
    path("step/3/",      OnboardingStep3View.as_view(),    name="step-3"),
    path("step/4/",      OnboardingStep4View.as_view(),    name="step-4"),
    path("step/5/",      OnboardingStep5View.as_view(),    name="step-5"),
    path("step/6/rppg/", OnboardingRppgView.as_view(),     name="step-6-rppg"),
    path("step/7/",      OnboardingStep7View.as_view(),    name="step-7"),
    path("complete/",    OnboardingCompleteView.as_view(), name="complete"),
]