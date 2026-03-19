"""
apps/accounts/management/commands/seed_demo.py
────────────────────────────────────────────────
Creates realistic demo users for development and QA.

Usage:
    python manage.py seed_demo              # creates all demo users
    python manage.py seed_demo --flush      # wipes non-superusers first
    python manage.py seed_demo --quiet      # suppress output

Demo users created:
    patient@demo.com    / Demo1234!   (patient,   onboarding complete)
    clinician@demo.com  / Demo1234!   (clinician, onboarding complete)
    newuser@demo.com    / Demo1234!   (patient,   fresh — not onboarded)
"""
import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()
logger = logging.getLogger(__name__)

DEMO_PASSWORD = "Demo1234!"


class Command(BaseCommand):
    help = "Seed the database with demo users for development and QA"

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all non-superuser accounts before seeding",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Suppress output",
        )

    def handle(self, *args, **options):
        self.quiet = options["quiet"]

        if options["flush"]:
            deleted, _ = User.objects.filter(is_superuser=False).delete()
            self._print(f"🗑  Flushed {deleted} non-superuser accounts", "WARNING")

        self._create_centers()
        self._create_patient()
        self._create_clinician()
        self._create_hcc_admin()
        self._create_fhc_admin()
        self._create_new_user()

        self._print("\n✅  Demo seed complete.", "SUCCESS")
        self._print(f"   All passwords: {DEMO_PASSWORD}", "SUCCESS")

    # ── User creators ─────────────────────────────────────────────────────────

    def _create_patient(self):
        user, created = User.objects.get_or_create(
            email="patient@demo.com",
            defaults={
                "full_name": "Sarah Johnson",
                "role": User.Role.PATIENT,
                "is_email_verified": True,
                "onboarding_completed": True,
                "onboarding_step": 6,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self._seed_patient_data(user)
            self._print("👩  Created patient: patient@demo.com", "SUCCESS")
        else:
            self._print("👩  Patient already exists: patient@demo.com", "NOTICE")

    def _create_clinician(self):
        from apps.centers.models import HealthCareCenter, ClinicianProfile
        user, created = User.objects.get_or_create(
            email="clinician@demo.com",
            defaults={
                "full_name": "Dr. James Okafor",
                "role": User.Role.CLINICIAN,
                "is_email_verified": True,
                "onboarding_completed": True,
                "onboarding_step": 6,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self._print("👨‍⚕️  Created clinician: clinician@demo.com", "SUCCESS")
        else:
            self._print("👨‍⚕️  Clinician already exists: clinician@demo.com", "NOTICE")

    def _create_new_user(self):
        user, created = User.objects.get_or_create(
            email="newuser@demo.com",
            defaults={
                "full_name": "Alex Okonkwo",
                "role": User.Role.PATIENT,
                "is_email_verified": True,
                "onboarding_completed": False,
                "onboarding_step": 0,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self._print("🆕  Created new user: newuser@demo.com", "SUCCESS")
        else:
            self._print("🆕  New user already exists: newuser@demo.com", "NOTICE")

    def _create_centers(self):
        from apps.centers.models import HealthCareCenter, FederalHealthCenter
        hcc, created = HealthCareCenter.objects.get_or_create(
            code="LGH-001",
            defaults={
                "name": "Lagos General Hospital",
                "state": "Lagos",
                "lga": "Lagos Island",
                "address": "1 Marina Road, Lagos Island, Lagos",
                "phone": "+2348000000001",
                "email": "info@lgh.gov.ng",
                "status": "active",
                "notify_on_severe": True,
                "notify_on_very_severe": True,
            },
        )
        if created:
            self._print("🏥  Created HCC: Lagos General Hospital (LGH-001)", "SUCCESS")

        HealthCareCenter.objects.get_or_create(
            code="UCH-001",
            defaults={
                "name": "University College Hospital Ibadan",
                "state": "Oyo",
                "lga": "Ibadan North",
                "address": "Queen Elizabeth Rd, Ibadan, Oyo",
                "phone": "+2348000000002",
                "email": "info@uch.edu.ng",
                "status": "active",
                "notify_on_severe": True,
                "notify_on_very_severe": True,
            },
        )

        FederalHealthCenter.objects.get_or_create(
            code="FHC-ABJ-001",
            defaults={
                "name": "Federal Medical Centre Abuja",
                "state": "FCT",
                "zone": "North Central",
                "address": "PMB 053 Garki, Abuja FCT",
                "phone": "+2348000000010",
                "email": "info@fmcabuja.gov.ng",
                "status": "active",
            },
        )
        if created:
            self._print("🏛  Created FHC: Federal Medical Centre Abuja (FHC-ABJ-001)", "SUCCESS")

    def _create_hcc_admin(self):
        from apps.centers.models import HealthCareCenter
        hcc = HealthCareCenter.objects.filter(code="LGH-001").first()
        user, created = User.objects.get_or_create(
            email="hcc.admin@demo.com",
            defaults={
                "full_name": "Admin HCC Lagos",
                "role": User.Role.HCC_ADMIN,
                "is_email_verified": True,
                "onboarding_completed": True,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            if hcc:
                hcc.admin_user = user
                hcc.save(update_fields=["admin_user"])
            self._print("🏥  Created HCC admin: hcc.admin@demo.com", "SUCCESS")
        else:
            self._print("🏥  HCC admin already exists", "NOTICE")

    def _create_fhc_admin(self):
        from apps.centers.models import FederalHealthCenter
        fhc = FederalHealthCenter.objects.filter(code="FHC-ABJ-001").first()
        user, created = User.objects.get_or_create(
            email="fhc.admin@demo.com",
            defaults={
                "full_name": "Admin FHC Abuja",
                "role": User.Role.FHC_ADMIN,
                "is_email_verified": True,
                "onboarding_completed": True,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            if fhc:
                fhc.admin_user = user
                fhc.save(update_fields=["admin_user"])
            self._print("🏛  Created FHC admin: fhc.admin@demo.com", "SUCCESS")
        else:
            self._print("🏛  FHC admin already exists", "NOTICE")

    # ── Seed related data ─────────────────────────────────────────────────────

    def _seed_patient_data(self, user):
        """Populate onboarding profile, settings, and sample notifications."""
        from apps.onboarding.models import OnboardingProfile
        from apps.settings_app.models import (
            NotificationPreferences,
            ConnectedDevice,
            PrivacySettings,
        )
        from apps.notifications.models import Notification

        # Onboarding profile
        profile, _ = OnboardingProfile.objects.get_or_create(user=user)
        profile.full_name       = "Sarah Johnson"
        profile.age             = 28
        profile.ethnicity       = OnboardingProfile.Ethnicity.WHITE
        profile.height_cm       = 165.0
        profile.weight_kg       = 62.0
        profile.has_skin_changes = False
        profile.cycle_length_days = 28
        profile.periods_per_year  = 12
        profile.cycle_regularity  = OnboardingProfile.CycleRegularity.REGULAR
        profile.selected_wearable = OnboardingProfile.WearableDevice.APPLE_WATCH
        profile.rppg_baseline_captured = True
        profile.rppg_captured_at       = timezone.now()
        profile.save()

        # Notification preferences
        prefs, _ = NotificationPreferences.objects.get_or_create(user=user)
        prefs.morning_time = "08:00"
        prefs.evening_time = "20:00"
        prefs.morning_checkin_enabled   = True
        prefs.evening_checkin_enabled   = True
        prefs.weekly_prompts_enabled    = True
        prefs.period_alerts_enabled     = True
        prefs.risk_score_updates_enabled = True
        prefs.save()

        # Connected device
        ConnectedDevice.objects.get_or_create(
            user=user,
            device_type=ConnectedDevice.DeviceType.APPLE_WATCH,
            defaults={
                "device_name": "Apple Watch Series 9",
                "sync_frequency": ConnectedDevice.SyncFrequency.FIFTEEN_MIN,
                "background_sync": True,
                "is_connected": True,
                "last_synced_at": timezone.now(),
                "data_quality_pct": 72,
            },
        )

        # Privacy settings
        privacy, _ = PrivacySettings.objects.get_or_create(user=user)
        privacy.share_with_clinician = True
        privacy.model_improvement    = True
        privacy.save()

        # Sample notifications
        sample_notifications = [
            {
                "notification_type": Notification.NotificationType.SYSTEM,
                "title": "Welcome to AI-MSHM 🎉",
                "body": "Your account is set up. Complete onboarding to start tracking.",
                "priority": Notification.Priority.HIGH,
                "is_read": True,
            },
            {
                "notification_type": Notification.NotificationType.RISK_UPDATE,
                "title": "PCOS risk score updated",
                "body": "Your PCOS risk score has changed from 45 to 62. Tap to view details.",
                "priority": Notification.Priority.HIGH,
                "is_read": False,
                "data": {"condition": "pcos", "new_score": 62, "previous_score": 45},
            },
            {
                "notification_type": Notification.NotificationType.MORNING_CHECKIN,
                "title": "Good morning! ☀️",
                "body": "Time for your morning check-in.",
                "priority": Notification.Priority.MEDIUM,
                "is_read": False,
            },
            {
                "notification_type": Notification.NotificationType.WEEKLY_PROMPT,
                "title": "Weekly assessment due 📋",
                "body": "Your mFG score and PHQ-4 assessment are ready.",
                "priority": Notification.Priority.MEDIUM,
                "is_read": False,
            },
        ]

        for n in sample_notifications:
            data = n.pop("data", {})
            Notification.objects.get_or_create(
                recipient=user,
                title=n["title"],
                defaults={**n, "data": data},
            )

    # ── Output helper ─────────────────────────────────────────────────────────

    def _print(self, message: str, style: str = ""):
        if self.quiet:
            return
        style_map = {
            "SUCCESS": self.style.SUCCESS,
            "WARNING": self.style.WARNING,
            "ERROR":   self.style.ERROR,
            "NOTICE":  self.style.NOTICE,
        }
        styled = style_map.get(style, lambda x: x)(message)
        self.stdout.write(styled)
