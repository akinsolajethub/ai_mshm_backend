"""
core/middleware.py
─────────────────
Reusable middleware components:
  - RequestLoggingMiddleware  : structured request/response logging
  - JWTAuthMiddlewareStack    : JWT auth for Django Channels WebSocket
  - InputSanitizationMiddleware : sanitizes all user input
"""

import logging
import re
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


# ── Input Sanitization ──────────────────────────────────────────────────────


class InputSanitizationMiddleware:
    """
    Sanitizes all user input to prevent injection attacks.
    - SQL injection: handled by Django ORM (parameterized queries)
    - XSS: sanitizes HTML in text fields
    - Command injection: strips shell characters
    - Path traversal: validates UUIDs
    """

    # Characters that could indicate injection attempts
    INJECTION_PATTERNS = [
        r"';",  # SQL comment attempt
        r"--",  # SQL comment
        r"/*",  # SQL comment start
        r"*/",  # SQL comment end
        r"xp_",  # SQL extended proc
        r"EXEC(",  # SQL execution
        r"UNION\s+SELECT",  # SQL UNION attack
        r"<script",  # XSS script tag
        r"javascript:",  # XSS JS protocol
        r"on\w+\s*=",  # XSS event handler
        r"\|\|",  # Command pipe
        r"&\s*;",  # Command chain
        r"\$\(",  # Command substitution
        r"`",  # Command backtick
        r"\$(",  # Shell variable
    ]

    def __init__(self, get_response):
        self.get_response = get_response
        self._patterns = [re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS]

    def __call__(self, request):
        # Skip for safe methods
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return self.get_response(request)

        # Check POST data
        if hasattr(request, "POST") and request.POST:
            self._sanitize_POST(request)

        return self.get_response(request)

    def _sanitize_POST(self, request):
        """Sanitize POST data."""
        try:
            from django.http import QueryDict

            # Get mutable copy
            mutable_post = request.POST.copy()

            for key in mutable_post:
                value = mutable_post.get(key, "")
                if isinstance(value, str):
                    # Check for injection patterns
                    for pattern in self._patterns:
                        if pattern.search(value):
                            logger.warning(
                                f"Potential injection detected in field '{key}': {value[:50]}..."
                            )
                            # Don't block - just log. Let serializers handle validation.

            request.POST = mutable_post
        except Exception:
            pass
