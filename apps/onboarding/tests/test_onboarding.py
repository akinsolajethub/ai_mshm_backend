"""
apps/onboarding/tests/test_onboarding.py
──────────────────────────────────────────
Tests for all onboarding steps and profile retrieval.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.onboarding.models import OnboardingProfile

User = get_user_model()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="patient@test.com",
        full_name="Test Patient",
        password="TestPass1234!",
        role="patient",
        is_email_verified=True,
    )


@pytest.fixture
def auth_client(api_client, user):
    url = reverse("v1:accounts:login")
    resp = api_client.post(url, {
        "email": "patient@test.com",
        "password": "TestPass1234!",
    }, format="json")
    token = resp.data["data"]["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


# ── Profile GET ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOnboardingProfile:

    def test_get_profile_creates_if_missing(self, auth_client, user):
        url = reverse("v1:onboarding:profile")
        resp = auth_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert OnboardingProfile.objects.filter(user=user).exists()

    def test_get_profile_unauthenticated(self, api_client):
        url = reverse("v1:onboarding:profile")
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ── Step 1: Personal Info ─────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStep1PersonalInfo:

    def _url(self):
        return reverse("v1:onboarding:step", kwargs={"step": 1})

    def test_submit_step1_success(self, auth_client, user):
        resp = auth_client.patch(self._url(), {
            "full_name": "Sarah Johnson",
            "age": 28,
            "ethnicity": "white",
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        profile = OnboardingProfile.objects.get(user=user)
        assert profile.full_name == "Sarah Johnson"
        assert profile.age == 28

    def test_step1_advances_onboarding_step(self, auth_client, user):
        auth_client.patch(self._url(), {
            "full_name": "Sarah",
            "age": 28,
        }, format="json")
        user.refresh_from_db()
        assert user.onboarding_step >= 1

    def test_step1_invalid_age_too_young(self, auth_client):
        resp = auth_client.patch(self._url(), {
            "full_name": "Young",
            "age": 5,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_step1_invalid_age_too_old(self, auth_client):
        resp = auth_client.patch(self._url(), {
            "full_name": "Old",
            "age": 200,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Step 2: Physical Measurements ────────────────────────────────────────────

@pytest.mark.django_db
class TestStep2Physical:

    def _url(self):
        return reverse("v1:onboarding:step", kwargs={"step": 2})

    def test_submit_step2_computes_bmi(self, auth_client, user):
        resp = auth_client.patch(self._url(), {
            "height_cm": 165,
            "weight_kg": 62,
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        profile = OnboardingProfile.objects.get(user=user)
        # BMI = 62 / (1.65)^2 ≈ 22.8
        assert profile.bmi is not None
        assert 22.0 < profile.bmi < 24.0

    def test_step2_bmi_returned_in_response(self, auth_client):
        resp = auth_client.patch(self._url(), {
            "height_cm": 170,
            "weight_kg": 70,
        }, format="json")
        assert "bmi" in resp.data["data"]
        assert resp.data["data"]["bmi"] is not None

    def test_step2_invalid_height(self, auth_client):
        resp = auth_client.patch(self._url(), {
            "height_cm": 10,   # too short
            "weight_kg": 60,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_step2_invalid_weight(self, auth_client):
        resp = auth_client.patch(self._url(), {
            "height_cm": 165,
            "weight_kg": 5,    # too light
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Step 3: Skin Changes ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStep3SkinChanges:

    def _url(self):
        return reverse("v1:onboarding:step", kwargs={"step": 3})

    def test_submit_yes(self, auth_client, user):
        resp = auth_client.patch(self._url(), {"has_skin_changes": True}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert OnboardingProfile.objects.get(user=user).has_skin_changes is True

    def test_submit_no(self, auth_client, user):
        resp = auth_client.patch(self._url(), {"has_skin_changes": False}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert OnboardingProfile.objects.get(user=user).has_skin_changes is False

    def test_null_rejected(self, auth_client):
        resp = auth_client.patch(self._url(), {"has_skin_changes": None}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Step 4: Menstrual History ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestStep4Menstrual:

    def _url(self):
        return reverse("v1:onboarding:step", kwargs={"step": 4})

    def test_submit_step4_success(self, auth_client, user):
        resp = auth_client.patch(self._url(), {
            "cycle_length_days": 28,
            "periods_per_year": 12,
            "cycle_regularity": "regular",
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        profile = OnboardingProfile.objects.get(user=user)
        assert profile.cycle_length_days == 28
        assert profile.cycle_regularity == "regular"

    def test_cycle_length_too_long(self, auth_client):
        resp = auth_client.patch(self._url(), {
            "cycle_length_days": 200,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_periods_per_year_too_many(self, auth_client):
        resp = auth_client.patch(self._url(), {
            "periods_per_year": 20,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Step 5: Wearable ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStep5Wearable:

    def _url(self):
        return reverse("v1:onboarding:step", kwargs={"step": 5})

    def test_select_apple_watch(self, auth_client, user):
        resp = auth_client.patch(self._url(), {"selected_wearable": "apple_watch"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert OnboardingProfile.objects.get(user=user).selected_wearable == "apple_watch"

    def test_skip_wearable(self, auth_client, user):
        resp = auth_client.patch(self._url(), {"selected_wearable": "none"}, format="json")
        assert resp.status_code == status.HTTP_200_OK


# ── Step 6: rPPG ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStep6Rppg:

    url = reverse("v1:onboarding:rppg")

    def test_mark_rppg_captured(self, auth_client, user):
        resp = auth_client.post(self.url, {"baseline_captured": True}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        profile = OnboardingProfile.objects.get(user=user)
        assert profile.rppg_baseline_captured is True
        assert profile.rppg_captured_at is not None

    def test_rppg_false_returns_error(self, auth_client):
        resp = auth_client.post(self.url, {"baseline_captured": False}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Complete Onboarding ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOnboardingComplete:

    url = reverse("v1:onboarding:complete")

    def test_complete_sets_flag(self, auth_client, user):
        resp = auth_client.post(self.url)
        assert resp.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.onboarding_completed is True
        assert user.onboarding_step == 6

    def test_invalid_step_returns_404(self, auth_client):
        url = reverse("v1:onboarding:step", kwargs={"step": 99})
        resp = auth_client.patch(url, {}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
