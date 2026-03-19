"""
apps/accounts/services.py
──────────────────────────
All auth business logic lives here — views just validate input and call services.
This keeps views thin and logic testable in isolation.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.utils.helpers import (
    generate_secure_token,
    hash_token,
    token_expiry,
    build_frontend_url,
)
from .models import EmailVerificationToken, PasswordResetToken
from .tasks import send_verification_email_task, send_password_reset_email_task
from core.utils.celery_helpers import run_task

logger = logging.getLogger(__name__)
User = get_user_model()


class AuthService:
    # ── Registration ──────────────────────────────────────────────────────────

    @staticmethod
    def register(validated_data: dict) -> User:
        """
        Create user, generate email verification token, queue email.
        Returns the newly created (unverified) user.
        """
        user = User.objects.create_user(**validated_data)
        AuthService._create_and_send_verification_token(user)
        logger.info("New user registered: %s (role=%s)", user.email, user.role)
        return user

    # ── Email Verification ────────────────────────────────────────────────────

    @staticmethod
    def _create_and_send_verification_token(user: User) -> str:
        raw_token = generate_secure_token()
        hashed    = hash_token(raw_token)
        expires   = token_expiry(hours=settings.EMAIL_VERIFICATION_EXPIRY_HOURS)

        EmailVerificationToken.objects.update_or_create(
            user=user,
            defaults={"token_hash": hashed, "expires_at": expires},
        )

        verify_url = build_frontend_url(f"verify-email?token={raw_token}")
        run_task(
            send_verification_email_task,
            user_id=str(user.id),
            user_name=user.display_name,
            user_email=user.email,
            verify_url=verify_url,
        )
        return raw_token

    @staticmethod
    def verify_email(raw_token: str) -> User:
        hashed = hash_token(raw_token)
        try:
            token_obj = EmailVerificationToken.objects.select_related("user").get(
                token_hash=hashed
            )
        except EmailVerificationToken.DoesNotExist:
            raise ValueError("Invalid or expired verification token.")

        if token_obj.is_expired():
            raise ValueError("Verification token has expired. Please request a new one.")

        user = token_obj.user
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])
        token_obj.delete()
        logger.info("Email verified: %s", user.email)
        return user

    @staticmethod
    def resend_verification(email: str) -> None:
        try:
            user = User.objects.get(email=email, is_email_verified=False)
        except User.DoesNotExist:
            # Don't reveal whether email exists — just return silently
            return
        AuthService._create_and_send_verification_token(user)

    # ── Password Reset ────────────────────────────────────────────────────────

    @staticmethod
    def forgot_password(email: str) -> None:
        """Always returns silently to prevent email enumeration."""
        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return

        raw_token = generate_secure_token()
        hashed    = hash_token(raw_token)
        expires   = token_expiry(hours=settings.PASSWORD_RESET_EXPIRY_HOURS)

        PasswordResetToken.objects.create(
            user=user, token_hash=hashed, expires_at=expires
        )

        reset_url = build_frontend_url(f"reset-password?token={raw_token}")
        run_task(
            send_password_reset_email_task,
            user_name=user.display_name,
            user_email=user.email,
            reset_url=reset_url,
        )

    @staticmethod
    def reset_password(raw_token: str, new_password: str) -> None:
        hashed = hash_token(raw_token)
        try:
            token_obj = PasswordResetToken.objects.select_related("user").get(
                token_hash=hashed, is_used=False
            )
        except PasswordResetToken.DoesNotExist:
            raise ValueError("Invalid or expired reset token.")

        if token_obj.is_expired():
            raise ValueError("Reset token has expired. Please request a new one.")

        user = token_obj.user
        user.set_password(new_password)
        user.save(update_fields=["password"])

        token_obj.is_used = True
        token_obj.save(update_fields=["is_used"])

        # Invalidate all other reset tokens for this user
        PasswordResetToken.objects.filter(user=user, is_used=False).update(is_used=True)
        logger.info("Password reset successful: %s", user.email)
