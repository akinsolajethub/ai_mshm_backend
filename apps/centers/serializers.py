"""
apps/centers/serializers.py
────────────────────────────
Serializers for PHC, FMC, staff profiles, clinicians, and change requests.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from .models import (
    HealthCareCenter,
    FederalHealthCenter,
    HCCStaffProfile,
    FHCStaffProfile,
    ClinicianProfile,
    PHCPatientRecord,
    PatientCase,
    ConsultationNote,
    TreatmentPlan,
    Prescription,
    ChangeRequest,
)

User = get_user_model()


# ── Public dropdowns ──────────────────────────────────────────────────────────


class HealthCareCenterPublicSerializer(serializers.ModelSerializer):
    """Minimal PHC info for onboarding step 7 and registration dropdowns."""

    class Meta:
        model = HealthCareCenter
        fields = ["id", "name", "code", "state", "lga"]


class FederalHealthCenterPublicSerializer(serializers.ModelSerializer):
    """Minimal FMC info for dropdowns."""

    class Meta:
        model = FederalHealthCenter
        fields = ["id", "name", "code", "state", "zone"]


# ── PHC full detail ───────────────────────────────────────────────────────────


class HealthCareCenterSerializer(serializers.ModelSerializer):
    """
    Full PHC record for HCC Admin and Platform Admin.
    escalates_to_name: read-only name of the linked FMC.
    Platform Admin can set escalates_to. HCC Admin cannot.
    """

    staff_count = serializers.SerializerMethodField()
    escalates_to_name = serializers.CharField(
        source="escalates_to.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = HealthCareCenter
        fields = [
            "id",
            "name",
            "code",
            "address",
            "state",
            "lga",
            "phone",
            "email",
            "website",
            "status",
            "escalates_to",
            "escalates_to_name",
            "notify_on_severe",
            "notify_on_very_severe",
            "staff_count",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "staff_count", "escalates_to_name"]

    @extend_schema_field(serializers.IntegerField())
    def get_staff_count(self, obj):
        return obj.staff_profiles.filter(user__is_active=True).count()


# ── FMC full detail ───────────────────────────────────────────────────────────


class FederalHealthCenterSerializer(serializers.ModelSerializer):
    """Full FMC record for FHC Admin and Platform Admin."""

    staff_count = serializers.SerializerMethodField()
    clinician_count = serializers.SerializerMethodField()

    class Meta:
        model = FederalHealthCenter
        fields = [
            "id",
            "name",
            "code",
            "address",
            "state",
            "zone",
            "phone",
            "email",
            "status",
            "notify_on_very_severe",
            "staff_count",
            "clinician_count",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "notify_on_very_severe",
            "staff_count",
            "clinician_count",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_staff_count(self, obj):
        return obj.staff_profiles.filter(user__is_active=True).count()

    @extend_schema_field(serializers.IntegerField())
    def get_clinician_count(self, obj):
        return obj.clinicians.filter(user__is_active=True, is_verified=True).count()


# ── PHC Staff ─────────────────────────────────────────────────────────────────


class HCCStaffProfileSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    hcc_name = serializers.CharField(source="hcc.name", read_only=True)
    hcc_code = serializers.CharField(source="hcc.code", read_only=True)
    user_last_login = serializers.DateTimeField(
        source="user.last_login", read_only=True, allow_null=True
    )

    class Meta:
        model = HCCStaffProfile
        fields = [
            "id",
            "user_email",
            "user_full_name",
            "hcc_name",
            "hcc_code",
            "staff_role",
            "employee_id",
            "is_active",
            "created_at",
            "updated_at",
            "user_last_login",
        ]
        read_only_fields = [
            "id",
            "user_email",
            "user_full_name",
            "hcc_name",
            "hcc_code",
            "created_at",
            "updated_at",
            "user_last_login",
        ]


class CreateHCCStaffSerializer(serializers.Serializer):
    """Used by HCC Admin to create PHC staff accounts."""

    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    staff_role = serializers.ChoiceField(choices=HCCStaffProfile.StaffRole.choices)
    employee_id = serializers.CharField(max_length=50, required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class HCCStaffCreatedSerializer(serializers.Serializer):
    """
    Response serializer for staff creation.
    Includes temp_password so admin can share credentials with the new staff.
    """

    id = serializers.UUIDField()
    user_email = serializers.EmailField()
    user_full_name = serializers.CharField()
    hcc_name = serializers.CharField()
    hcc_code = serializers.CharField()
    staff_role = serializers.CharField()
    employee_id = serializers.CharField(allow_blank=True, allow_null=True)
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    temp_password = serializers.CharField(help_text="Share this with the new staff member")


# ── FMC Staff ─────────────────────────────────────────────────────────────────


class FHCStaffProfileSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    fhc_name = serializers.CharField(source="fhc.name", read_only=True)
    fhc_code = serializers.CharField(source="fhc.code", read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)

    class Meta:
        model = FHCStaffProfile
        fields = [
            "id",
            "user_email",
            "user_full_name",
            "fhc_name",
            "fhc_code",
            "staff_role",
            "employee_id",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user_email",
            "user_full_name",
            "fhc_name",
            "fhc_code",
            "staff_role",
            "employee_id",
            "is_active",
            "created_at",
            "updated_at",
        ]


class CreateFHCStaffSerializer(serializers.Serializer):
    """Used by FHC Admin to create FMC staff accounts."""

    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    staff_role = serializers.ChoiceField(choices=FHCStaffProfile.StaffRole.choices)
    employee_id = serializers.CharField(max_length=50, required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


# ── Clinician ─────────────────────────────────────────────────────────────────


class ClinicianProfileSerializer(serializers.ModelSerializer):
    fhc_name = serializers.CharField(source="fhc.name", read_only=True)
    fhc_code = serializers.CharField(source="fhc.code", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    profile_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = ClinicianProfile
        fields = [
            "id",
            "user_email",
            "user_full_name",
            "fhc",
            "fhc_name",
            "fhc_code",
            "specialization",
            "downstream_expertise",
            "onboarded",
            "onboarded_at",
            "license_number",
            "years_of_experience",
            "bio",
            "is_verified",
            "verified_at",
            "profile_photo_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_verified",
            "verified_at",
            "onboarded_at",
            "user_email",
            "user_full_name",
            "fhc_name",
            "fhc_code",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_profile_photo_url(self, obj):
        request = self.context.get("request")
        if obj.profile_photo and request:
            return request.build_absolute_uri(obj.profile_photo.url)
        return None


class UpdateClinicianProfileSerializer(serializers.ModelSerializer):
    """Clinician updates own profile. Cannot change FMC affiliation."""

    class Meta:
        model = ClinicianProfile
        fields = ["specialization", "license_number", "years_of_experience", "bio", "profile_photo"]


from .constants import DOWNSTREAM_DISEASES


class ClinicianOnboardingSerializer(serializers.Serializer):
    """Clinician onboarding - sets specialization and downstream expertise."""

    specialization = serializers.ChoiceField(
        choices=ClinicianProfile.Specialization.choices,
    )
    downstream_expertise = serializers.ListField(
        child=serializers.ChoiceField(choices=list(DOWNSTREAM_DISEASES.keys())),
        min_length=1,
        max_length=10,
    )
    license_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    years_of_experience = serializers.IntegerField(min_value=0, required=False, default=0)
    bio = serializers.CharField(required=False, allow_blank=True)


class CreateClinicianSerializer(serializers.Serializer):
    """Used by FHC Admin to create clinician accounts."""

    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    specialization = serializers.ChoiceField(
        choices=ClinicianProfile.Specialization.choices,
        default=ClinicianProfile.Specialization.GENERAL_PRACTICE,
    )
    license_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    years_of_experience = serializers.IntegerField(min_value=0, required=False, default=0)
    bio = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


# ── PHC Walk-In Registration ──────────────────────────────────────────────────


class PHCWalkInSerializer(serializers.Serializer):
    """
    Used by PHC staff to register a walk-in patient (screen PHC4).

    The patient's registered_hcc is automatically set to the staff member's
    PHC — no need to specify it here.

    Fields:
      full_name  : patient's full name (required)
      email      : patient's email (required, must be unique)
      age        : patient's age (optional)
      condition  : which condition triggered the visit (required)
      severity   : mild | moderate (required)
      notes      : initial PHC staff observations (optional)
    """

    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    age = serializers.IntegerField(min_value=10, max_value=120, required=False, allow_null=True)
    condition = serializers.ChoiceField(choices=PHCPatientRecord.Condition.choices)
    severity = serializers.ChoiceField(
        choices=[("mild", "Mild"), ("moderate", "Moderate")],
        default="moderate",
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "A patient with this email already exists. "
                "If this is an existing patient, ask them to log in instead."
            )
        return value


class PHCWalkInComprehensiveSerializer(serializers.Serializer):
    """
    Comprehensive walk-in registration with all health data.
    Used by PHC staff to register a patient with full assessment data.
    """

    first_name = serializers.CharField(max_length=100, allow_blank=False)
    last_name = serializers.CharField(max_length=100, allow_blank=False)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, allow_null=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=["female", "intersex", "prefer_not_to_say"], default="female", required=False
    )
    ethnicity = serializers.ChoiceField(
        choices=[
            "african",
            "asian",
            "caucasian",
            "hispanic",
            "middle_eastern",
            "other",
            "prefer_not_to_say",
        ],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    family_history = serializers.ListField(
        child=serializers.CharField(), required=False, default=list, allow_null=True
    )

    height_cm = serializers.FloatField(required=False, allow_null=True)
    weight_kg = serializers.FloatField(required=False, allow_null=True)
    waist_cm = serializers.FloatField(required=False, allow_null=True)
    hip_cm = serializers.FloatField(required=False, allow_null=True)
    acanthosis_nigricans = serializers.ChoiceField(
        choices=["yes", "no", "not_sure"], required=False, allow_blank=True, allow_null=True
    )
    skin_tags = serializers.ChoiceField(
        choices=["yes", "no"], required=False, allow_blank=True, allow_null=True
    )
    scalp_hair_thinning = serializers.ChoiceField(
        choices=["yes", "no", "unsure"], required=False, allow_blank=True, allow_null=True
    )

    cycle_regularity = serializers.ChoiceField(
        choices=["regular", "irregular", "not_sure"],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    typical_cycle_length = serializers.IntegerField(required=False, allow_null=True)
    periods_per_year = serializers.IntegerField(required=False, allow_null=True)
    last_period_date = serializers.DateField(required=False, allow_null=True)
    bleeding_intensity = serializers.ChoiceField(
        choices=["spotting", "light", "medium", "heavy", "very_heavy"],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    acne_severity = serializers.ChoiceField(
        choices=["none", "mild", "moderate", "severe"],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    night_sweats = serializers.ChoiceField(
        choices=["none", "occasional", "frequent", "every_night"],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    breast_soreness = serializers.ChoiceField(
        choices=["none", "mild", "moderate", "severe"],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    muscle_weakness = serializers.ChoiceField(
        choices=["none", "mild", "moderate", "significant"],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    cramp_severity = serializers.IntegerField(
        min_value=0, max_value=10, required=False, allow_null=True
    )
    fatigue_level = serializers.ChoiceField(
        choices=["none", "mild", "moderate", "severe"],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    high_blood_pressure = serializers.ChoiceField(
        choices=["yes", "no", "not_sure"], required=False, allow_blank=True, allow_null=True
    )
    abdominal_weight = serializers.ChoiceField(
        choices=["no", "mild", "significant"], required=False, allow_blank=True, allow_null=True
    )
    hypoglycemia_symptoms = serializers.ListField(
        child=serializers.CharField(), required=False, default=list, allow_null=True
    )
    ethnicity = serializers.ChoiceField(
        choices=[
            "african",
            "asian",
            "caucasian",
            "hispanic",
            "middle_eastern",
            "other",
            "prefer_not_to_say",
        ],
        required=False,
        allow_blank=True,
    )
    family_history = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )

    height_cm = serializers.FloatField(required=False, allow_null=True)
    weight_kg = serializers.FloatField(required=False, allow_null=True)
    waist_cm = serializers.FloatField(required=False, allow_null=True)
    hip_cm = serializers.FloatField(required=False, allow_null=True)
    acanthosis_nigricans = serializers.ChoiceField(
        choices=["yes", "no", "not_sure"], required=False, allow_blank=True
    )
    skin_tags = serializers.ChoiceField(choices=["yes", "no"], required=False, allow_blank=True)
    scalp_hair_thinning = serializers.ChoiceField(
        choices=["yes", "no", "unsure"], required=False, allow_blank=True
    )

    cycle_regularity = serializers.ChoiceField(
        choices=["regular", "irregular", "not_sure"], required=False, allow_blank=True
    )
    typical_cycle_length = serializers.IntegerField(required=False, allow_null=True)
    periods_per_year = serializers.IntegerField(required=False, allow_null=True)
    last_period_date = serializers.DateField(required=False, allow_null=True)
    bleeding_intensity = serializers.ChoiceField(
        choices=["spotting", "light", "medium", "heavy", "very_heavy"],
        required=False,
        allow_blank=True,
    )
    acne_severity = serializers.ChoiceField(
        choices=["none", "mild", "moderate", "severe"], required=False, allow_blank=True
    )
    night_sweats = serializers.ChoiceField(
        choices=["none", "occasional", "frequent", "every_night"], required=False, allow_blank=True
    )
    breast_soreness = serializers.ChoiceField(
        choices=["none", "mild", "moderate", "severe"], required=False, allow_blank=True
    )
    muscle_weakness = serializers.ChoiceField(
        choices=["none", "mild", "moderate", "significant"], required=False, allow_blank=True
    )
    cramp_severity = serializers.IntegerField(
        min_value=0, max_value=10, required=False, allow_null=True
    )
    fatigue_level = serializers.ChoiceField(
        choices=["none", "mild", "moderate", "severe"], required=False, allow_blank=True
    )
    high_blood_pressure = serializers.ChoiceField(
        choices=["yes", "no", "not_sure"], required=False, allow_blank=True
    )
    abdominal_weight = serializers.ChoiceField(
        choices=["no", "mild", "significant"], required=False, allow_blank=True
    )
    hypoglycemia_symptoms = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )

    consent_given = serializers.BooleanField(default=False)

    def validate_email(self, value):
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A patient with this email already exists.")
        return value


# ── PHC Advice ─────────────────────────────────────────────────────────────────


class PHCAdviceSerializer(serializers.Serializer):
    """Request serializer for sending lifestyle advice to a patient."""

    condition = serializers.ChoiceField(choices=PHCPatientRecord.Condition.choices)
    message = serializers.CharField(max_length=2000)
    followup_date = serializers.DateField(required=False, allow_null=True)


class PHCAdviceResponseSerializer(serializers.Serializer):
    """Response serializer for advice sent to a patient."""

    id = serializers.UUIDField()
    queue_record_id = serializers.UUIDField()
    condition = serializers.CharField()
    message = serializers.CharField()
    followup_date = serializers.DateField(allow_null=True)
    sent_at = serializers.DateTimeField()
    sent_by_name = serializers.CharField()


class PHCAdviceHistorySerializer(serializers.Serializer):
    """Serializer for advice history."""

    results = PHCAdviceResponseSerializer(many=True)


# ── PHC Analytics ───────────────────────────────────────────────────────────────


class PHCAnalyticsSerializer(serializers.Serializer):
    """Serializer for PHC analytics data."""

    total_patients = serializers.IntegerField()
    active_minor_risk = serializers.IntegerField()
    escalated_this_period = serializers.IntegerField()
    avg_time_to_action_days = serializers.FloatField()
    risk_distribution = serializers.DictField()
    condition_breakdown = serializers.DictField()
    escalations_timeline = serializers.ListField()
    staff_actions = serializers.DictField()


# ── FMC Analytics ───────────────────────────────────────────────────────────────


class FMCAnalyticsSerializer(serializers.Serializer):
    """Serializer for FMC population analytics."""

    total_active_cases = serializers.IntegerField()
    critical_unassigned = serializers.IntegerField()
    critical_assigned = serializers.IntegerField()
    high_unassigned = serializers.IntegerField()
    high_assigned = serializers.IntegerField()
    avg_days_to_assignment = serializers.FloatField()
    cases_resolved_this_month = serializers.IntegerField()
    severity_distribution = serializers.DictField()
    condition_prevalence = serializers.DictField()
    referral_sources = serializers.ListField()
    time_to_assignment_histogram = serializers.ListField()
    outcomes_tracker = serializers.DictField()
    clinician_load = serializers.ListField()


class FMCAlertSerializer(serializers.Serializer):
    """Serializer for FMC alerts."""

    id = serializers.UUIDField()
    alert_type = serializers.CharField()
    severity = serializers.CharField()
    patient_id = serializers.UUIDField()
    patient_name = serializers.CharField()
    message = serializers.CharField()
    timestamp = serializers.DateTimeField()
    is_read = serializers.BooleanField()
    action_required = serializers.BooleanField()


class FMCAlertListSerializer(serializers.Serializer):
    """Serializer for alert list response."""

    pinned_alerts = FMCAlertSerializer(many=True)
    regular_alerts = FMCAlertSerializer(many=True)


class FMCDiagnosticsRequestSerializer(serializers.Serializer):
    """Serializer for diagnostics request."""

    patient_id = serializers.UUIDField()
    tests = serializers.ListField(child=serializers.CharField())
    urgency = serializers.ChoiceField(choices=["routine", "urgent"])
    custom_note = serializers.CharField(required=False, allow_blank=True)


class FMCDischargeSerializer(serializers.Serializer):
    """Serializer for case discharge."""

    condition_confirmed = serializers.ChoiceField(
        choices=[
            "pcos_confirmed",
            "hormonal_imbalance",
            "metabolic_syndrome",
            "multiple",
            "none_confirmed",
        ]
    )
    diagnostic_basis = serializers.ChoiceField(
        choices=["clinical_criteria", "lab_results", "imaging", "combined"]
    )
    treatment_summary = serializers.CharField(max_length=5000)
    follow_up_plan = serializers.ChoiceField(
        choices=["discharged_to_phc", "self_monitor", "specialist_followup", "tertiary_referral"]
    )
    closing_score = serializers.FloatField()
    discharge_letter = serializers.CharField(max_length=10000)


# ── Change Request ────────────────────────────────────────────────────────────


class ChangeRequestSerializer(serializers.ModelSerializer):
    """
    Patient submits and views change requests.
    Status, admin_notes, and resolved_at are read-only.
    """

    requested_hcc_detail = serializers.SerializerMethodField()

    class Meta:
        model = ChangeRequest
        fields = [
            "id",
            "request_type",
            "status",
            "requested_hcc",
            "requested_hcc_detail",
            "description",
            "admin_notes",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "admin_notes",
            "created_at",
            "resolved_at",
            "requested_hcc_detail",
        ]

    def get_requested_hcc_detail(self, obj):
        if not obj.requested_hcc:
            return None
        hcc = obj.requested_hcc
        return {"id": str(hcc.id), "name": hcc.name, "code": hcc.code, "state": hcc.state}

    def validate(self, attrs):
        if attrs.get("request_type") == ChangeRequest.RequestType.CHANGE_PHC and not attrs.get(
            "requested_hcc"
        ):
            raise serializers.ValidationError(
                {
                    "requested_hcc": "Select the PHC you want to switch to.",
                }
            )
        return attrs

    def create(self, validated_data):
        patient = self.context["request"].user
        return ChangeRequest.objects.create(patient=patient, **validated_data)


# ── FMC Consultation Notes & Treatment Plans ─────────────────────────────────────


class ConsultationNoteSerializer(serializers.ModelSerializer):
    clinician_name = serializers.CharField(source="clinician.user.full_name", read_only=True)

    class Meta:
        model = ConsultationNote
        fields = [
            "id",
            "case",
            "clinician",
            "clinician_name",
            "note_type",
            "content",
            "vital_signs",
            "diagnosis",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "case", "clinician", "created_at", "updated_at"]


class CreateConsultationNoteSerializer(serializers.Serializer):
    note_type = serializers.ChoiceField(
        choices=ConsultationNote.NoteType.choices, default=ConsultationNote.NoteType.ROUTINE
    )
    content = serializers.CharField()
    vital_signs = serializers.JSONField(required=False, allow_null=True)
    diagnosis = serializers.JSONField(required=False, allow_null=True)


class TreatmentPlanSerializer(serializers.ModelSerializer):
    clinician_name = serializers.CharField(source="clinician.user.full_name", read_only=True)

    class Meta:
        model = TreatmentPlan
        fields = [
            "id",
            "case",
            "clinician",
            "clinician_name",
            "title",
            "description",
            "medications",
            "lifestyle",
            "follow_up_days",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "case", "clinician", "created_at", "updated_at"]


class PrescriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prescription
        fields = ["id", "patient", "medications", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "clinician", "created_at", "updated_at"]


class CreateTreatmentPlanSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField()
    medications = serializers.JSONField(required=False, allow_null=True)
    lifestyle = serializers.JSONField(required=False, allow_null=True)
    follow_up_days = serializers.IntegerField(default=30, min_value=1, max_value=365)
