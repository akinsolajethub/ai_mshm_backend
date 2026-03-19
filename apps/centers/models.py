"""
apps/centers/models.py
───────────────────────
Models for PHC, FMC, staff profiles, patient records, cases, and change requests.

TWO LEVELS OF PATIENT TRACKING
────────────────────────────────
PHCPatientRecord (mild/moderate level):
  - Created when a patient's score hits Mild or Moderate
  - PHC staff monitor, send advice, book follow-ups
  - No clinician assigned — PHC has health workers only
  - Can be escalated → creates a PatientCase at FMC
  - Does NOT block patient from changing their PHC
  - Status: NEW → UNDER_REVIEW → ACTION_TAKEN → ESCALATED / DISCHARGED

PatientCase (severe/very severe level):
  - Created when score hits Severe or Very Severe
  - FMC staff assign a clinician to the case
  - Clinician writes treatment plans, prescriptions
  - ASSIGNED/UNDER_TREATMENT status blocks patient from changing PHC
  - Status: OPEN → ASSIGNED → UNDER_TREATMENT → DISCHARGED
  - On discharge: PHC is notified, PHCPatientRecord updated

ESCALATION CHAIN
─────────────────
  Patient → registered_hcc (PHC) → PHC.escalates_to (FMC)
  Mild/Moderate  → PHCPatientRecord created at PHC
  Severe         → PatientCase created at FMC
  PHC escalates  → PatientCase created at FMC from PHCPatientRecord
  FMC discharges → PHCPatientRecord status updated, PHC notified

PHC→FMC LINK (escalates_to)
────────────────────────────
  Set by Platform Admin during system setup.
  PHC Admin and FMC Admin cannot change this link.
  If null: system falls back to any active FMC in same state.
"""
import uuid
from django.db import models
from django.conf import settings


# ── Risk severity scale ───────────────────────────────────────────────────────

class RiskSeverity(models.TextChoices):
    """
    Standard four-tier severity scale for all AI-MSHM prediction outputs.
    Mild/Moderate → PHC level. Severe/Very Severe → FMC level.
    """
    MILD        = "mild",        "Mild"
    MODERATE    = "moderate",    "Moderate"
    SEVERE      = "severe",      "Severe"
    VERY_SEVERE = "very_severe", "Very Severe"


# ── Primary Health Centre (PHC / HCC) ────────────────────────────────────────

