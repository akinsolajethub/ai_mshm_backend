"""
AI-MSHM – Production Settings
"""

import os
from .base import *  # noqa
import sentry_sdk
from decouple import config

DEBUG = False
ALLOWED_HOSTS = ["*"]

# ── CORS ──────────────────────────────────────────────────────────────────────
# Parse comma-separated origins from env variable
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8080"
    ).split(",")
    if origin.strip()
]

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = True  # TEMPORARY: Remove after confirming CORS works

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

# ── Email (Resend via django-anymail) ────────────────────────────────────────
EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"

ANYMAIL = {
    "RESEND_API_KEY": os.environ.get("RESEND_API_KEY", ""),
}

DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    "AI-MSHM <noreply@devalyze.space>",
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ── Security hardening ────────────────────────────────────────────────────────
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = False
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# ── Channel Layers (WebSocket support) ──────────────────────────────────────
USE_IN_MEMORY_CHANNELS = config("USE_IN_MEMORY_CHANNELS", default="False") == "True"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

if USE_IN_MEMORY_CHANNELS:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
else:
    # Parse Upstash Redis URL to handle SSL params
    redis_address = REDIS_URL.split("?")[0]  # strip query params like ?ssl_cert_reqs=CERT_NONE
    redis_ssl = REDIS_URL.startswith("rediss://")

    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [
                    {
                        "address": redis_address,
                        "ssl": redis_ssl,
                        "ssl_cert_reqs": None,  # disable cert verification for Upstash
                    }
                ],
            },
        },
    }

# ── Sentry error tracking ──────────────────────────────────────────────────────
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
    )

# ── Production logging ────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "pythonjsonlogger.jsonlogger.JsonFormatter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}
