"""
apps/accounts/tests/test_auth.py
──────────────────────────────────
Full test coverage for all auth endpoints.
Run: pytest apps/accounts/tests/ -v
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import EmailVerificationToken, PasswordResetToken
from core.utils.helpers import generate_secure_token, hash_token, token_expiry

User = get_user_model()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def unverified_user(db):
    return User.objects.create_user(
        email="unverified@test.com",
        full_name="Unverified User",
        password="TestPass1234!",
        role="patient",
        is_email_verified=False,
    )


@pytest.fixture
def verified_user(db):
    return User.objects.create_user(
        email="verified@test.com",
        full_name="Verified User",
        password="TestPass1234!",
        role="patient",
        is_email_verified=True,
    )


@pytest.fixture
def auth_client(api_client, verified_user):
    """API client already authenticated as verified_user."""
    url = reverse("v1:accounts:login")
    resp = api_client.post(url, {
        "email": "verified@test.com",
        "password": "TestPass1234!",
    }, format="json")
    token = resp.data["data"]["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


# ── Registration ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRegister:
    url = reverse("v1:accounts:register")  # lazy — resolved at test time via pytest-django

    def test_register_patient_success(self, api_client):
        resp = api_client.post(self.url, {
            "full_name": "Sarah Johnson",
            "email": "sarah@test.com",
            "password": "SecurePass1!",
            "confirm_password": "SecurePass1!",
            "role": "patient",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["status"] == "success"
        assert "email" in resp.data["data"]
        assert User.objects.filter(email="sarah@test.com").exists()

    def test_register_clinician_success(self, api_client):
        resp = api_client.post(self.url, {
            "full_name": "Dr. James Okafor",
            "email": "dr.james@clinic.com",
            "password": "SecurePass1!",
            "confirm_password": "SecurePass1!",
            "role": "clinician",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["data"]["role"] == "clinician"

    def test_register_duplicate_email(self, api_client, verified_user):
        resp = api_client.post(self.url, {
            "full_name": "Duplicate",
            "email": "verified@test.com",   # already exists
            "password": "SecurePass1!",
            "confirm_password": "SecurePass1!",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["status"] == "error"

    def test_register_password_mismatch(self, api_client):
        resp = api_client.post(self.url, {
            "full_name": "Test User",
            "email": "new@test.com",
            "password": "SecurePass1!",
            "confirm_password": "DifferentPass!",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "confirm_password" in str(resp.data["errors"])

    def test_register_admin_role_rejected(self, api_client):
        resp = api_client.post(self.url, {
            "full_name": "Hacker",
            "email": "hacker@test.com",
            "password": "SecurePass1!",
            "confirm_password": "SecurePass1!",
            "role": "admin",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_weak_password_rejected(self, api_client):
        resp = api_client.post(self.url, {
            "full_name": "Test",
            "email": "weak@test.com",
            "password": "123",
            "confirm_password": "123",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_new_user_is_unverified(self, api_client):
        api_client.post(self.url, {
            "full_name": "New User",
            "email": "newuser@test.com",
            "password": "SecurePass1!",
            "confirm_password": "SecurePass1!",
        }, format="json")
        user = User.objects.get(email="newuser@test.com")
        assert user.is_email_verified is False


# ── Email Verification ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestEmailVerification:
    verify_url   = reverse("v1:accounts:verify-email")
    resend_url   = reverse("v1:accounts:resend-verification")

    def _create_valid_token(self, user):
        raw = generate_secure_token()
        EmailVerificationToken.objects.update_or_create(
            user=user,
            defaults={"token_hash": hash_token(raw), "expires_at": token_expiry(24)},
        )
        return raw

    def test_verify_email_success(self, api_client, unverified_user):
        raw = self._create_valid_token(unverified_user)
        resp = api_client.post(self.verify_url, {"token": raw}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        unverified_user.refresh_from_db()
        assert unverified_user.is_email_verified is True

    def test_verify_email_invalid_token(self, api_client):
        resp = api_client.post(self.verify_url, {"token": "invalid-token-xyz"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["status"] == "error"

    def test_verify_email_expired_token(self, api_client, unverified_user):
        from datetime import timedelta
        from django.utils import timezone
        raw = generate_secure_token()
        EmailVerificationToken.objects.create(
            user=unverified_user,
            token_hash=hash_token(raw),
            expires_at=timezone.now() - timedelta(hours=1),  # already expired
        )
        resp = api_client.post(self.verify_url, {"token": raw}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_resend_verification_returns_200_always(self, api_client):
        """Should return 200 even for non-existent email (anti-enumeration)."""
        resp = api_client.post(self.resend_url, {"email": "ghost@test.com"}, format="json")
        assert resp.status_code == status.HTTP_200_OK


# ── Login ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLogin:
    url = reverse("v1:accounts:login")

    def test_login_success(self, api_client, verified_user):
        resp = api_client.post(self.url, {
            "email": "verified@test.com",
            "password": "TestPass1234!",
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert "access" in resp.data["data"]
        assert "refresh" in resp.data["data"]
        assert resp.data["data"]["user"]["email"] == "verified@test.com"

    def test_login_unverified_blocked(self, api_client, unverified_user):
        resp = api_client.post(self.url, {
            "email": "unverified@test.com",
            "password": "TestPass1234!",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_login_wrong_password(self, api_client, verified_user):
        resp = api_client.post(self.url, {
            "email": "verified@test.com",
            "password": "WrongPassword!",
        }, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_unknown_email(self, api_client):
        resp = api_client.post(self.url, {
            "email": "nobody@test.com",
            "password": "TestPass1234!",
        }, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ── Password Reset ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPasswordReset:
    forgot_url = reverse("v1:accounts:forgot-password")
    reset_url  = reverse("v1:accounts:reset-password")

    def test_forgot_password_returns_200_for_unknown_email(self, api_client):
        """Anti-enumeration: always 200."""
        resp = api_client.post(self.forgot_url, {"email": "ghost@test.com"}, format="json")
        assert resp.status_code == status.HTTP_200_OK

    def test_forgot_password_creates_token(self, api_client, verified_user):
        api_client.post(self.forgot_url, {"email": "verified@test.com"}, format="json")
        assert PasswordResetToken.objects.filter(user=verified_user).exists()

    def test_reset_password_success(self, api_client, verified_user):
        raw = generate_secure_token()
        PasswordResetToken.objects.create(
            user=verified_user,
            token_hash=hash_token(raw),
            expires_at=token_expiry(2),
        )
        resp = api_client.post(self.reset_url, {
            "token": raw,
            "password": "NewSecure1234!",
            "confirm_password": "NewSecure1234!",
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        verified_user.refresh_from_db()
        assert verified_user.check_password("NewSecure1234!")

    def test_reset_password_invalid_token(self, api_client):
        resp = api_client.post(self.reset_url, {
            "token": "fake-token",
            "password": "NewSecure1234!",
            "confirm_password": "NewSecure1234!",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_reset_token_cannot_be_reused(self, api_client, verified_user):
        raw = generate_secure_token()
        PasswordResetToken.objects.create(
            user=verified_user,
            token_hash=hash_token(raw),
            expires_at=token_expiry(2),
        )
        # First use succeeds
        api_client.post(self.reset_url, {
            "token": raw,
            "password": "NewSecure1234!",
            "confirm_password": "NewSecure1234!",
        }, format="json")
        # Second use must fail
        resp = api_client.post(self.reset_url, {
            "token": raw,
            "password": "AnotherPass1234!",
            "confirm_password": "AnotherPass1234!",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Me endpoints ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestMeEndpoints:
    me_url = reverse("v1:accounts:me")

    def test_get_me_authenticated(self, auth_client, verified_user):
        resp = auth_client.get(self.me_url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["email"] == "verified@test.com"

    def test_get_me_unauthenticated(self, api_client):
        resp = api_client.get(self.me_url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_full_name(self, auth_client, verified_user):
        resp = auth_client.patch(self.me_url, {"full_name": "Updated Name"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        verified_user.refresh_from_db()
        assert verified_user.full_name == "Updated Name"

    def test_change_password(self, auth_client, verified_user):
        url = reverse("v1:accounts:change-password")
        resp = auth_client.post(url, {
            "old_password": "TestPass1234!",
            "new_password": "BrandNew1234!",
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        verified_user.refresh_from_db()
        assert verified_user.check_password("BrandNew1234!")

    def test_change_password_wrong_old(self, auth_client):
        url = reverse("v1:accounts:change-password")
        resp = auth_client.post(url, {
            "old_password": "WrongOld!",
            "new_password": "BrandNew1234!",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
