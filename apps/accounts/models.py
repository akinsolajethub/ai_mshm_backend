"""
apps/accounts/models.py
────────────────────────
Custom User model + EmailVerificationToken + PasswordResetToken.

Role hierarchy (top → bottom):
  ADMIN        – Platform superuser. Uses Django /admin/ panel only.
                 Created via: python manage.py createsuperuser
  HCC_ADMIN    – Primary Health Centre admin. Created by Platform Admin.
                 Manages one PHC facility and its staff accounts.
  HCC_STAFF    – PHC health worker / nurse. Created by HCC Admin.
                 Screens patients, sends lifestyle advice, escalates to FMC.
                 Uses PHC portal (green, screens PHC1–PHC9).
  FHC_ADMIN    – Federal Medical Centre admin. Created by Platform Admin.
                 Manages one FMC facility, its staff, and clinician accounts.
  FHC_STAFF    – FMC case coordinator. Created by FHC Admin.
                 Manages the High/Critical patient queue, assigns clinicians.
                 Uses FMC portal (red, screens FMC1–FMC9).
  CLINICIAN    – Licensed doctor affiliated with one FMC. Created by FHC Admin.
                 Treats assigned patients, writes prescriptions and plans.
                 Uses Clinician portal (navy, screens CL1–CL8).
  PATIENT      – End user. Self-registers via app or registered by HCC Staff.
                 Uses Patient portal (purple, screens P1–P9).

Account creation rules:
  - Patients self-register via POST /api/v1/auth/register/
    (or are registered by HCC staff via the walk-in registration endpoint)
  - Platform Admin creates HCC/FHC centers and their admin accounts
    via Django /admin/ panel
  - HCC Admin creates HCC Staff accounts via the PHC staff management API
  - FHC Admin creates FHC Staff and Clinician accounts via the FMC management API
  - No self-registration is allowed for staff, admin, or clinician roles
"""
import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from core.storage import AvatarStorage


class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str = None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        """
        Creates a platform-level superuser for the Django /admin/ panel.

        Usage:
            python manage.py createsuperuser
            # or
            python manage.py createsuperuser --email admin@example.com

        The created superuser can then log in at /admin/ and:
          - Create HealthCareCenter (PHC) and FederalHealthCenter (FMC) records
          - Create HCC Admin and FHC Admin user accounts
          - Monitor all platform data
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("is_email_verified", True)
    
        if not extra_fields.get("full_name"):
            extra_fields["full_name"] = "Platform Admin"
    
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Central user model shared across all roles.

    Role-specific extended profile data lives in separate models:
      - HCCStaffProfile  (centers app) — for hcc_staff users
      - ClinicianProfile (centers app) — for clinician users
      - OnboardingProfile (onboarding app) — for patient users

    HCC Admin and FHC Admin users do not have a separate profile model;
    their center linkage is via the reverse OneToOne on the center model
    (user.managed_hcc or user.managed_fhc).
    """

    class Role(models.TextChoices):
        PATIENT   = "patient",    "Patient"
        CLINICIAN = "clinician",  "Clinician / Doctor"
        HCC_STAFF = "hcc_staff",  "PHC Staff"
        HCC_ADMIN = "hcc_admin",  "PHC Admin"
        FHC_STAFF = "fhc_staff",  "FMC Staff"
        FHC_ADMIN = "fhc_admin",  "FMC Admin"
        ADMIN     = "admin",      "Platform Admin"

    # ── Core identity ─────────────────────────────────────────────────────────
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email     = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    role      = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.PATIENT,
        db_index=True,
    )

    # ── Auth state ────────────────────────────────────────────────────────────
    is_active         = models.BooleanField(default=True)
    is_staff          = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)

    # ── Onboarding progress (patients only) ───────────────────────────────────
    onboarding_completed = models.BooleanField(default=False)
    onboarding_step      = models.PositiveSmallIntegerField(default=0)  # 0–5

    # ── Avatar (Cloudinary) ───────────────────────────────────────────────────
    avatar = models.ImageField(storage=AvatarStorage(), null=True, blank=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    date_joined = models.DateTimeField(default=timezone.now)
    last_login  = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering      = ["-date_joined"]
        verbose_name  = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.email} ({self.role})"

    @property
    def display_name(self):
        return self.full_name or self.email.split("@")[0]

    # ── Role convenience properties ───────────────────────────────────────────

    @property
    def is_patient(self):
        return self.role == self.Role.PATIENT

    @property
    def is_clinician(self):
        return self.role == self.Role.CLINICIAN

    @property
    def is_hcc_staff(self):
        """True for PHC health workers (role=hcc_staff)."""
        return self.role == self.Role.HCC_STAFF

    @property
    def is_hcc_admin(self):
        """True for PHC facility administrators (role=hcc_admin)."""
        return self.role == self.Role.HCC_ADMIN

    @property
    def is_fhc_staff(self):
        """True for FMC case coordinators (role=fhc_staff)."""
        return self.role == self.Role.FHC_STAFF

    @property
    def is_fhc_admin(self):
        """True for FMC facility administrators (role=fhc_admin)."""
        return self.role == self.Role.FHC_ADMIN

    @property
    def is_any_hcc(self):
        """True for any user attached to a PHC facility (admin or staff)."""
        return self.role in (self.Role.HCC_ADMIN, self.Role.HCC_STAFF)

    @property
    def is_any_fhc(self):
        """True for any user attached to an FMC facility (admin, staff, or clinician)."""
        return self.role in (self.Role.FHC_ADMIN, self.Role.FHC_STAFF, self.Role.CLINICIAN)

    @property
    def is_center_admin(self):
        """True for either PHC or FMC administrators."""
        return self.role in (self.Role.HCC_ADMIN, self.Role.FHC_ADMIN)

    @property
    def is_platform_admin(self):
        return self.role == self.Role.ADMIN


# ── Email Verification ────────────────────────────────────────────────────────

class EmailVerificationToken(models.Model):
    """
    Short-lived token sent to a user's email to verify ownership.
    Stores a SHA-256 hash of the raw token — raw token is never persisted.
    Expiry configured via EMAIL_VERIFICATION_EXPIRY_HOURS in settings.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name="email_token")
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Email Verification Token"

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"EmailToken({self.user.email})"


# ── Password Reset ────────────────────────────────────────────────────────────

class PasswordResetToken(models.Model):
    """
    Short-lived token sent to a user's email to reset their password.
    Stores a SHA-256 hash of the raw token — raw token is never persisted.
    Expiry configured via PASSWORD_RESET_EXPIRY_HOURS in settings.
    Multiple outstanding tokens are allowed per user (all stored),
    but only the most recent unused, unexpired token is valid.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_tokens")
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    is_used    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Password Reset Token"
        ordering     = ["-created_at"]

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"PasswordReset({self.user.email})"
