"""
core/utils/helpers.py
──────────────────────
Small utility functions used across apps.
"""
import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

from django.conf import settings


# ── Token / OTP generation ────────────────────────────────────────────────────

def generate_otp(length: int = 6) -> str:
    """Return a numeric OTP of the given length."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_secure_token(nbytes: int = 32) -> str:
    """Return a URL-safe secure random token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 hash a token for safe DB storage."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── Time helpers ──────────────────────────────────────────────────────────────

def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def token_expiry(hours: int = 24) -> datetime:
    return utc_now() + timedelta(hours=hours)


def is_expired(dt: datetime) -> bool:
    return utc_now() > dt


# ── Misc ──────────────────────────────────────────────────────────────────────

def build_frontend_url(path: str) -> str:
    """Construct an absolute frontend URL."""
    base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def safe_get(d: dict, *keys: Any, default=None):
    """Safely traverse nested dicts."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d
