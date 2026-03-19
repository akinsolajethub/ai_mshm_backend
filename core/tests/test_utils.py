"""
core/tests/test_utils.py
─────────────────────────
Tests for core utility functions.
"""
import pytest
from datetime import timedelta
from django.utils import timezone

from core.utils.helpers import (
    generate_otp,
    generate_secure_token,
    hash_token,
    utc_now,
    token_expiry,
    is_expired,
    build_frontend_url,
    safe_get,
)


class TestGenerateOtp:
    def test_default_length_is_6(self):
        otp = generate_otp()
        assert len(otp) == 6

    def test_custom_length(self):
        otp = generate_otp(length=8)
        assert len(otp) == 8

    def test_numeric_only(self):
        otp = generate_otp()
        assert otp.isdigit()

    def test_randomness(self):
        otps = {generate_otp() for _ in range(20)}
        assert len(otps) > 1  # extremely unlikely to be all equal


class TestGenerateSecureToken:
    def test_returns_string(self):
        token = generate_secure_token()
        assert isinstance(token, str)

    def test_minimum_length(self):
        token = generate_secure_token()
        assert len(token) >= 32

    def test_url_safe(self):
        import re
        token = generate_secure_token()
        assert re.match(r"^[A-Za-z0-9_\-]+$", token)

    def test_unique_tokens(self):
        tokens = {generate_secure_token() for _ in range(10)}
        assert len(tokens) == 10


class TestHashToken:
    def test_same_input_same_hash(self):
        token = "my_test_token"
        assert hash_token(token) == hash_token(token)

    def test_different_tokens_different_hashes(self):
        assert hash_token("token_a") != hash_token("token_b")

    def test_hash_is_hex_64_chars(self):
        h = hash_token("anything")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestTimeHelpers:
    def test_utc_now_is_timezone_aware(self):
        now = utc_now()
        assert now.tzinfo is not None

    def test_token_expiry_default_24h(self):
        expiry = token_expiry()
        diff = expiry - utc_now()
        assert 23 * 3600 < diff.total_seconds() < 25 * 3600

    def test_token_expiry_custom_hours(self):
        expiry = token_expiry(hours=2)
        diff = expiry - utc_now()
        assert 1 * 3600 < diff.total_seconds() < 3 * 3600

    def test_is_expired_past_date(self):
        past = utc_now() - timedelta(hours=1)
        assert is_expired(past) is True

    def test_is_expired_future_date(self):
        future = utc_now() + timedelta(hours=1)
        assert is_expired(future) is False


class TestBuildFrontendUrl:
    def test_builds_absolute_url(self, settings):
        settings.FRONTEND_URL = "http://localhost:3000"
        url = build_frontend_url("verify-email?token=abc")
        assert url == "http://localhost:3000/verify-email?token=abc"

    def test_handles_trailing_slash_on_base(self, settings):
        settings.FRONTEND_URL = "http://localhost:3000/"
        url = build_frontend_url("reset-password")
        assert url == "http://localhost:3000/reset-password"

    def test_handles_leading_slash_on_path(self, settings):
        settings.FRONTEND_URL = "http://localhost:3000"
        url = build_frontend_url("/verify-email")
        assert url == "http://localhost:3000/verify-email"


class TestSafeGet:
    def test_simple_key(self):
        d = {"a": 1}
        assert safe_get(d, "a") == 1

    def test_nested_keys(self):
        d = {"a": {"b": {"c": 42}}}
        assert safe_get(d, "a", "b", "c") == 42

    def test_missing_key_returns_default(self):
        d = {"a": 1}
        assert safe_get(d, "b") is None
        assert safe_get(d, "b", default="fallback") == "fallback"

    def test_non_dict_intermediate(self):
        d = {"a": "not_a_dict"}
        assert safe_get(d, "a", "b") is None

    def test_empty_dict(self):
        assert safe_get({}, "anything") is None