class HealthCareCenter(models.Model):
    """
    A Primary Health Centre (PHC) — community-level facility.
    Codebase abbreviation: HCC. Frontend/docs label: PHC.

    escalates_to: set by Platform Admin. Determines which FMC receives
    Severe/Very Severe escalations from this PHC's patients.
    If null, system falls back to any active FMC in same state.
    """

    class CenterStatus(models.TextChoices):
        ACTIVE   = "active",   "Active"
        INACTIVE = "inactive", "Inactive"
        PENDING  = "pending",  "Pending Verification"

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(
        max_length=20, unique=True,
        help_text="Short identifier e.g. PHC-LGS-001",
    )
    address = models.TextField(blank=True)
    state   = models.CharField(
        max_length=100, blank=True, db_index=True,
        help_text="Nigerian state. Used for fallback FMC matching.",
    )
    lga = models.CharField(
        max_length=100, blank=True, verbose_name="LGA",
        help_text="Local Government Area. Used for proximity filtering.",
    )
    phone   = models.CharField(max_length=20, blank=True)
    email   = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    status  = models.CharField(
        max_length=15, choices=CenterStatus.choices, default=CenterStatus.ACTIVE,
    )

    escalates_to = models.ForeignKey(
        "FederalHealthCenter",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="referring_phcs",
        help_text=(
            "The FMC this PHC escalates Severe/Very Severe patients to. "
            "Set by Platform Admin only. Choose an FMC in the same state. "
            "If not set, system falls back to any active FMC in same state."
        ),
    )

    notify_on_severe = models.BooleanField(
        default=True,
        help_text="Notify PHC admin/staff when a registered patient reaches Severe risk.",
    )
    notify_on_very_severe = models.BooleanField(
        default=True,
        help_text="Notify PHC admin/staff when a registered patient reaches Very Severe risk.",
    )

    admin_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="managed_hcc",
        limit_choices_to={"role": "hcc_admin"},
        help_text="The PHC Admin account that manages this facility.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Primary Health Centre (PHC)"
        verbose_name_plural = "Primary Health Centres (PHC)"
        ordering            = ["state", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def get_active_staff(self):
        return self.staff_profiles.filter(user__is_active=True).select_related("user")

    def get_escalation_fmc(self):
        """
        Returns the FMC this PHC escalates to.
        Priority: escalates_to (explicit) → any active FMC in same state → None.
        """
        if self.escalates_to_id:
            fmc = self.escalates_to
            if fmc and fmc.status == FederalHealthCenter.CenterStatus.ACTIVE:
                return fmc

        if self.state:
            fallback = FederalHealthCenter.objects.filter(
                status=FederalHealthCenter.CenterStatus.ACTIVE,
                state__iexact=self.state,
            ).first()
            if fallback:
                return fallback

        return None


# ── Federal Health Centre (FMC / FHC) ────────────────────────────────────────

class FederalHealthCenter(models.Model):
    """
    A Federal Medical Centre (FMC) — hospital-level facility.
    Codebase abbreviation: FHC. Frontend/docs label: FMC.

    Receives Severe/Very Severe escalations from PHCs.
    notify_on_very_severe is always True — non-configurable.
    """

    class CenterStatus(models.TextChoices):
        ACTIVE   = "active",   "Active"
        INACTIVE = "inactive", "Inactive"
        PENDING  = "pending",  "Pending Verification"

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text="e.g. FMC-ABJ-001")
    address  = models.TextField(blank=True)
    state    = models.CharField(max_length=100, blank=True, db_index=True)
    zone     = models.CharField(max_length=100, blank=True, help_text="Geopolitical zone")
    phone    = models.CharField(max_length=20, blank=True)
    email    = models.EmailField(blank=True)
    status   = models.CharField(
        max_length=15, choices=CenterStatus.choices, default=CenterStatus.ACTIVE,
    )
    notify_on_very_severe = models.BooleanField(
        default=True, editable=False,
        help_text="Always True — FMC always receives Very Severe alerts.",
    )
    admin_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="managed_fhc",
        limit_choices_to={"role": "fhc_admin"},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Federal Medical Centre (FMC)"
        verbose_name_plural = "Federal Medical Centres (FMC)"
        ordering            = ["state", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def get_active_staff(self):
        return self.staff_profiles.filter(user__is_active=True).select_related("user")

    def get_active_clinicians(self):
        return self.clinicians.filter(
            user__is_active=True, is_verified=True
        ).select_related("user")


# ── PHC Staff Profile ─────────────────────────────────────────────────────────

class HCCStaffProfile(models.Model):
    """
    Extended profile for role='hcc_staff' (PHC health workers).
    Created by HCC Admin via POST /api/v1/centers/phc/staff/
    """

    class StaffRole(models.TextChoices):
        NURSE                    = "nurse",        "Nurse"
        COMMUNITY_HEALTH_OFFICER = "cho",          "Community Health Officer"
        HEALTH_ASSISTANT         = "assistant",    "Health Assistant"
        RECEPTIONIST             = "receptionist", "Receptionist"
        OTHER                    = "other",        "Other"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hcc_staff_profile",
    )
    hcc         = models.ForeignKey(
        HealthCareCenter, on_delete=models.CASCADE, related_name="staff_profiles",
    )
    staff_role  = models.CharField(max_length=20, choices=StaffRole.choices, default=StaffRole.OTHER)
    employee_id = models.CharField(max_length=50, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PHC Staff Profile"

    def __str__(self):
        return f"{self.user.full_name} — {self.hcc.name} ({self.get_staff_role_display()})"


# ── FMC Staff Profile ─────────────────────────────────────────────────────────

class FHCStaffProfile(models.Model):
    """
    Extended profile for role='fhc_staff' (FMC case coordinators).
    Created by FHC Admin via POST /api/v1/centers/fmc/staff/
    """

    class StaffRole(models.TextChoices):
        CASE_COORDINATOR = "coordinator", "Case Coordinator"
        TRIAGE_OFFICER   = "triage",      "Triage Officer"
        RECORDS_OFFICER  = "records",     "Records Officer"
        OTHER            = "other",       "Other"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fhc_staff_profile",
    )
    fhc         = models.ForeignKey(
        FederalHealthCenter, on_delete=models.CASCADE, related_name="staff_profiles",
    )
    staff_role  = models.CharField(max_length=20, choices=StaffRole.choices, default=StaffRole.OTHER)
    employee_id = models.CharField(max_length=50, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "FMC Staff Profile"

    def __str__(self):
        return f"{self.user.full_name} — {self.fhc.name} ({self.get_staff_role_display()})"


# ── Clinician Profile ─────────────────────────────────────────────────────────

class ClinicianProfile(models.Model):
    """
    Extended profile for role='clinician' (licensed doctors).
    FHC-affiliated only. Must be verified before accessing patient data.
    Created by FHC Admin via POST /api/v1/centers/fmc/clinicians/
    """

    class Specialization(models.TextChoices):
        GENERAL_PRACTICE    = "general_practice",    "General Practice"
        OBSTETRICS_GYNAE    = "obstetrics_gynae",     "Obstetrics & Gynaecology"
        ENDOCRINOLOGY       = "endocrinology",        "Endocrinology"
        CARDIOLOGY          = "cardiology",           "Cardiology"
        INTERNAL_MEDICINE   = "internal_medicine",    "Internal Medicine"
        REPRODUCTIVE_HEALTH = "reproductive_health",  "Reproductive Health"
        MIDWIFERY           = "midwifery",            "Midwifery"
        NURSING             = "nursing",              "Nursing"
        OTHER               = "other",                "Other"

    id                  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user                = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clinician_profile",
    )
    fhc                 = models.ForeignKey(
        FederalHealthCenter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="clinicians",
    )
    specialization      = models.CharField(
        max_length=30, choices=Specialization.choices, default=Specialization.GENERAL_PRACTICE,
    )
    license_number      = models.CharField(max_length=50, blank=True)
    years_of_experience = models.PositiveSmallIntegerField(default=0)
    bio                 = models.TextField(blank=True)
    is_verified         = models.BooleanField(default=False)
    verified_at         = models.DateTimeField(null=True, blank=True)
    profile_photo       = models.ImageField(upload_to="clinicians/", null=True, blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Clinician Profile"

    def __str__(self):
        return f"Dr. {self.user.full_name} — {self.get_specialization_display()}"

    @property
    def center_name(self) -> str:
        return self.fhc.name if self.fhc else "Unaffiliated"


# ── PHC Patient Record ────────────────────────────────────────────────────────

class PHCPatientRecord(models.Model):
    """
    Tracks a patient's Mild/Moderate risk episode at PHC level.

    CREATED:
      Automatically by signals.py when Mild/Moderate severity is detected
      and the patient has a registered PHC.
      Also created when PHC staff registers a walk-in patient.

    LIFECYCLE:
      NEW         → PHC notified, patient appears in PHC2 queue
      UNDER_REVIEW → PHC staff opened the record and is reviewing
      ACTION_TAKEN → PHC staff sent advice or booked a follow-up
      ESCALATED    → PHC staff escalated to FMC (PatientCase created at FMC)
      DISCHARGED   → PHC staff discharged (patient resolved at PHC level)
                     Also set when FMC discharges back to PHC monitoring

    KEY DIFFERENCES FROM PatientCase:
      - No clinician field (PHC has no doctors)
      - No ASSIGNED or UNDER_TREATMENT status
      - Does NOT block patient from changing their PHC
      - Can be escalated → creates a PatientCase at the FMC
      - Multiple records can exist for the same patient over time

    ESCALATION:
      PHC staff click "Escalate to FMC" on screen PHC6.
      Code creates a PatientCase at PHC.get_escalation_fmc().
      PHCPatientRecord status → ESCALATED.
      escalated_to_case FK set so the two records are linked.

    FMC DISCHARGE BACK:
      When FMC discharges a PatientCase, the linked PHCPatientRecord
      (if any) is updated to DISCHARGED and PHC is notified to resume
      monitoring.
    """

    class RecordStatus(models.TextChoices):
        NEW          = "new",          "New — Awaiting Review"
        UNDER_REVIEW = "under_review", "Under Review"
        ACTION_TAKEN = "action_taken", "Action Taken"
        ESCALATED    = "escalated",    "Escalated to FMC"
        DISCHARGED   = "discharged",   "Discharged"

    class Condition(models.TextChoices):
        PCOS           = "pcos",           "PCOS"
        MATERNAL       = "maternal",       "Maternal Health"
        CARDIOVASCULAR = "cardiovascular", "Cardiovascular"

    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="phc_records",
        limit_choices_to={"role": "patient"},
    )
    hcc       = models.ForeignKey(
        HealthCareCenter,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="patient_records",
        help_text="The PHC managing this patient at the time this record was created.",
    )
    condition  = models.CharField(max_length=20, choices=Condition.choices)
    severity   = models.CharField(
        max_length=20, choices=RiskSeverity.choices,
        help_text="Should only be mild or moderate at PHC level.",
    )
    status     = models.CharField(
        max_length=20, choices=RecordStatus.choices,
        default=RecordStatus.NEW, db_index=True,
    )
    opening_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Risk score (0–100) when this record was created.",
    )
    latest_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Most recent risk score — updated each time ML runs.",
    )

    # PHC staff notes — lifestyle advice, observations
    notes          = models.TextField(blank=True)
    last_advice_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp of last lifestyle advice sent to patient.",
    )
    next_followup  = models.DateField(
        null=True, blank=True,
        help_text="Date PHC staff scheduled a follow-up for this patient.",
    )

    # Link to FMC case if escalated
    escalated_to_case = models.OneToOneField(
        "PatientCase",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="phc_record",
        help_text="The FMC PatientCase created when this record was escalated.",
    )

    opened_at  = models.DateTimeField(auto_now_add=True)
    closed_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = "PHC Patient Record"
        verbose_name_plural = "PHC Patient Records"
        ordering            = ["-opened_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["hcc", "status"]),
        ]

    def __str__(self):
        return f"PHCRecord({self.patient.email} | {self.condition} | {self.status})"

    def is_open(self) -> bool:
        return self.status in (
            self.RecordStatus.NEW,
            self.RecordStatus.UNDER_REVIEW,
            self.RecordStatus.ACTION_TAKEN,
        )

    def close(self, status: str):
        from django.utils import timezone
        self.status    = status
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at"])


