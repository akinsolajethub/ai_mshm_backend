"""
apps/accounts/views.py
───────────────────────
All auth endpoints. Views are intentionally thin — logic lives in services.py.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView, TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiResponse

from core.responses import success_response, created_response, error_response

logger = logging.getLogger(__name__)

from .services import AuthService
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

User = get_user_model()


# ── Registration ──────────────────────────────────────────────────────────────


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

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
    Custom login view that wraps SimpleJWT with rate limiting and proper response format.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(tags=["Auth"], summary="Login – obtain JWT token pair")
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            from django.contrib.auth import get_user_model

            User = get_user_model()

            identifier = request.data.get("email", "").strip().lower()
            user = None

            if identifier and "/" in identifier:
                try:
                    user = User.objects.get(unique_id__iexact=identifier)
                except User.DoesNotExist:
                    pass

            if not user:
                try:
                    user = User.objects.get(email=identifier)
                except User.DoesNotExist:
                    user = None

            if user:
                if not settings.DEBUG:
                    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
                    ip_address = (
                        x_forwarded_for.split(",")[0].strip()
                        if x_forwarded_for
                        else request.META.get("REMOTE_ADDR", "0.0.0.0")
                    )
                    AuthService.clear_failed_attempts(user.email)

                user_data = UserProfileSerializer(user, context={"request": request}).data
                original_data = response.data

                return Response(
                    {
                        "status": "success",
                        "message": "Login successful.",
                        "data": {
                            "access": original_data.get("access"),
                            "refresh": original_data.get("refresh"),
                            "user": user_data,
                        },
                    },
                    status=status.HTTP_200_OK,
                )

        if not settings.DEBUG:
            identifier = request.data.get("email", "").strip().lower()
            if identifier:
                x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
                ip_address = (
                    x_forwarded_for.split(",")[0].strip()
                    if x_forwarded_for
                    else request.META.get("REMOTE_ADDR", "0.0.0.0")
                )

                # Try to get email from unique_id for logging
                user = None
                if "/" in identifier:
                    try:
                        user = User.objects.get(unique_id__iexact=identifier)
                    except User.DoesNotExist:
                        pass
                if not user:
                    try:
                        user = User.objects.get(email=identifier)
                    except User.DoesNotExist:
                        pass

                if user:
                    AuthService.record_failed_attempt(user.email, ip_address)

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
        try:
            logger.info("VerifyEmailView: Starting verification")
            serializer = EmailVerificationSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            logger.info("VerifyEmailView: Serializer valid")

            token = serializer.validated_data.get("token")
            logger.info("VerifyEmailView: Token received, length=%d", len(token) if token else 0)

            user = AuthService.verify_email(token)
            logger.info("VerifyEmailView: AuthService.verify_email completed, user=%s", user.email)

            logger.info("VerifyEmailView: Generating JWT tokens")
            refresh = RefreshToken.for_user(user)
            logger.info("VerifyEmailView: JWT tokens generated")

            logger.info("VerifyEmailView: Serializing user profile")
            user_data = UserProfileSerializer(user, context={"request": request}).data
            logger.info("VerifyEmailView: User profile serialized")

            result = success_response(
                data={
                    **user_data,
                    "tokens": {
                        "refresh": str(refresh),
                        "access": str(refresh.access_token),
                    },
                },
                message="Email verified successfully.",
            )
            logger.info("VerifyEmailView: Success response created")
            return result

        except ValueError as e:
            logger.warning("VerifyEmailView: ValueError - %s", str(e))
            return error_response(str(e), http_status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Error in VerifyEmailView: %s", str(e))
            return error_response(
                message="An unexpected error occurred during email verification.",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

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
        request.user.must_change_password = False
        request.user.save(update_fields=["password", "must_change_password"])
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


# ── Admin Stats ──────────────────────────────────────────────────────────────


class AdminStatsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Admin"],
        summary="Get system statistics",
    )
    def get(self, request):
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        today = now.date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        from .models import User
        from apps.onboarding.models import OnboardingProfile
        from apps.predictions.models import RiskPrediction
        from apps.checkin.models import CheckIn

        total_users = User.objects.filter(role='patient').count()
        total_staff = User.objects.exclude(role='patient').count()
        facilities_count = User.objects.exclude(facility__isnull=True).values('facility').distinct().count()
        active_sessions = User.objects.filter(last_login__date=today).count()

        new_users_this_week = User.objects.filter(date_joined__gte=week_ago).count()
        new_users_this_month = User.objects.filter(date_joined__gte=month_ago).count()

        predictions_today = RiskPrediction.objects.filter(computed_at__date=today).count()
        predictions_this_week = RiskPrediction.objects.filter(computed_at__gte=week_ago).count()

        checkins_today = CheckIn.objects.filter(date=today).count()
        checkins_this_week = CheckIn.objects.filter(date__gte=week_ago).count()

        pending_onboardings = OnboardingProfile.objects.filter(
            onboarding_completed=False,
            onboarding_step__lt=7
        ).count()

        return Response({
            "success": True,
            "status": 200,
            "data": {
                "users": {
                    "total": total_users,
                    "total_staff": total_staff,
                    "new_this_week": new_users_this_week,
                    "new_this_month": new_users_this_month,
                },
                "facilities": {
                    "count": facilities_count,
                },
                "sessions": {
                    "active_today": active_sessions,
                },
                "predictions": {
                    "today": predictions_today,
                    "this_week": predictions_this_week,
                },
                "checkins": {
                    "today": checkins_today,
                    "this_week": checkins_this_week,
                },
                "onboardings": {
                    "pending": pending_onboardings,
                },
            },
        })


class AdminUsersListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Admin"],
        summary="List all users",
    )
    def get(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        role = request.query_params.get('role')
        status = request.query_params.get('status')
        search = request.query_params.get('search')
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))

        users = User.objects.all()

        if role:
            users = users.filter(role=role)
        if status == 'active':
            users = users.filter(is_active=True)
        elif status == 'inactive':
            users = users.filter(is_active=False)
        if search:
            users = users.filter(email__icontains=search) | users.filter(full_name__icontains=search)

        total = users.count()
        start = (page - 1) * page_size
        end = start + page_size
        users_page = users[start:end]

        return Response({
            "success": True,
            "status": 200,
            "data": {
                "users": [
                    {
                        "id": str(u.id),
                        "email": u.email,
                        "full_name": u.full_name,
                        "role": u.role,
                        "facility": u.facility,
                        "is_active": u.is_active,
                        "date_joined": u.date_joined.isoformat() if u.date_joined else None,
                        "last_login": u.last_login.isoformat() if u.last_login else None,
                    }
                    for u in users_page
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        })


class ActivityLogsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Admin"],
        summary="Get activity logs",
    )
    def get(self, request):
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from datetime import timedelta
        from apps.onboarding.models import OnboardingProfile

        User = get_user_model()

        action = request.query_params.get('action')
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 50))

        base_qs = OnboardingProfile.objects.select_related('user').order_by('-updated_at')

        if action == 'registration':
            base_qs = base_qs.filter(onboarding_step=1)
        elif action == 'onboarding':
            base_qs = base_qs.filter(onboarding_step__gt=1, onboarding_completed=False)
        elif action == 'completed':
            base_qs = base_qs.filter(onboarding_completed=True)

        total = base_qs.count()
        start = (page - 1) * page_size
        end = start + page_size
        logs_page = base_qs[start:end]

        logs = []
        for op in logs_page:
            if op.onboarding_completed:
                action_type = 'onboarding_completed'
            elif op.onboarding_step == 1:
                action_type = 'registration'
            else:
                action_type = f'onboarding_step_{op.onboarding_step}'

            logs.append({
                "id": str(op.id),
                "action": action_type,
                "user": op.user.full_name if op.user else 'Unknown',
                "email": op.user.email if op.user else '',
                "facility": op.health_centre,
                "timestamp": op.updated_at.isoformat(),
            })

        return Response({
            "success": True,
            "status": 200,
            "data": {
                "logs": logs,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        })
