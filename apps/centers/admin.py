"""
apps/centers/admin.py
──────────────────────
Django admin for centers app. This is the PRIMARY tool for Platform Admin.

PLATFORM ADMIN BOOTSTRAP (complete step-by-step):

  STEP 1 — Create the superuser (run once on server):
    python manage.py createsuperuser

  STEP 2 — Create Federal Medical Centres (FMCs) first:
    Admin → Federal Medical Centres (FMC) → Add
    Fill: name, code, state, zone, address, phone, email, status=Active
    Leave admin_user empty for now.

  STEP 3 — Create Primary Health Centres (PHCs):
    Admin → Primary Health Centres (PHC) → Add
    Fill: name, code, state, lga, address, phone, email, status=Active
    Set escalates_to = the FMC in the same state (CRITICAL — this is the routing link)

  STEP 4 — Create PHC Admin user accounts:
    Admin → Users → Add User
    Set: email, full_name, role=PHC Admin (hcc_admin), password
    Set is_email_verified = True (so they can log in immediately)
    Then: Admin → Primary Health Centres → [PHC] → set admin_user = this user

  STEP 5 — Create FMC Admin user accounts:
    Same as Step 4 but role=FMC Admin (fhc_admin)
    Then: Admin → Federal Medical Centres → [FMC] → set admin_user = this user

  AFTER SETUP:
    PHC Admin logs in to PHC portal → creates PHC staff via API
    FMC Admin logs in to FMC portal → creates FMC staff + clinicians via API
    Patients self-register via app or PHC staff registers them as walk-ins

CHANGE REQUEST WORKFLOW:
  Patient submits request → appears in Change Requests section here
  Admin updates status → patient automatically notified via Celery task
  For CHANGE_PHC: after resolving, also update the patient's
  OnboardingProfile.registered_hcc in the Onboarding Profiles section
"""
from django.contrib import admin
from django.utils import timezone

from .models import (
    HealthCareCenter, FederalHealthCenter,
    HCCStaffProfile, FHCStaffProfile, ClinicianProfile,
    PHCPatientRecord, PatientCase, ChangeRequest,
)