# ── FMC Patient Case ──────────────────────────────────────────────────────────

class PatientCase(models.Model):
    """
    Tracks a single FMC clinical event for a patient.

    CREATED:
      Automatically by signals.py when Severe/Very Severe is detected.
      Also created when PHC staff manually escalate a PHCPatientRecord.

    LIFECYCLE:
      OPEN            → FMC notified, case in queue, no clinician yet
      ASSIGNED        → FMC staff assigned a clinician
      UNDER_TREATMENT → Clinician actively treating
      DISCHARGED      → Case closed by FMC staff or clinician

    PHC CHANGE BLOCK:
      ASSIGNED and UNDER_TREATMENT cases block the patient from changing
      their PHC (enforced in OnboardingStep7View).
      OPEN cases do not block — signals.py reroutes automatically.

    DISCHARGE:
      FMC staff/clinician discharges via POST /fmc/cases/<uuid>/discharge/
      Patient is notified.
      Linked PHCPatientRecord (if any) is updated to DISCHARGED.
      PHC is notified to resume monitoring.
    """

    class CaseStatus(models.TextChoices):
        OPEN            = "open",            "Open — Awaiting Assignment"
        ASSIGNED        = "assigned",        "Assigned to Clinician"
        UNDER_TREATMENT = "under_treatment", "Under Treatment"
        DISCHARGED      = "discharged",      "Discharged"

    class Condition(models.TextChoices):
        PCOS           = "pcos",           "PCOS"
        MATERNAL       = "maternal",       "Maternal Health"
        CARDIOVASCULAR = "cardiovascular", "Cardiovascular"

    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_cases",
        limit_choices_to={"role": "patient"},
    )
    fhc       = models.ForeignKey(
        FederalHealthCenter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cases",
        help_text="FMC handling this case. Set from PHC.escalates_to at creation.",
    )
    clinician = models.ForeignKey(
        ClinicianProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_cases",
        help_text="Assigned by FMC staff. Null until assignment.",
    )
    condition     = models.CharField(max_length=20, choices=Condition.choices)
    severity      = models.CharField(max_length=20, choices=RiskSeverity.choices)
    status        = models.CharField(
        max_length=20, choices=CaseStatus.choices,
        default=CaseStatus.OPEN, db_index=True,
    )
    opening_score = models.PositiveSmallIntegerField(null=True, blank=True)
    closing_score = models.PositiveSmallIntegerField(null=True, blank=True)
    fmc_notes     = models.TextField(blank=True)
    opened_at     = models.DateTimeField(auto_now_add=True)
    assigned_at   = models.DateTimeField(null=True, blank=True)
    closed_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = "FMC Patient Case"
        verbose_name_plural = "FMC Patient Cases"
        ordering            = ["-opened_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["fhc", "status"]),
        ]

    def __str__(self):
        return f"Case({self.patient.email} | {self.condition} | {self.status})"

    def is_open(self) -> bool:
        return self.status in (
            self.CaseStatus.OPEN,
            self.CaseStatus.ASSIGNED,
            self.CaseStatus.UNDER_TREATMENT,
        )

    def assign_clinician(self, clinician: "ClinicianProfile"):
        from django.utils import timezone
        self.clinician   = clinician
        self.status      = self.CaseStatus.ASSIGNED
        self.assigned_at = timezone.now()
        self.save(update_fields=["clinician", "status", "assigned_at"])

    def close(self, status: str, closing_score: int = None):
        from django.utils import timezone
        self.status        = status
        self.closing_score = closing_score
        self.closed_at     = timezone.now()
        self.save(update_fields=["status", "closing_score", "closed_at"])


