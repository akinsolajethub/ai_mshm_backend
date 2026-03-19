"""
core/middleware.py
──────────────────
Reusable middleware components:
  - RequestLoggingMiddleware  : structured request/response logging
  - JWTAuthMiddlewareStack    : JWT auth for Django Channels WebSocket
"""
import logging
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)

User = get_user_model()


# ── HTTP Middleware ───────────────────────────────────────────────────────────

class RequestLoggingMiddleware:
    """Log method, path, status code and response time for every request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            "http_request",
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "user": str(request.user),
            },
        )
        return response


# ── WebSocket JWT Auth ────────────────────────────────────────────────────────

@database_sync_to_async
def _get_user_from_token(token_key: str):
    """Validate a raw JWT and return the corresponding User or AnonymousUser."""
    from rest_framework_simplejwt.tokens import AccessToken
    from rest_framework_simplejwt.exceptions import TokenError

    try:
        token = AccessToken(token_key)
        return User.objects.get(id=token["user_id"])
    except (TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Attach authenticated user to WebSocket scope.
    Token should be passed as a query param: ws://host/ws/.../?token=<access_token>
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        token_list = params.get("token", [])

        if token_list:
            scope["user"] = await _get_user_from_token(token_list[0])
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """Convenience wrapper matching Channels' AuthMiddlewareStack signature."""
    return JWTAuthMiddleware(inner)
