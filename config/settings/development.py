"""
AI-MSHM – Development Settings
Extends base. Run with: DJANGO_SETTINGS_MODULE=config.settings.development
"""

from .base import *  # noqa

DEBUG = True

ALLOWED_HOSTS = ["*"]

# ── CORS: Allow all origins for local development ──────────────────────────────
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:8080",
]

# ── Dev email: print to console ───────────────────────────────────────────────
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ── Disable throttling in dev ─────────────────────────────────────────────────
# Option A: Completely disable (uncomment next line)
# REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # type: ignore[index]

# Option B: Increase rate limits for testing
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["auth"] = "100/minute"
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["email_verify"] = "100/minute"

# ── Django Debug Toolbar (optional, install separately) ───────────────────────
try:
    import debug_toolbar  # noqa

    INSTALLED_APPS += ["debug_toolbar"]  # type: ignore[name-defined]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # type: ignore[name-defined]
    INTERNAL_IPS = ["127.0.0.1"]
except ImportError:
    pass

# ── Use local file storage in dev (skip Cloudinary) ──────────────────────────
# DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"

# ── Logging ───────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{levelname}] {asctime} {module}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "DEBUG"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
