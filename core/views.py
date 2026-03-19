import time
from django.conf import settings
from django.db import connections
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from core.responses import success_response, error_response
from drf_spectacular.utils import extend_schema

try:
    import redis
except ImportError:
    redis = None


class HealthCheckView(APIView):
    """
    Internal health check (Mongo + optional Redis)
    """
    permission_classes = [AllowAny]
    schema = None  # exclude from drf-spectacular / Swagger

    def get(self, request):
        checks = {}
        start = time.time()

        # MongoDB check
        try:
            connections["default"].cursor()
            checks["mongodb"] = "ok"
        except Exception as e:
            checks["mongodb"] = f"error: {e}"

        # Redis check if exists
        if getattr(settings, "REDIS_URL", None) and redis is not None:
            try:
                redis.from_url(settings.REDIS_URL).ping()
                checks["redis"] = "ok"
            except Exception as e:
                checks["redis"] = f"error: {e}"

        # Response time
        checks["response_time_ms"] = round((time.time() - start) * 1000)

        # Critical failure only if Mongo is down
        if "mongodb" in checks and checks["mongodb"] != "ok":
            return error_response(
                message="System unhealthy",
                data=checks,
                http_status=503,
            )

        return success_response(
            message="System online",
            data=checks,
        )


class SimpleHealthView(APIView):
    """
    User-facing health check (just service online)
    """
    permission_classes = [AllowAny]

    @extend_schema(tags=["System"], summary="Simple health probe")
    def get(self, request):
        return success_response(message="Service online")

    
class RootView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(tags=["System"], summary="API root")
    def get(self, request):
        return success_response(
            message="Welcome to AI-MSHM API",
            data={"docs": "/api/docs/", "redoc": "/api/redoc/"}
        )