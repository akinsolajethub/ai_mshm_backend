"""
core/throttles.py
──────────────────
Custom DRF throttle classes.

Usage in a view:
    from core.throttles import AuthRateThrottle, SensitiveEndpointThrottle

    class LoginView(APIView):
        throttle_classes = [AuthRateThrottle]
"""
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """
    Strict throttle for unauthenticated auth endpoints.
    10 requests / minute per IP.
    Protects: register, login, forgot-password, resend-verification.
    """
    scope = "auth"
    rate  = "10/minute"


class SensitiveEndpointThrottle(UserRateThrottle):
    """
    For authenticated sensitive actions: change-password, delete-account, export-data.
    5 requests / minute per user.
    """
    scope = "sensitive"
    rate  = "5/minute"


class EmailVerificationThrottle(AnonRateThrottle):
    """
    Prevents OTP / verification link abuse.
    3 requests / minute per IP.
    """
    scope = "email_verify"
    rate  = "3/minute"


class WebSocketConnectThrottle(AnonRateThrottle):
    """
    Throttle WebSocket connection attempts.
    Not used directly by DRF — wire via Channels middleware if needed.
    """
    scope = "ws_connect"
    rate  = "20/minute"
