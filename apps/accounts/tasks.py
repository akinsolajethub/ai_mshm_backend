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
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured — skipping email to %s (subject: %s)", to, subject)
        return
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(
        {
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": plain,
        }
    )


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="accounts.send_verification_email",
)
def send_verification_email_task(
    self, user_id: str, user_name: str, user_email: str, verify_url: str
):
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


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="accounts.send_staff_credentials_email",
)
def send_staff_credentials_email_task(
    self,
    user_name: str,
    user_email: str,
    temp_password: str,
    facility_name: str,
    role: str,
    unique_id: str = None,
):
    html = render_to_string(
        "emails/staff_credentials.html",
        {
            "user_name": user_name,
            "temp_password": temp_password,
            "facility_name": facility_name,
            "role": role,
            "unique_id": unique_id,
            "app_name": settings.APP_NAME,
        },
    )
    plain = (
        f"Hi {user_name},\n\n"
        f"Welcome to {settings.APP_NAME}!\n\n"
        f"Your account has been created at {facility_name} as {role}.\n\n"
        f"Your ID: {unique_id or 'N/A'}\n"
        f"Temporary Password: {temp_password}\n\n"
        f"Please login and change your password immediately.\n\n"
        f"— The {settings.APP_NAME} Team"
    )
    _send_email(user_email, f"Your {settings.APP_NAME} Login Credentials", html, plain)
    logger.info("Staff credentials email sent to %s", user_email)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="accounts.send_facility_admin_assignment_email",
)
def send_facility_admin_assignment_email_task(
    self,
    user_name: str,
    user_email: str,
    facility_name: str,
    facility_type: str,
):
    """
    Send email when a user is assigned as admin to a facility.
    """
    login_url = getattr(settings, 'FRONTEND_URL', 'https://ai-mshm.vercel.app')
    
    # Determine login path based on facility type
    login_paths = {
        'PHC': '/phc/login',
        'FMC': '/fmc/login',
        'STH': '/sth/login',
        'STTH': '/stth/login',
        'FTH': '/fth/login',
        'HMO': '/hmo/login',
        'CLN': '/cln/login',
        'PVT': '/pvt/login',
        'PTTH': '/ptth/login',
    }
    login_path = login_paths.get(facility_type, '/login')
    
    html = render_to_string(
        "emails/facility_admin_assignment.html",
        {
            "user_name": user_name,
            "facility_name": facility_name,
            "facility_type": facility_type,
            "login_url": f"{login_url}{login_path}",
            "app_name": settings.APP_NAME,
        },
    )
    plain = (
        f"Hi {user_name},\n\n"
        f"You have been assigned as Admin for {facility_name} ({facility_type}).\n\n"
        f"You can now login to manage this facility.\n\n"
        f"Login URL: {login_url}{login_path}\n\n"
        f"If you have any questions, please contact your system administrator.\n\n"
        f"— The {settings.APP_NAME} Team"
    )
    _send_email(user_email, f"You've been assigned as Admin for {facility_name}", html, plain)
    logger.info("Facility admin assignment email sent to %s for facility %s", user_email, facility_name)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="accounts.send_patient_welcome_email",
)
def send_patient_welcome_email_task(
    self,
    user_name: str,
    user_email: str,
    temp_password: str,
    facility_name: str,
    unique_id: str = None,
):
    """
    Send welcome email to a newly registered patient with login credentials.
    """
    login_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
    patient_login_path = '/login'

    html = render_to_string(
        "emails/patient_welcome.html",
        {
            "user_name": user_name,
            "temp_password": temp_password,
            "facility_name": facility_name,
            "unique_id": unique_id,
            "login_url": f"{login_url}{patient_login_path}",
            "app_name": settings.APP_NAME,
        },
    )
    plain = (
        f"Hi {user_name},\n\n"
        f"Welcome to {settings.APP_NAME}!\n\n"
        f"You have been registered as a patient at {facility_name}.\n\n"
        f"Your Patient ID: {unique_id or 'N/A'}\n"
        f"Temporary Password: {temp_password}\n\n"
        f"Login URL: {login_url}{patient_login_path}\n\n"
        f"Please login and complete your onboarding.\n\n"
        f"— The {settings.APP_NAME} Team"
    )
    _send_email(user_email, f"Welcome to {settings.APP_NAME} – Your Login Credentials", html, plain)
    logger.info("Patient welcome email sent to %s", user_email)
