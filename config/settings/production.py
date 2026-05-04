"""
AI-MSHM – Production Settings
SECURE DEPLOYMENT CONFIGURATION
"""

import os
import logging
from datetime import timedelta
from .base import *  # noqa
import sentry_sdk
from decouple import config

DEBUG = False
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="ai-mshm-backend-d47t.onrender.com,ai-mshm-backend.onrender.com,localhost,127.0.0.1",
).split(",")

# ── HTTPS Enforcement ───────────────────────────────────────────
SECURE_SSL_REDIRECT = True  # Enforce HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# ── Session Security ────────────────────────────────────────────────
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTP_ONLY = True
SESSION_COOKIE_SAMESITE = "strict"
SESSION_COOKIE_AGE = 1800  # 30 minutes
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# CSRF Security
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "strict"

# Clickjacking Protection
X_FRAME_OPTIONS = "DENY"

# Additional Security Headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# ── CORS (Whitelist only in production) ───────────────────────────
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False  # Disabled - use whitelist only
CORS_PREFLIGHT_MAX_AGE = 3600  # 1 hour

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

# ── CACHING (Redis for production)──────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", ""),
    }
}

# ── JWT Settings (Shorter sessions for security) ────────────────
from datetime import timedelta as td

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": td(minutes=30),  # 30 minutes
    "REFRESH_TOKEN_LIFETIME": td(hours=24),  # 24 hours
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ── Database Security ─────────────────────────────────────────────
# Database should be accessed via internal network only
# Ensure DATABASE_URL uses internal network or private subnet

# ── Email (Resend via django-anymail) ────────────────────────────
EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"
ANYMAIL = {
    "RESEND_API_KEY": os.environ.get("RESEND_API_KEY"),
}
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    "AI-MSHM <noreply@devalyze.space>",
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ── Channel Layers (WebSocket support) ───────────────────────────
USE_IN_MEMORY_CHANNELS = config("USE_IN_MEMORY_CHANNELS", default="False") == "True"
_redis_raw = os.environ.get("REDIS_URL", "")

if _redis_raw.startswith("rediss://"):
    _redis_url = _redis_raw
    if "ssl_cert_reqs" not in _redis_url:
        sep = "&" if "?" in _redis_url else "?"
        _redis_url = _redis_url + sep + "ssl_cert_reqs=CERT_NONE"
else:
    _redis_url = _redis_raw

if USE_IN_MEMORY_CHANNELS:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [_redis_url],
                "ssl_cert_reqs": None,
            },
        },
    }

CELERY_BROKER_URL = _redis_url
CELERY_RESULT_BACKEND = _redis_url

# ── Sentry error tracking ────────────────────────────────────────
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
    )

# ── Security Logging ─────────────────────────────────────────────
# Render captures stdout/stderr automatically; skip file handler to avoid build errors
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "pythonjsonlogger.jsonlogger.JsonFormatter"},
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "loggers": {
        "django.security": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.auth": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.accounts": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}
