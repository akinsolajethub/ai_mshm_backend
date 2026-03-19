"""
apps/accounts/tasks.py
"""
import logging
import resend

from celery import shared_task
from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _send_email(to: str, subject: str, html: str, plain: str):
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send({
        "from": settings.DEFAULT_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": plain,
    })


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="accounts.send_verification_email",
)
def send_verification_email_task(self, user_id: str, user_name: str, user_email: str, verify_url: str):
    html = render_to_string(
        "emails/verify_email.html",
        {"user_name": user_name, "verify_url": verify_url, "app_name": settings.APP_NAME},
    )
    plain = (
        f"Hi {user_name},\n\n"
        f"Please verify your email by visiting:\n{verify_url}\n\n"
        f"This link expires in {settings.EMAIL_VERIFICATION_EXPIRY_HOURS} hours.\n\n"
        f"— The {settings.APP_NAME} Team"
    )
    _send_email(user_email, f"Verify your {settings.APP_NAME} email", html, plain)
    logger.info("Verification email sent to %s", user_email)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="accounts.send_password_reset_email",
)
def send_password_reset_email_task(self, user_name: str, user_email: str, reset_url: str):
    html = render_to_string(
        "emails/reset_password.html",
        {"user_name": user_name, "reset_url": reset_url, "app_name": settings.APP_NAME},
    )
    plain = (
        f"Hi {user_name},\n\n"
        f"Reset your password here:\n{reset_url}\n\n"
        f"This link expires in {settings.PASSWORD_RESET_EXPIRY_HOURS} hours.\n"
        f"If you didn't request this, please ignore this email.\n\n"
        f"— The {settings.APP_NAME} Team"
    )
    _send_email(user_email, f"Reset your {settings.APP_NAME} password", html, plain)
    logger.info("Password reset email sent to %s", user_email)