@admin.register(HealthCareCenter)
class HealthCareCenterAdmin(admin.ModelAdmin):
    """
    Primary Health Centre (PHC) management.

    The most important field here is escalates_to — it determines which FMC
    receives Severe/Very Severe escalations from patients at this PHC.
    Always pick an FMC in the same state. If not set, the system falls back
    to any active FMC in the same state as a safety net.
    """
    list_display    = (
        "name", "code", "state", "lga",
        "escalates_to", "status", "notify_on_severe",
        "admin_user", "created_at",
    )
    list_filter     = ("status", "state", "notify_on_severe")
    search_fields   = ("name", "code", "email", "state", "lga")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields   = ("admin_user",)

    fieldsets = (
        ("Facility Info", {
            "fields": ("name", "code", "address", "state", "lga", "phone", "email", "website", "status"),
        }),
        ("Escalation Routing", {
            "fields": ("escalates_to",),
            "description": (
                "IMPORTANT: Set this to the FMC in the same state as this PHC. "
                "This is the routing link — Severe/Very Severe patients from this PHC "
                "are escalated to this FMC. If not set, the system falls back to any "
                "active FMC in the same state."
            ),
        }),
        ("PHC Admin", {
            "fields": ("admin_user",),
            "description": (
                "Assign a User with role='hcc_admin' as the PHC administrator. "
                "Create the user first (Users → Add User, role=PHC Admin, "
                "is_email_verified=True), then come back here to assign them."
            ),
        }),
        ("Notification Settings", {
            "fields": ("notify_on_severe", "notify_on_very_severe"),
            "description": (
                "Controls whether this PHC receives escalation alert notifications "
                "when registered patients reach Severe or Very Severe risk levels."
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        """
        Filter escalates_to to show only active FMCs.
        Adds help text showing the PHC's current state for easy selection.
        """
        form = super().get_form(request, obj, **kwargs)
        if "escalates_to" in form.base_fields:
            qs = FederalHealthCenter.objects.filter(
                status=FederalHealthCenter.CenterStatus.ACTIVE
            ).order_by("state", "name")
            form.base_fields["escalates_to"].queryset = qs
            state_hint = obj.state if (obj and obj.state) else "(set state field first)"
            form.base_fields["escalates_to"].help_text = (
                f"Only active FMCs shown. This PHC is in state: {state_hint}. "
                f"Select an FMC in the same state for correct routing."
            )
        return form


@admin.register(FederalHealthCenter)
class FederalHealthCenterAdmin(admin.ModelAdmin):
    """
    Federal Medical Centre (FMC) management.

    FMCs receive Severe/Very Severe patient escalations from PHCs.
    notify_on_very_severe is always True and cannot be changed — FMCs always
    receive critical alerts by design.
    """
    list_display    = (
        "name", "code", "state", "zone",
        "status", "admin_user", "created_at",
    )
    list_filter     = ("status", "state", "zone")
    search_fields   = ("name", "code", "email", "state")
    readonly_fields = ("created_at", "updated_at", "notify_on_very_severe")
    raw_id_fields   = ("admin_user",)

    fieldsets = (
        ("Facility Info", {
            "fields": ("name", "code", "address", "state", "zone", "phone", "email", "status"),
        }),
        ("FMC Admin", {
            "fields": ("admin_user",),
            "description": (
                "Assign a User with role='fhc_admin' as the FMC administrator. "
                "Create the user first (Users → Add User, role=FMC Admin, "
                "is_email_verified=True), then come back here to assign them."
            ),
        }),
        ("Notification Settings", {
            "fields": ("notify_on_very_severe",),
            "description": "FMCs always receive Very Severe escalation alerts. This cannot be disabled.",
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(HCCStaffProfile)
class HCCStaffProfileAdmin(admin.ModelAdmin):
    """
    PHC Staff Profile — oversight view for Platform Admin.

    PHC staff accounts are normally created by PHC Admins via the API
    (POST /api/v1/centers/phc/staff/). This view is for admin oversight,
    troubleshooting, and edge-case manual management.
    """
    list_display    = ("user", "hcc", "staff_role", "employee_id", "is_active", "created_at")
    list_filter     = ("staff_role", "is_active", "hcc__state")
    search_fields   = ("user__email", "user__full_name", "employee_id", "hcc__name")
    raw_id_fields   = ("user", "hcc")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FHCStaffProfile)
class FHCStaffProfileAdmin(admin.ModelAdmin):
    """
    FMC Staff Profile — oversight view for Platform Admin.

    FMC staff accounts are normally created by FMC Admins via the API
    (POST /api/v1/centers/fmc/staff/). This view is for oversight and troubleshooting.
    """
    list_display    = ("user", "fhc", "staff_role", "employee_id", "is_active", "created_at")
    list_filter     = ("staff_role", "is_active", "fhc__state")
    search_fields   = ("user__email", "user__full_name", "employee_id", "fhc__name")
    raw_id_fields   = ("user", "fhc")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ClinicianProfile)
class ClinicianProfileAdmin(admin.ModelAdmin):
    """
    Clinician Profile — oversight view for Platform Admin.

    Clinician accounts are normally created and verified by FMC Admins via the API.
    The verify/unverify bulk actions here are admin overrides for edge cases.
    """
    list_display    = ("user", "fhc", "specialization", "license_number", "is_verified", "created_at")
    list_filter     = ("specialization", "is_verified", "fhc__state")
    search_fields   = ("user__email", "user__full_name", "license_number", "fhc__name")
    raw_id_fields   = ("user", "fhc")
    readonly_fields = ("created_at", "updated_at", "verified_at")
    actions         = ["verify_clinicians", "unverify_clinicians"]

    @admin.action(description="Mark selected clinicians as verified")
    def verify_clinicians(self, request, queryset):
        count = queryset.filter(is_verified=False).update(
            is_verified=True,
            verified_at=timezone.now(),
        )
        self.message_user(request, f"{count} clinician(s) verified.")

    @admin.action(description="Revoke verification for selected clinicians")
    def unverify_clinicians(self, request, queryset):
        count = queryset.filter(is_verified=True).update(
            is_verified=False,
            verified_at=None,
        )
        self.message_user(request, f"{count} clinician(s) unverified.")


@admin.register(PHCPatientRecord)
class PHCPatientRecordAdmin(admin.ModelAdmin):
    """
    PHC Patient Record — Platform Admin oversight of Mild/Moderate patient tracking.

    These records are created automatically by the escalation pipeline
    when a patient's score reaches Mild or Moderate, and they have a registered PHC.
    Also created when PHC staff registers a walk-in patient.

    PHC staff manage these via the PHC portal (screens PHC2/PHC3).
    This view is for Platform Admin oversight and troubleshooting only.
    """
    list_display    = (
        "patient", "hcc", "condition", "severity",
        "status", "opening_score", "latest_score", "opened_at",
    )
    list_filter     = ("status", "condition", "severity", "hcc__state")
    search_fields   = ("patient__email", "patient__full_name", "hcc__name")
    raw_id_fields   = ("patient", "hcc", "escalated_to_case")
    readonly_fields = ("opened_at", "closed_at", "opening_score")
    date_hierarchy  = "opened_at"

    fieldsets = (
        ("Patient & PHC", {
            "fields": ("patient", "hcc", "condition", "severity", "status"),
        }),
        ("Scores", {
            "fields": ("opening_score", "latest_score"),
        }),
        ("PHC Notes & Follow-up", {
            "fields": ("notes", "last_advice_at", "next_followup"),
        }),
        ("Escalation", {
            "fields": ("escalated_to_case",),
            "description": "Linked FMC PatientCase if this record was escalated.",
        }),
        ("Timestamps", {
            "fields": ("opened_at", "closed_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(PatientCase)
class PatientCaseAdmin(admin.ModelAdmin):
    """
    FMC Patient Case — Platform Admin oversight of Severe/Very Severe cases.

    PatientCases are created automatically by the escalation pipeline
    or when PHC staff escalate a patient. FMC staff manage them via the
    FMC portal (screens FMC2/FMC3/FMC4/FMC8).

    This view is for oversight and admin override only.
    Use the mark_discharged action to close stuck cases.
    """
    list_display    = (
        "patient", "fhc", "clinician", "condition",
        "severity", "status", "opening_score", "opened_at",
    )
    list_filter     = ("status", "condition", "severity", "fhc__state")
    search_fields   = ("patient__email", "patient__full_name", "fhc__name")
    raw_id_fields   = ("patient", "fhc", "clinician")
    readonly_fields = ("opened_at", "assigned_at", "closed_at", "opening_score")
    date_hierarchy  = "opened_at"
    actions         = ["mark_discharged"]

    fieldsets = (
        ("Patient & FMC", {
            "fields": ("patient", "fhc", "clinician", "condition", "severity", "status"),
        }),
        ("Scores", {
            "fields": ("opening_score", "closing_score"),
        }),
        ("Notes", {
            "fields": ("fmc_notes",),
        }),
        ("Timestamps", {
            "fields": ("opened_at", "assigned_at", "closed_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.action(description="Mark selected cases as discharged (admin override)")
    def mark_discharged(self, request, queryset):
        """
        Admin override to force-close stuck cases.
        Only closes OPEN, ASSIGNED, or UNDER_TREATMENT cases.
        """
        count = queryset.filter(
            status__in=[
                PatientCase.CaseStatus.OPEN,
                PatientCase.CaseStatus.ASSIGNED,
                PatientCase.CaseStatus.UNDER_TREATMENT,
            ]
        ).update(
            status=PatientCase.CaseStatus.DISCHARGED,
            closed_at=timezone.now(),
        )
        self.message_user(request, f"{count} case(s) marked as discharged.")


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    """
    Patient Change Request management.

    WORKFLOW:
      1. Patient submits a request (status = PENDING)
         It appears here automatically.

      2. Admin reviews the request:
         Change status to REVIEWED → patient is notified automatically.

      3. Admin resolves or rejects:
         Change status to RESOLVED or REJECTED → patient notified automatically.
         Notification is sent via the notify_change_request_status_update Celery task.

      4. For CHANGE_PHC requests that are RESOLVED:
         Go to Onboarding Profiles → find the patient → update registered_hcc
         to the requested PHC. This applies the actual PHC change.

    STATUS FLOW: PENDING → REVIEWED → RESOLVED or REJECTED
    """
    list_display    = ("patient", "request_type", "status", "requested_hcc", "created_at")
    list_filter     = ("request_type", "status")
    search_fields   = ("patient__email", "patient__full_name")
    raw_id_fields   = ("patient", "requested_hcc")
    readonly_fields = ("created_at", "resolved_at")

    fieldsets = (
        ("Request", {
            "fields": ("patient", "request_type", "description", "requested_hcc"),
        }),
        ("Review", {
            "fields": ("status", "admin_notes"),
            "description": (
                "Change the status to update the patient. "
                "An in-app notification is sent automatically on REVIEWED, RESOLVED, and REJECTED. "
                "Add admin_notes to explain a REJECTED decision — they are shown to the patient."
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "resolved_at"),
            "classes": ("collapse",),
        }),
    )

    def save_model(self, request, obj, form, change):
        """Auto-set resolved_at and trigger patient notification on status change."""
        is_status_change = change and "status" in form.changed_data

        if obj.status in (
            ChangeRequest.RequestStatus.RESOLVED,
            ChangeRequest.RequestStatus.REJECTED,
        ):
            if not obj.resolved_at:
                obj.resolved_at = timezone.now()

        super().save_model(request, obj, form, change)

        if is_status_change and obj.status != ChangeRequest.RequestStatus.PENDING:
            try:
                from apps.notifications.tasks import notify_change_request_status_update
                from core.utils.celery_helpers import run_task
                run_task(notify_change_request_status_update, str(obj.id))
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    "Failed to dispatch change request notification: %s", e
                )