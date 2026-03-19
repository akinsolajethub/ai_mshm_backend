"""
AI-MSHM – Root URL Configuration
All app-level URLs are versioned under /api/v1/
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from core.views import RootView, HealthCheckView, SimpleHealthView

# ── API v1 URL groups ─────────────────────────────────────────────────────────
api_v1_patterns = [
    path("auth/", include("apps.accounts.urls", namespace="accounts")),
    path("onboarding/", include("apps.onboarding.urls", namespace="onboarding")),
    path("notifications/", include("apps.notifications.urls", namespace="notifications")),
    path("settings/", include("apps.settings_app.urls", namespace="settings_app")),
    path("centers/", include("apps.centers.urls", namespace="centers")),
    path("checkin/", include("apps.health_checkin.urls", namespace="health_checkin")),
    path("predictions/", include("apps.predictions.urls", namespace="predictions")),
    path("health/", HealthCheckView.as_view(), name="internal-health"),
    path("", include("apps.ml_proxy.urls")),
]

urlpatterns = [
    # ── Admin ────────────────────────────────────────────────────────────────
    path("admin/", admin.site.urls),
    # ── API v1 ───────────────────────────────────────────────────────────────
    path("api/v1/", include((api_v1_patterns, "v1"))),
    # ── OpenAPI Schema & Docs ─────────────────────────────────────────────────
    path("", RootView.as_view(), name="root"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("health/", SimpleHealthView.as_view(), name="simple-health"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    try:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass
