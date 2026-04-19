"""
apps/accounts/urls.py
──────────────────────
Base prefix: /api/v1/auth/
"""

from django.urls import path
from .views import (
    RegisterView,
    LoginView,
    TokenRefreshViewDocs,
    LogoutView,
    VerifyEmailView,
    ResendVerificationView,
    ForgotPasswordView,
    ResetPasswordView,
    MeView,
    ChangePasswordView,
    DeleteAccountView,
    AdminStatsView,
    AdminUsersListView,
    AdminUserDetailView,
    ActivityLogsView,
)

app_name = "accounts"

urlpatterns = [
    # Registration & Login
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshViewDocs.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    # Email verification
    path("verify-email/", VerifyEmailView.as_view(), name="verify-email"),
    path("resend-verification/", ResendVerificationView.as_view(), name="resend-verification"),
    # Password reset
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    # Authenticated user
    path("me/", MeView.as_view(), name="me"),
    path("me/change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("me/delete/", DeleteAccountView.as_view(), name="delete-account"),
    # Admin endpoints
    path("stats/", AdminStatsView.as_view(), name="admin-stats"),
    path("users/", AdminUsersListView.as_view(), name="admin-users"),
    path("users/<str:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("logs/", ActivityLogsView.as_view(), name="activity-logs"),
]