# ── Change Request ────────────────────────────────────────────────────────────

class ChangeRequest(models.Model):
    """
    Patient-submitted request to change their home PHC or report an issue.
    Reviewed by Platform Admin via Django /admin/.
    Patient notified when status changes via notify_change_request_status_update task.
    """

    class RequestType(models.TextChoices):
        CHANGE_PHC   = "change_phc",   "Change Home PHC"
        REPORT_ISSUE = "report_issue", "Report an Issue"
        OTHER        = "other",        "Other"

    class RequestStatus(models.TextChoices):
        PENDING  = "pending",  "Pending Review"
        REVIEWED = "reviewed", "Under Review"
        RESOLVED = "resolved", "Resolved"
        REJECTED = "rejected", "Rejected"

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient      = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="change_requests",
        limit_choices_to={"role": "patient"},
    )
    request_type = models.CharField(max_length=20, choices=RequestType.choices)
    status       = models.CharField(
        max_length=15, choices=RequestStatus.choices,
        default=RequestStatus.PENDING, db_index=True,
    )
    requested_hcc = models.ForeignKey(
        HealthCareCenter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="incoming_change_requests",
        help_text="The PHC the patient wants to switch to (CHANGE_PHC only).",
    )
    description  = models.TextField()
    admin_notes  = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    resolved_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = "Change Request"
        verbose_name_plural = "Change Requests"
        ordering            = ["-created_at"]

    def __str__(self):
        return f"ChangeRequest({self.patient.email} | {self.request_type} | {self.status})"