"""
apps/onboarding/services.py
────────────────────────────
Business logic helpers for the onboarding flow.
Views call these helpers to keep view code thin.

TOTAL STEPS: 7
  1 — Personal Info
  2 — Physical Measurements
  3 — Skin Changes
  4 — Menstrual History
  5 — Wearable Setup
  6 — rPPG Baseline (optional but recommended)
  7 — PHC Registration (optional, can be done later from P9)

completion_percentage counts steps 1–5 as required (each worth 17%),
step 6 and 7 as optional bonuses (each worth 7.5%) giving 115% max.
We cap at 100%.
"""
import logging
from django.contrib.auth import get_user_model
from .models import OnboardingProfile

logger = logging.getLogger(__name__)
User = get_user_model()

REQUIRED_STEPS   = 5   # Steps 1–5 are required
TOTAL_STEPS      = 7   # Steps 6–7 are optional


class OnboardingService:

    @staticmethod
    def get_or_create_profile(user) -> OnboardingProfile:
        profile, created = OnboardingProfile.objects.get_or_create(user=user)
        if created:
            logger.debug("Created onboarding profile for %s", user.email)
        return profile

    @staticmethod
    def advance_step(user, completed_step: int) -> None:
        """
        Advance user.onboarding_step if completed_step is further than current.
        Never goes backwards — re-submitting step 2 after step 4 does not regress.
        """
        if completed_step > user.onboarding_step:
            user.onboarding_step = completed_step
            user.save(update_fields=["onboarding_step"])

    @staticmethod
    def completion_percentage(user) -> int:
        """
        Returns 0–100 based on onboarding progress.

        Steps 1–5 are required — each contributes 20% (5 × 20 = 100%).
        Steps 6–7 are optional — they don't affect the percentage.
        This means 100% can be reached at step 5, encouraging completion
        of the required steps without penalising skipping optional ones.
        """
        step = min(user.onboarding_step, REQUIRED_STEPS)
        return round((step / REQUIRED_STEPS) * 100)

    @staticmethod
    def is_minimum_complete(user) -> bool:
        """
        Returns True if the user has completed at least the 5 required steps.
        Used to gate dashboard and health check-in access.
        """
        return user.onboarding_step >= REQUIRED_STEPS