"""
apps/accounts/views.py
───────────────────────
All auth endpoints. Views are intentionally thin — logic lives in services.py.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiResponse

from core.responses import success_response, created_response, error_response
from .serializers import (
    RegisterSerializer,
    UserProfileSerializer,
    EmailVerificationSerializer,
    ResendVerificationSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    ChangePasswordSerializer,
    ConfirmPasswordSerializer,
    LogoutSerializer, 
    UpdateProfileSerializer,
)
from .services import AuthService

User = get_user_model()


# ── Registration ──────────────────────────────────────────────────────────────

class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [ScopedRateThrottle]
    throttle_scope     = "auth"

    @extend_schema(
        tags=["Auth"],
        request=RegisterSerializer,
        summary="Register a new user",
        description="Creates a Patient or Clinician account and sends an email verification link.",
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = AuthService.register(serializer.validated_data)
        return created_response(
            data=UserProfileSerializer(user, context={"request": request}).data,
            message="Account created. Please check your email to verify your account.",
        )


# ── Login / Token ─────────────────────────────────────────────────────────────

class LoginView(TokenObtainPairView):
    """
    Returns access + refresh tokens along with user profile.
    Inherits from SimpleJWT — custom payload added via CustomTokenObtainPairSerializer.
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope   = "auth"

    @extend_schema(tags=["Auth"], summary="Login – obtain JWT token pair")
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            return success_response(
                data=response.data,
                message="Login successful.",
            )
        return response


class TokenRefreshViewDocs(TokenRefreshView):
    @extend_schema(tags=["Auth"], summary="Refresh access token")
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


# ── Logout ────────────────────────────────────────────────────────────────────

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        request=LogoutSerializer,
        summary="Logout – blacklist refresh token",
    )
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return error_response("Refresh token is required.")
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            return error_response("Invalid or already blacklisted token.")
        return success_response(message="Logged out successfully.")


# ── Email Verification ────────────────────────────────────────────────────────

class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        request=EmailVerificationSerializer,
        summary="Verify email address",
    )
    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = AuthService.verify_email(serializer.validated_data["token"])
        except ValueError as e:
            return error_response(str(e), http_status=status.HTTP_400_BAD_REQUEST)

        # ── Generate tokens so the user is immediately logged in ──────────────
        refresh = RefreshToken.for_user(user)

        return success_response(
            data={
                **UserProfileSerializer(user, context={"request": request}).data,
                "tokens": {
                    "refresh": str(refresh),
                    "access":  str(refresh.access_token),
                },
            },
            message="Email verified successfully.",
        )


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        request=ResendVerificationSerializer,
        summary="Resend email verification link",
    )
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        AuthService.resend_verification(serializer.validated_data["email"])
        return success_response(
            message="If that email exists and is unverified, a new verification link has been sent."
        )


# ── Password Reset ────────────────────────────────────────────────────────────

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [ScopedRateThrottle]
    throttle_scope     = "auth"

    @extend_schema(
        tags=["Auth"],
        request=ForgotPasswordSerializer,
        summary="Request password reset email",
    )
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        AuthService.forgot_password(serializer.validated_data["email"])
        return success_response(
            message="If that email exists, a password reset link has been sent."
        )


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        request=ResetPasswordSerializer,
        summary="Reset password with token",
    )
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            AuthService.reset_password(
                raw_token=serializer.validated_data["token"],
                new_password=serializer.validated_data["password"],
            )
        except ValueError as e:
            return error_response(str(e), http_status=status.HTTP_400_BAD_REQUEST)
        return success_response(message="Password reset successful. You can now log in.")


# ── Authenticated User ────────────────────────────────────────────────────────

class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Get current user profile")
    def get(self, request):
        return success_response(
            data=UserProfileSerializer(request.user, context={"request": request}).data
        )

    @extend_schema(
        tags=["Auth"],
        request={
            "multipart/form-data": UpdateProfileSerializer,
        },
        summary="Update current user profile (name, avatar)",
        description=(
            "Send as `multipart/form-data` (not JSON) when uploading an avatar.\n\n"
            "- `full_name` — string (optional)\n"
            "- `avatar` — image file (optional, uploads to Cloudinary)"
        ),
    )
    def patch(self, request):
        serializer = UpdateProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=UserProfileSerializer(request.user, context={"request": request}).data,
            message="Profile updated.",
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        request=ChangePasswordSerializer,
        summary="Change password (authenticated)",
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return success_response(message="Password changed successfully.")


class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        request=ConfirmPasswordSerializer,
        summary="Delete account",
        description=(
            "Permanently deletes the authenticated user's account and all associated data. "
            "Requires current password confirmation. This action is irreversible."
        ),
    )
    def post(self, request):
        serializer = ConfirmPasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.delete()
        return success_response(message="Account deleted successfully.")