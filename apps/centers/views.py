"""
apps/centers/views.py
──────────────────────
All center-related API views.

PHC PORTAL VIEWS (screens PHC2, PHC3, PHC4, PHC6):
  PHCPatientQueueView       GET  /phc/queue/              — PHC patient queue (PHC2)
  PHCPatientRecordView      GET/PATCH /phc/queue/<uuid>/  — single record (PHC3)
  PHCEscalateView           POST /phc/queue/<uuid>/escalate/ — escalate to FMC (PHC6)
  PHCWalkInView             POST /phc/walk-in/            — register walk-in patient (PHC4)

FMC PORTAL VIEWS (screens FMC2, FMC3, FMC4, FMC8):
  FMCCaseListView           GET  /fmc/cases/
  FMCCaseDetailView         GET  /fmc/cases/<uuid>/
  FMCAssignClinicianView    POST /fmc/cases/<uuid>/assign/
  FMCDischargeCaseView      POST /fmc/cases/<uuid>/discharge/

CLINICIAN PORTAL VIEWS (screens CL2, CL3):
  ClinicianCaseListView     GET  /clinician/cases/
  ClinicianCaseDetailView   GET  /clinician/cases/<uuid>/

ACCOUNT MANAGEMENT:
  PHC Admin  → /phc/profile/, /phc/staff/, /phc/staff/<uuid>/
  FMC Admin  → /fmc/profile/, /fmc/staff/, /fmc/staff/<uuid>/,
                /fmc/clinicians/, /fmc/clinicians/<uuid>/, /fmc/clinicians/<uuid>/verify/
  Clinician  → /clinician/profile/
  Patient    → /change-request/, /change-request/<uuid>/
  Platform Admin → /admin/phc/, /admin/phc/<uuid>/, /admin/fmc/, /admin/fmc/<uuid>/
"""

import secrets
import string
import uuid
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.responses import success_response, created_response, error_response
from core.permissions.roles import (
    IsHCCAdmin,
    IsAnyPHCUser,
    IsFHCAdmin,
    IsAnyFMCUser,
    IsClinician,
    IsPatient,
)
from .models import (
    HealthCareCenter,
    FederalHealthCenter,
    StateHospital,
    StateTeachingHospital,
    FederalTeachingHospital,
    HealthInsuranceOrganization,
    Clinic,
    PrivateHospital,
    PrivateTeachingHospital,
    Country,
    State,
    HCCStaffProfile,
    FHCStaffProfile,
    ClinicianProfile,
    PHCPatientRecord,
    PatientCase,
    ConsultationNote,
    TreatmentPlan,
    ChangeRequest,
    Prescription,
)
from .serializers import (
    HealthCareCenterSerializer,
    HealthCareCenterPublicSerializer,
    FederalHealthCenterSerializer,
    FederalHealthCenterPublicSerializer,
    HCCStaffProfileSerializer,
    CreateHCCStaffSerializer,
    FHCStaffProfileSerializer,
    CreateFHCStaffSerializer,
    ClinicianProfileSerializer,
    UpdateClinicianProfileSerializer,
    ClinicianOnboardingSerializer,
    CreateClinicianSerializer,
    ChangeRequestSerializer,
    ConsultationNoteSerializer,
    CreateConsultationNoteSerializer,
    TreatmentPlanSerializer,
    CreateTreatmentPlanSerializer,
    PHCWalkInSerializer,
    PHCAdviceSerializer,
    FMCDiagnosticsRequestSerializer,
    FMCDischargeSerializer,
)

from .constants import DOWNSTREAM_DISEASES

from apps.accounts.tasks import send_staff_credentials_email_task

User = get_user_model()


def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ── Public: Center dropdowns ──────────────────────────────────────────────────


class HCCListPublicView(APIView):
    """
    GET /api/v1/centers/phc/
    Optional: ?state=Lagos&lga=Surulere
    No authentication required. Used by onboarding step 7.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Public"],
        summary="List active PHCs",
        description=(
            "Returns active PHCs for dropdown lists.\n\n"
            "**Query params:** `?state=Lagos` and/or `?lga=Surulere`\n\n"
            "Used by onboarding step 7 to show nearby PHCs."
        ),
    )
    def get(self, request):
        qs = HealthCareCenter.objects.filter(status=HealthCareCenter.CenterStatus.ACTIVE)
        state = request.query_params.get("state")
        lga = request.query_params.get("lga")
        if state:
            qs = qs.filter(state__iexact=state)
        if lga:
            qs = qs.filter(lga__iexact=lga)
        return success_response(
            data=HealthCareCenterPublicSerializer(qs.order_by("name"), many=True).data
        )


class FHCListPublicView(APIView):
    """GET /api/v1/centers/fmc/ — No auth required."""

    permission_classes = [AllowAny]

    @extend_schema(tags=["Public"], summary="List active FMCs")
    def get(self, request):
        centers = FederalHealthCenter.objects.filter(
            status=FederalHealthCenter.CenterStatus.ACTIVE
        ).order_by("state", "name")
        return success_response(data=FederalHealthCenterPublicSerializer(centers, many=True).data)


# ── PHC Portal: Patient Queue ─────────────────────────────────────────────────


class PHCPatientQueueView(APIView):
    """
    GET /api/v1/centers/phc/queue/

    PHC staff and admin see their patient queue (screen PHC2).
    Returns all PHCPatientRecords linked to the authenticated user's PHC.

    Optional filters: ?status=new&condition=pcos
    Default: returns all non-discharged records, newest first.
    """

    permission_classes = [IsAuthenticated, IsAnyPHCUser]

    @extend_schema(
        tags=["PHC Portal"],
        summary="Get PHC patient queue (PHC2)",
        description=(
            "Returns all patient records for this PHC.\n\n"
            "**Filters (optional):**\n"
            "- `status` — `new` | `under_review` | `action_taken` | `escalated` | `discharged`\n"
            "- `condition` — `pcos` | `maternal` | `cardiovascular`\n"
            "- `severity` — `mild` | `moderate`\n"
            "- `search` — search by patient name or email"
        ),
    )
    def get(self, request):
        hcc = _get_user_hcc(request.user)
        if not hcc:
            return error_response("No PHC facility linked to your account.", http_status=404)

        qs = PHCPatientRecord.objects.filter(hcc=hcc).select_related("patient", "escalated_to_case")

        status = request.query_params.get("status")
        condition = request.query_params.get("condition")
        severity = request.query_params.get("severity")
        search = request.query_params.get("search")

        if status:
            qs = qs.filter(status=status)
        if condition:
            qs = qs.filter(condition=condition)
        if severity:
            qs = qs.filter(severity=severity)
        if search:
            qs = qs.filter(patient__full_name__icontains=search) | qs.filter(
                patient__email__icontains=search
            )

        # Default: exclude discharged and escalated
        if not status:
            qs = qs.exclude(
                status__in=[
                    PHCPatientRecord.RecordStatus.DISCHARGED,
                    PHCPatientRecord.RecordStatus.ESCALATED,
                ]
            )

        return success_response(data=[_serialize_phc_record(r) for r in qs.order_by("-opened_at")])


class PHCPatientRecordView(APIView):
    """
    GET   /api/v1/centers/phc/queue/<uuid:pk>/ — view record (PHC3)
    PATCH /api/v1/centers/phc/queue/<uuid:pk>/ — update notes, status, follow-up
    """

    permission_classes = [IsAuthenticated, IsAnyPHCUser]

    def _get_record(self, pk, user):
        hcc = _get_user_hcc(user)
        if not hcc:
            return None
        try:
            return PHCPatientRecord.objects.select_related(
                "patient", "hcc", "escalated_to_case"
            ).get(pk=pk, hcc=hcc)
        except PHCPatientRecord.DoesNotExist:
            return None

    @extend_schema(
        tags=["PHC Portal"],
        summary="Get PHC patient record detail (PHC3)",
        description="Returns full detail of a single PHC patient record.",
    )
    def get(self, request, pk):
        record = self._get_record(pk, request.user)
        if not record:
            return error_response("Record not found.", http_status=404)

        # Auto-advance status from NEW to UNDER_REVIEW on first view
        if record.status == PHCPatientRecord.RecordStatus.NEW:
            record.status = PHCPatientRecord.RecordStatus.UNDER_REVIEW
            record.save(update_fields=["status"])

        return success_response(data=_serialize_phc_record(record))

    @extend_schema(
        tags=["PHC Portal"],
        summary="Update PHC patient record",
        description=(
            "PHC staff can update:\n"
            "- `status` — `under_review` | `action_taken` | `discharged`\n"
            "- `notes` — free text staff observations\n"
            "- `next_followup` — date for next follow-up (YYYY-MM-DD)"
        ),
    )
    def patch(self, request, pk):
        record = self._get_record(pk, request.user)
        if not record:
            return error_response("Record not found.", http_status=404)

        allowed_fields = {"status", "notes", "next_followup"}
        data = {k: v for k, v in request.data.items() if k in allowed_fields}

        # Validate status transitions
        new_status = data.get("status")
        if new_status:
            valid_transitions = {
                PHCPatientRecord.RecordStatus.NEW: [PHCPatientRecord.RecordStatus.UNDER_REVIEW],
                PHCPatientRecord.RecordStatus.UNDER_REVIEW: [
                    PHCPatientRecord.RecordStatus.ACTION_TAKEN,
                    PHCPatientRecord.RecordStatus.DISCHARGED,
                ],
                PHCPatientRecord.RecordStatus.ACTION_TAKEN: [
                    PHCPatientRecord.RecordStatus.DISCHARGED
                ],
            }
            allowed = valid_transitions.get(record.status, [])
            if new_status not in allowed:
                return error_response(
                    f"Cannot transition from '{record.status}' to '{new_status}'. "
                    f"Use the escalate endpoint to escalate to FMC."
                )

        for field, value in data.items():
            setattr(record, field, value)
        if data:
            record.save(update_fields=list(data.keys()))

        if new_status == PHCPatientRecord.RecordStatus.DISCHARGED:
            record.closed_at = timezone.now()
            record.save(update_fields=["closed_at"])
            # Notify patient they have been discharged at PHC level
            _notify_patient_phc_discharged(record)

        return success_response(
            data=_serialize_phc_record(record),
            message="Record updated.",
        )


class PHCEscalateView(APIView):
    """
    POST /api/v1/centers/phc/queue/<uuid:pk>/escalate/

    PHC staff escalates a patient record to FMC (screen PHC6).

    What happens:
      1. Finds the FMC via PHC.get_escalation_fmc()
      2. Creates a PatientCase at that FMC
      3. Updates PHCPatientRecord status → ESCALATED
      4. Links PHCPatientRecord.escalated_to_case → new PatientCase
      5. Notifies FMC admin + staff
      6. Notifies patient they have been referred to FMC

    Body (optional): { "urgency": "urgent", "notes": "Clinical observations..." }
    urgency: "routine" | "priority" | "urgent" (default: "priority")
    """

    permission_classes = [IsAuthenticated, IsAnyPHCUser]

    @extend_schema(
        tags=["PHC Portal"],
        summary="Escalate patient to FMC (PHC6)",
        description=(
            "Escalates a Mild/Moderate patient to the FMC for Severe-level care.\n\n"
            "The FMC is determined by this PHC's `escalates_to` link — PHC staff "
            "do not choose the FMC directly.\n\n"
            'Body (optional): `{ "urgency": "urgent", "notes": "..." }`\n'
            "urgency: `routine` | `priority` | `urgent`"
        ),
    )
    def post(self, request, pk):
        hcc = _get_user_hcc(request.user)
        if not hcc:
            return error_response("No PHC facility linked to your account.", http_status=404)

        try:
            record = PHCPatientRecord.objects.select_related("patient", "hcc").get(pk=pk, hcc=hcc)
        except PHCPatientRecord.DoesNotExist:
            return error_response("Record not found.", http_status=404)

        if not record.is_open():
            return error_response(f"Cannot escalate a record with status '{record.status}'.")

        if record.status == PHCPatientRecord.RecordStatus.ESCALATED:
            return error_response("This patient has already been escalated to FMC.")

        # Find the escalation FMC
        fmc = hcc.get_escalation_fmc()
        if not fmc:
            return error_response(
                f"This PHC has no linked FMC and no active FMC was found in "
                f"state '{hcc.state}'. Please contact the Platform Admin to "
                f"set up the escalation routing.",
                http_status=503,
            )

        urgency = request.data.get("urgency", "priority")
        notes = request.data.get("notes", "")

        # Add PHC notes before escalating
        if notes:
            record.notes = (record.notes + "\n\n" + notes).strip()
            record.save(update_fields=["notes"])

        # Create PatientCase at FMC
        # Map PHCPatientRecord condition to PatientCase condition
        condition_map = {
            PHCPatientRecord.Condition.PCOS: PatientCase.Condition.PCOS,
            PHCPatientRecord.Condition.MATERNAL: PatientCase.Condition.MATERNAL,
            PHCPatientRecord.Condition.CARDIOVASCULAR: PatientCase.Condition.CARDIOVASCULAR,
        }
        case = PatientCase.objects.create(
            patient=record.patient,
            fhc=fmc,
            condition=condition_map.get(record.condition, record.condition),
            severity=PatientCase.CaseStatus.OPEN,  # Will be reassigned to actual severity
            status=PatientCase.CaseStatus.OPEN,
            opening_score=record.latest_score or record.opening_score,
            fmc_notes=f"Escalated from {hcc.name}. PHC notes: {record.notes}",
        )
        # Fix severity — use the PHC record's severity
        case.severity = record.severity
        case.save(update_fields=["severity"])

        # Link the records
        record.escalated_to_case = case
        record.status = PHCPatientRecord.RecordStatus.ESCALATED
        record.closed_at = timezone.now()
        record.save(update_fields=["escalated_to_case", "status", "closed_at"])

        logger.info(
            "PHC '%s' escalated patient %s to FMC '%s'. Case: %s",
            hcc.name,
            record.patient.email,
            fmc.name,
            case.id,
        )

        # Notify FMC admin + staff
        _notify_fmc_of_escalation(
            case=case,
            hcc=hcc,
            fmc=fmc,
            urgency=urgency,
        )

        # Notify patient they have been referred
        _notify_patient_escalated(patient=record.patient, hcc=hcc, fmc=fmc)

        return success_response(
            data={
                "phc_record_id": str(record.id),
                "case_id": str(case.id),
                "fmc_name": fmc.name,
                "urgency": urgency,
                "status": record.status,
            },
            message=f"Patient escalated to {fmc.name}. FMC staff have been notified.",
        )


class PHCWalkInView(APIView):
    """
    POST /api/v1/centers/phc/walk-in/

    PHC staff registers a walk-in patient (screen PHC4).

    Creates:
      - A new User (role=patient, is_email_verified=True)
      - An OnboardingProfile with registered_hcc set to the staff's PHC
      - A PHCPatientRecord (status=NEW)

    The patient receives a temporary password via SMS/email.
    PHC staff's PHC is automatically set as the patient's home facility.
    """

    permission_classes = [IsAuthenticated, IsAnyPHCUser]

    @extend_schema(
        tags=["PHC Portal"],
        summary="Register walk-in patient (PHC4)",
        description=(
            "Registers a new patient who walked into the PHC without an app account.\n\n"
            "The patient is automatically linked to the PHC staff's facility.\n"
            "A temporary password is generated and should be shared with the patient.\n\n"
            "Required fields: `full_name`, `email` (or phone), `condition`, `severity`\n"
            "Optional: `age`, `notes`"
        ),
    )
    def post(self, request):
        hcc = _get_user_hcc(request.user)
        if not hcc:
            return error_response("No PHC facility linked to your account.", http_status=404)

        serializer = PHCWalkInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        temp_password = _generate_temp_password()

        # Create patient user
        patient = User.objects.create_user(
            email=data["email"],
            password=temp_password,
            full_name=data["full_name"],
            role=User.Role.PATIENT,
            is_email_verified=True,  # PHC staff vouches for identity
        )
        patient.must_change_password = True
        patient.save(update_fields=["must_change_password"])

        # Create onboarding profile and link to this PHC
        from apps.onboarding.models import OnboardingProfile

        profile = OnboardingProfile.objects.create(
            user=patient,
            full_name=data["full_name"],
            age=data.get("age"),
            gender=data.get("gender", ""),
            state=hcc.state,
            lga=hcc.lga,
            registered_hcc=hcc,
        )

        # Create PHC patient record
        condition_map = {
            "pcos": PHCPatientRecord.Condition.PCOS,
            "maternal": PHCPatientRecord.Condition.MATERNAL,
            "cardiovascular": PHCPatientRecord.Condition.CARDIOVASCULAR,
        }
        record = PHCPatientRecord.objects.create(
            patient=patient,
            hcc=hcc,
            condition=condition_map.get(data["condition"], data["condition"]),
            severity=data.get("severity", "moderate"),
            status=PHCPatientRecord.RecordStatus.NEW,
            notes=data.get("notes", ""),
        )

        # Send welcome email to patient with temporary password and login link
        try:
            from apps.accounts.tasks import send_patient_welcome_email_task
            send_patient_welcome_email_task.delay(
                user_name=patient.full_name,
                user_email=patient.email,
                temp_password=temp_password,
                facility_name=hcc.name,
                unique_id=getattr(patient, 'unique_id', None),
            )
        except Exception as e:
            logger.warning(f"Failed to send patient welcome email: {e}")

        logger.info(
            "Walk-in patient registered: %s at PHC '%s' by staff %s",
            patient.email,
            hcc.name,
            request.user.email,
        )

        return created_response(
            data={
                "patient_id": str(patient.id),
                "patient_email": patient.email,
                "patient_name": patient.full_name,
                "phc_record_id": str(record.id),
                "registered_hcc": hcc.name,
                "temp_password": temp_password,  # Staff shares this with patient
            },
            message=(
                f"Patient registered successfully and linked to {hcc.name}. "
                "Share the temporary password with the patient."
            ),
        )


class PHCWalkInComprehensiveView(APIView):
    """
    POST /api/v1/centers/phc/walk-in/comprehensive/

    Comprehensive walk-in registration with full health data.
    Creates patient, onboarding profile, and triggers predictions.
    """

    permission_classes = [IsAuthenticated, IsAnyPHCUser]

    @extend_schema(
        tags=["PHC Portal"],
        summary="Register walk-in patient with full assessment (PHC4)",
        description="Comprehensive registration including demographics, measurements, and symptoms.",
    )
    def post(self, request):
        hcc = _get_user_hcc(request.user)
        if not hcc:
            return error_response("No PHC facility linked to your account.", http_status=404)

        serializer = PHCWalkInComprehensiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        temp_password = _generate_temp_password()
        full_name = f"{data['first_name']} {data['last_name']}"

        email = data.get("email") or f"walkin_{uuid.uuid4().hex[:8]}@placeholder.local"

        patient = User.objects.create_user(
            email=email,
            password=temp_password,
            full_name=full_name,
            role=User.Role.PATIENT,
            is_email_verified=True,
        )
        patient.must_change_password = True
        patient.save(update_fields=["must_change_password"])

        from apps.onboarding.models import OnboardingProfile

        profile = OnboardingProfile.objects.create(
            user=patient,
            full_name=full_name,
            state=hcc.state,
            lga=hcc.lga,
            registered_hcc=hcc,
            height_cm=data.get("height_cm"),
            weight_kg=data.get("weight_kg"),
            cycle_regularity=data.get("cycle_regularity", ""),
            cycle_length_days=data.get("typical_cycle_length"),
            periods_per_year=data.get("periods_per_year"),
            has_skin_changes=True if data.get("acanthosis_nigricans") == "yes" else False,
        )

        if profile.height_cm and profile.weight_kg:
            profile.bmi = round(profile.weight_kg / ((profile.height_cm / 100) ** 2), 1)
            profile.save(update_fields=["bmi"])

        condition_map = {
            "pcos": PHCPatientRecord.Condition.PCOS,
            "maternal": PHCPatientRecord.Condition.MATERNAL,
            "cardiovascular": PHCPatientRecord.Condition.CARDIOVASCULAR,
        }
        record = PHCPatientRecord.objects.create(
            patient=patient,
            hcc=hcc,
            condition=PHCPatientRecord.Condition.PCOS,
            severity="moderate",
            status=PHCPatientRecord.RecordStatus.NEW,
        )

        from apps.predictions.signals import trigger_comprehensive_prediction

        try:
            trigger_comprehensive_prediction(patient)
        except Exception as e:
            logger.warning("Failed to trigger prediction for walk-in patient: %s", e)

        logger.info(
            "Walk-in patient (comprehensive) registered: %s at PHC '%s' by staff %s",
            patient.email,
            hcc.name,
            request.user.email,
        )

        return created_response(
            data={
                "patient_id": str(patient.id),
                "patient_email": patient.email,
                "patient_name": patient.full_name,
                "phc_record_id": str(record.id),
                "registered_hcc": hcc.name,
                "temp_password": temp_password,
                "phone": data.get("phone", ""),
            },
            message=(
                f"Patient registered successfully and linked to {hcc.name}. "
                "Share the temporary password with the patient."
            ),
        )


# ── Walk-in Patient Registration for All Facility Types ───────────────────


class GenericWalkInView(APIView):
    """
    POST /api/v1/centers/{facility}/walk-in/
    
    Generic walk-in patient registration for all facility types.
    Each facility type can register patients:
    - FMC, STH, STTH, FTH (Government hospitals)
    - HMO (Enrollees)
    - Clinic, PVT, PTTH (Private facilities)
    
    Creates:
      - A new User (role=patient, is_email_verified=True)
      - An OnboardingProfile with registered facility
      - A PatientRecord for the facility
    """
    
    def _get_facility_for_user(self, user):
        """Get facility based on user's role."""
        role = user.role
        
        try:
            # Government facilities
            if role in ("hcc_admin", "hcc_staff"):
                if role == "hcc_admin":
                    return user.managed_hcc, "PHC", "phc"
                return user.hcc_staff_profile.hcc, "PHC", "phc"
            
            if role in ("fhc_admin", "fhc_staff", "clinician"):
                if role == "fhc_admin":
                    return user.managed_fhc, "FMC", "fmc"
                elif role == "fhc_staff":
                    return user.fhc_staff_profile.fhc, "FMC", "fmc"
                return user.clinician_profile.fhc, "FMC", "fmc"
            
            if role in ("sth_admin", "sth_staff"):
                if role == "sth_admin":
                    return user.managed_state_hospital, "STH", "sth"
                return user.sth_staff_profile.sth, "STH", "sth"
            
            if role in ("stth_admin", "stth_staff"):
                if role == "stth_admin":
                    return user.managed_state_teaching, "STTH", "stth"
                return user.stth_staff_profile.stth, "STTH", "stth"
            
            if role in ("fth_admin", "fth_staff"):
                if role == "fth_admin":
                    return user.managed_federal_teaching, "FTH", "fth"
                return user.fth_staff_profile.fth, "FTH", "fth"
            
            # Private/Insurance facilities
            if role in ("hmo_admin", "hmo_staff"):
                if role == "hmo_admin":
                    return user.managed_hmo, "HMO", "hmo"
                return user.hmo_staff_profile.hmo, "HMO", "hmo"
            
            if role in ("clinic_admin", "clinic_staff"):
                if role == "clinic_admin":
                    return user.managed_clinic, "CLINIC", "cln"
                return user.clinic_staff_profile.clinic, "CLINIC", "cln"
            
            if role in ("pvt_admin", "pvt_staff"):
                if role == "pvt_admin":
                    return user.managed_private_hospital, "PVT", "pvt"
                return user.pvt_staff_profile.pvt, "PVT", "pvt"
            
            if role in ("ptth_admin", "ptth_staff"):
                if role == "ptth_admin":
                    return user.managed_ptth, "PTTH", "ptth"
                return user.ptth_staff_profile.ptth, "PTTH", "ptth"
        except Exception as e:
            logger.warning(f"Failed to get facility for user {user.email}: {e}")
            return None, None, None
        
        return None, None, None
    
    def _get_permission_class(self, facility_type):
        """Get permission class based on facility type."""
        if facility_type in ("phc", "sth", "stth", "fth"):
            return IsAuthenticated  # Use generic authenticated for now
        elif facility_type in ("fmc",):
            return IsAuthenticated
        elif facility_type in ("hmo",):
            return IsAuthenticated
        elif facility_type in ("cln", "pvt", "ptth"):
            return IsAuthenticated
        return IsAuthenticated
    
    @extend_schema(
        tags=["Walk-in Registration"],
        summary="Register walk-in patient",
        description=(
            "Register a new walk-in patient at any facility.\n\n"
            "Required fields: `full_name`, `email` (or phone), `condition`\n"
            "Optional: `age`, `notes`, `severity`"
        ),
    )
    def post(self, request, facility):
        facility = facility.lower()
        
        # Map facility URL to internal type
        facility_map = {
            "phc": "phc", "fmc": "fmc", "fmc": "fmc",
            "sth": "sth", "stth": "stth", "fth": "fth",
            "hmo": "hmo", "cln": "cln", "clinic": "cln",
            "pvt": "pvt", "ptth": "ptth",
        }
        facility_type = facility_map.get(facility, facility)
        
        # Get user's facility
        facility_obj, facility_name, _ = self._get_facility_for_user(request.user)
        
        if not facility_obj:
            return error_response(
                f"No {facility.upper()} facility linked to your account. "
                "Please contact your administrator.",
                http_status=404
            )
        
        data = request.data
        
        # Validate required fields
        if not data.get("full_name"):
            return error_response("full_name is required.", http_status=400)
        
        if not data.get("email") and not data.get("phone"):
            return error_response("Either email or phone is required.", http_status=400)
        
        # Generate temp password and create user
        temp_password = _generate_temp_password()
        email = data.get("email") or f"walkin_{uuid.uuid4().hex[:8]}@placeholder.local"
        
        try:
            patient = User.objects.create_user(
                email=email,
                password=temp_password,
                full_name=data["full_name"],
                role=User.Role.PATIENT,
                is_email_verified=True,
            )
            patient.must_change_password = True
            patient.save(update_fields=["must_change_password"])
            
        except Exception as e:
            return error_response(f"Failed to create patient: {str(e)}", http_status=400)
        
        # Send welcome email to patient with temporary password and login link
        try:
            from apps.accounts.tasks import send_patient_welcome_email_task
            send_patient_welcome_email_task.delay(
                user_name=patient.full_name,
                user_email=patient.email,
                temp_password=temp_password,
                facility_name=facility_obj.name,
                unique_id=getattr(patient, 'unique_id', None),
            )
        except Exception as e:
            logger.warning(f"Failed to send patient welcome email: {e}")
        
        # Create onboarding profile (signal already created one — update it)
        from apps.onboarding.models import OnboardingProfile
        
        state = getattr(facility_obj, "state", "")
        lga = getattr(facility_obj, "lga", "")
        
        profile, _ = OnboardingProfile.objects.get_or_create(user=patient)
        profile.full_name = data["full_name"]
        profile.age = data.get("age")
        profile.gender = data.get("gender", "")
        profile.state = state
        profile.lga = lga
        
        # Link PHC if available (other facilities use state for backward compatibility)
        if facility_type == "phc" and hasattr(facility_obj, 'id'):
            profile.registered_hcc = facility_obj
        profile.save()
        
        # Create patient record for the facility
        condition = data.get("condition", "pcos")
        severity = data.get("severity", "moderate")
        
        # Map condition to enum
        condition_map = {
            "pcos": PatientCase.Condition.PCOS,
            "maternal": PatientCase.Condition.MATERNAL,
            "cardiovascular": PatientCase.Condition.CARDIOVASCULAR,
        }
        mapped_condition = condition_map.get(condition, PatientCase.Condition.PCOS)
        
        # Create facility-specific record
        if facility_type == "phc":
            record = PHCPatientRecord.objects.create(
                patient=patient,
                hcc=facility_obj,
                condition=mapped_condition,
                severity=severity,
                status=PHCPatientRecord.RecordStatus.NEW,
                notes=data.get("notes", ""),
            )
        elif facility_type == "fmc":
            # Create FMC case
            case = PatientCase.objects.create(
                patient=patient,
                fhc=facility_obj,
                condition=mapped_condition,
                severity=severity,
                status=PatientCase.CaseStatus.OPEN,
                fmc_notes=data.get("notes", ""),
            )
            record = case
        else:
            # For other facilities, just create a generic record
            # Could extend based on facility type
            record = None
        
        logger.info(
            "Walk-in patient registered: %s at %s '%s' by staff %s",
            patient.email,
            facility_type.upper(),
            facility_obj.name,
            request.user.email,
        )
        
        return created_response(
            data={
                "patient_id": str(patient.id),
                "patient_email": patient.email,
                "patient_name": patient.full_name,
                "facility_name": facility_obj.name,
                "facility_type": facility_type.upper(),
                "temp_password": temp_password,
                "phone": data.get("phone", ""),
            },
            message=(
                f"Patient registered successfully at {facility_obj.name}. "
                "Share the temporary password with the patient."
            ),
        )


# ── PHC Advice ───────────────────────────────────────────────────────────────────


class PHCSendAdviceView(APIView):
    """
    POST /api/v1/centers/phc/advice/
    Send lifestyle advice to a patient record.
    """

    permission_classes = [IsAuthenticated, IsAnyPHCUser]

    @extend_schema(
        tags=["PHC Portal"],
        summary="Send lifestyle advice to patient (PHC5)",
        request=PHCAdviceSerializer,
        description="Sends lifestyle advice to a patient and updates the record status.",
    )
    def post(self, request):
        serializer = PHCAdviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        queue_record_id = request.data.get("queue_record_id")
        if not queue_record_id:
            return error_response("queue_record_id is required.", http_status=400)

        try:
            record = PHCPatientRecord.objects.get(pk=queue_record_id, hcc=request.user.managed_hcc)
        except PHCPatientRecord.DoesNotExist:
            return error_response("Patient record not found.", http_status=404)

        record.notes = data.get("message", "")
        record.last_advice_at = timezone.now()

        if data.get("followup_date"):
            record.next_followup = data.get("followup_date")

        if record.status == PHCPatientRecord.RecordStatus.NEW:
            record.status = PHCPatientRecord.RecordStatus.ACTION_TAKEN

        record.save()

        return created_response(
            data={
                "id": str(uuid.uuid4()),
                "queue_record_id": str(record.id),
                "condition": record.condition,
                "message": data.get("message"),
                "followup_date": data.get("followup_date"),
                "sent_at": record.last_advice_at.isoformat(),
                "sent_by_name": request.user.full_name,
            },
            message="Advice sent successfully.",
        )


class PHCAdviceHistoryView(APIView):
    """
    GET /api/v1/centers/phc/advice/
    Get recent advice history for the PHC.
    """

    permission_classes = [IsAuthenticated, IsAnyPHCUser]

    @extend_schema(
        tags=["PHC Portal"],
        summary="Get recent advice history (PHC5)",
        description="Returns recent lifestyle advice sent by PHC staff.",
    )
    def get(self, request):
        hcc = _get_user_hcc(request.user)
        if not hcc:
            return error_response("No PHC facility linked to your account.", http_status=404)

        limit = int(request.query_params.get("limit", 10))
        records = (
            PHCPatientRecord.objects.filter(hcc=hcc, last_advice_at__isnull=False)
            .select_related("patient")
            .order_by("-last_advice_at")[:limit]
        )

        results = []
        for record in records:
            results.append(
                {
                    "id": str(uuid.uuid4()),
                    "queue_record_id": str(record.id),
                    "patient_name": record.patient.full_name,
                    "patient_email": record.patient.email,
                    "condition": record.condition,
                    "message": record.notes,
                    "sent_at": record.last_advice_at.isoformat() if record.last_advice_at else None,
                }
            )

        return success_response(data={"results": results})


# ── PHC Analytics ───────────────────────────────────────────────────────────────


class PHCAnalyticsView(APIView):
    """
    GET /api/v1/centers/phc/analytics/
    Get analytics data for the PHC.
    """

    permission_classes = [IsAuthenticated, IsAnyPHCUser]

    @extend_schema(
        tags=["PHC Portal"],
        summary="Get PHC analytics (PHC7)",
        description="Returns analytics data for the PHC including patient stats and activity.",
    )
    def get(self, request):
        hcc = _get_user_hcc(request.user)
        if not hcc:
            return error_response("No PHC facility linked to your account.", http_status=404)

        range_param = request.query_params.get("range", "30d")

        from datetime import timedelta
        from django.utils import timezone

        today = timezone.now().date()
        if range_param == "7d":
            start_date = today - timedelta(days=7)
        elif range_param == "90d":
            start_date = today - timedelta(days=90)
        else:
            start_date = today - timedelta(days=30)

        all_records = PHCPatientRecord.objects.filter(hcc=hcc)
        active_records = all_records.exclude(
            status__in=[
                PHCPatientRecord.RecordStatus.DISCHARGED,
                PHCPatientRecord.RecordStatus.ESCALATED,
            ]
        )

        total_patients = all_records.count()
        active_minor_risk = active_records.filter(severity__in=["mild", "moderate"]).count()

        escalated_this_period = all_records.filter(
            status=PHCPatientRecord.RecordStatus.ESCALATED, closed_at__gte=start_date
        ).count()

        records_with_advice = active_records.filter(last_advice_at__isnull=False).values_list(
            "last_advice_at", flat=True
        )

        if records_with_advice:
            avg_days = sum((timezone.now() - d).days for d in records_with_advice if d) / len(
                records_with_advice
            )
        else:
            avg_days = 0.0

        risk_distribution = {
            "low": active_records.filter(severity="mild").count(),
            "moderate": active_records.filter(severity="moderate").count(),
        }

        condition_breakdown = {
            "pcos": active_records.filter(condition=PHCPatientRecord.Condition.PCOS).count(),
            "hormonal": active_records.filter(
                condition=PHCPatientRecord.Condition.MATERNAL
            ).count(),
            "metabolic": active_records.filter(
                condition=PHCPatientRecord.Condition.CARDIOVASCULAR
            ).count(),
        }

        escalations_timeline = []
        for i in range(4):
            week_start = today - timedelta(days=(i * 7 + 7))
            week_end = today - timedelta(days=i * 7)
            count = all_records.filter(
                status=PHCPatientRecord.RecordStatus.ESCALATED,
                closed_at__gte=week_start,
                closed_at__lt=week_end,
            ).count()
            escalations_timeline.append({"week": f"Week {4 - i}", "count": count})
        escalations_timeline.reverse()

        staff_actions = {
            "advice_sent": active_records.filter(last_advice_at__gte=start_date).count(),
            "followups_scheduled": active_records.filter(next_followup__gte=today).count(),
            "patients_discharged": all_records.filter(
                status=PHCPatientRecord.RecordStatus.DISCHARGED, closed_at__gte=start_date
            ).count(),
        }

        return success_response(
            data={
                "total_patients": total_patients,
                "active_minor_risk": active_minor_risk,
                "escalated_this_period": escalated_this_period,
                "avg_time_to_action_days": round(avg_days, 1),
                "risk_distribution": risk_distribution,
                "condition_breakdown": condition_breakdown,
                "escalations_timeline": escalations_timeline,
                "staff_actions": staff_actions,
            }
        )


# ── FMC Portal Views ────────────────────────────────────────────────────────────


def _get_user_fmc(user):
    """Get the FMC linked to the user's account."""
    try:
        return user.managed_fhc
    except Exception:
        return None


class FMCAnalyticsView(APIView):
    """
    GET /api/v1/fmc/analytics/
    Get population analytics for the FMC.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get FMC population analytics (FMC6)",
        description="Returns analytics data for the FMC including case severity and outcomes.",
    )
    def get(self, request):
        # Debug: Check if permissions allow access
        print(f"FMCAnalyticsView: user={request.user.email}, role={request.user.role}")
        print(
            f"FMCAnalyticsView: has fhc_staff_profile={hasattr(request.user, 'fhc_staff_profile')}"
        )

        fhc = _get_user_fhc(request.user)
        print(f"FMCAnalyticsView: fhc={fhc}")

        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)

        range_param = request.query_params.get("range", "30d")

        # Map frontend params to backend values
        range_map = {
            "this_month": "30d",
            "this_week": "7d",
            "3_months": "90d",
        }
        range_param = range_map.get(range_param, range_param)

        from datetime import timedelta
        from django.utils import timezone

        today = timezone.now().date()
        if range_param == "7d":
            start_date = today - timedelta(days=7)
        elif range_param == "90d":
            start_date = today - timedelta(days=90)
        else:
            start_date = today - timedelta(days=30)

        from .models import PatientCase

        all_cases = PatientCase.objects.filter(fhc=fhc)
        active_cases = all_cases.exclude(
            status__in=[
                PatientCase.CaseStatus.DISCHARGED,
            ]
        )

        total_active_cases = active_cases.count()
        critical_cases = active_cases.filter(severity="critical")
        high_cases = active_cases.filter(severity="high")

        critical_unassigned = critical_cases.filter(clinician__isnull=True).count()
        critical_assigned = critical_cases.filter(clinician__isnull=False).count()
        high_unassigned = high_cases.filter(clinician__isnull=True).count()
        high_assigned = high_cases.filter(clinician__isnull=False).count()

        cases_with_assignment = active_cases.filter(
            clinician__isnull=False, assigned_at__isnull=False
        ).values_list("assigned_at", flat=True)

        if cases_with_assignment:
            avg_days = sum((timezone.now() - d).days for d in cases_with_assignment if d) / len(
                cases_with_assignment
            )
        else:
            avg_days = 0.0

        cases_resolved_this_month = all_cases.filter(
            status=PatientCase.CaseStatus.DISCHARGED, closed_at__gte=start_date
        ).count()

        severity_distribution = {
            "critical": critical_cases.count(),
            "high": high_cases.count(),
        }

        condition_prevalence = {
            "pcos": active_cases.filter(condition=PatientCase.Condition.PCOS).count(),
            "hormonal": active_cases.filter(condition=PatientCase.Condition.MATERNAL).count(),
            "metabolic": active_cases.filter(
                condition=PatientCase.Condition.CARDIOVASCULAR
            ).count(),
        }

        from apps.centers.models import PHCPatientRecord

        referring_phcs = (
            PHCPatientRecord.objects.filter(escalated_to_case__fhc=fhc, closed_at__gte=start_date)
            .values("hcc__name")
            .annotate(count=models.Count("id"))
        )

        referral_sources = [
            {"phc_name": item["hcc__name"], "count": item["count"]} for item in referring_phcs
        ]

        time_to_assignment_histogram = []
        for i in range(5):
            day_start = i * 2
            day_end = (i + 1) * 2
            count = active_cases.filter(
                assigned_at__isnull=False,
                assigned_at__gte=timezone.now() - timedelta(days=day_end),
                assigned_at__lt=timezone.now() - timedelta(days=day_start),
            ).count()
            time_to_assignment_histogram.append(
                {"range": f"{day_start}-{day_end} days", "count": count}
            )

        outcomes_tracker = {
            "resolved": all_cases.filter(status=PatientCase.CaseStatus.DISCHARGED).count(),
            "under_treatment": active_cases.count(),
            "referred_externally": 0,
        }

        from apps.centers.models import ClinicianProfile

        clinicians = ClinicianProfile.objects.filter(fhc=fhc)
        clinician_load = []
        for clinician in clinicians:
            case_count = active_cases.filter(clinician=clinician).count()
            clinician_load.append(
                {
                    "clinician_name": clinician.user.full_name,
                    "specialization": clinician.specialization,
                    "active_cases": case_count,
                }
            )

        return success_response(
            data={
                "total_active_cases": total_active_cases,
                "critical_unassigned": critical_unassigned,
                "critical_assigned": critical_assigned,
                "high_unassigned": high_unassigned,
                "high_assigned": high_assigned,
                "avg_days_to_assignment": round(avg_days, 1),
                "cases_resolved_this_month": cases_resolved_this_month,
                "severity_distribution": severity_distribution,
                "condition_prevalence": condition_prevalence,
                "referral_sources": referral_sources,
                "time_to_assignment_histogram": time_to_assignment_histogram,
                "outcomes_tracker": outcomes_tracker,
                "clinician_load": clinician_load,
            }
        )


class FMCNetworkPHCView(APIView):
    """
    GET /api/v1/centers/fmc/network-phc/
    Get PHCs that refer to this FMC with referral statistics.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get FMC network PHCs (FMC13)",
        description="Returns PHCs that refer to this FMC with referral statistics.",
    )
    def get(self, request):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)

        # Find PHCs that have escalates_to pointing to this FMC
        from .models import HealthCareCenter, PatientCase, PHCPatientRecord

        # Get PHCs that escalate to this FMC
        referring_phcs = HealthCareCenter.objects.filter(
            escalates_to=fhc, status=HealthCareCenter.CenterStatus.ACTIVE
        ).select_related("escalates_to")

        # For each PHC, get referral stats
        phc_list = []
        for phc in referring_phcs:
            # Get cases from this PHC (via phc_record relationship)
            phc_cases = PatientCase.objects.filter(fhc=fhc).select_related("phc_record")

            # Filter cases that came from this PHC
            total_referrals = phc_cases.filter(phc_record__hcc=phc).count()
            pending_referrals = (
                phc_cases.exclude(
                    status__in=[
                        PatientCase.CaseStatus.DISCHARGED,
                    ]
                )
                .filter(phc_record__hcc=phc)
                .count()
            )

            # Get last referral date
            last_case = phc_cases.filter(phc_record__hcc=phc).order_by("-opened_at").first()
            last_referral_date = (
                last_case.opened_at.isoformat() if last_case and last_case.opened_at else None
            )

            phc_list.append(
                {
                    "id": str(phc.id),
                    "name": phc.name,
                    "code": phc.code,
                    "address": phc.address,
                    "state": phc.state,
                    "lga": phc.lga,
                    "phone": phc.phone,
                    "email": phc.email,
                    "status": phc.status.lower() if hasattr(phc.status, "lower") else phc.status,
                    "total_referrals": total_referrals,
                    "pending_referrals": pending_referrals,
                    "last_referral_date": last_referral_date,
                }
            )

        # Sort by total referrals descending
        phc_list.sort(key=lambda x: x["total_referrals"], reverse=True)

        return success_response(data=phc_list)


class FMCAlertsView(APIView):
    """
    GET /api/v1/fmc/alerts/
    Get priority-sorted alert feed for FMC.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get FMC alerts (FMC7)",
        description="Returns priority-sorted alerts including critical unassigned cases.",
    )
    def get(self, request):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)

        from .models import PatientCase
        from datetime import timedelta

        active_cases = (
            PatientCase.objects.filter(fhc=fhc)
            .exclude(
                status__in=[
                    PatientCase.CaseStatus.DISCHARGED,
                ]
            )
            .select_related("patient")
        )

        pinned_alerts = []
        regular_alerts = []

        critical_unassigned = active_cases.filter(severity="critical", clinician__isnull=True)
        for case in critical_unassigned:
            pinned_alerts.append(
                {
                    "id": str(uuid.uuid4()),
                    "alert_type": "critical_unassigned",
                    "severity": "critical",
                    "patient_id": str(case.patient.id),
                    "patient_name": case.patient.full_name,
                    "message": f"Critical patient unassigned - requires immediate clinician assignment",
                    "timestamp": case.assigned_at or case.opened_at,
                    "is_read": False,
                    "action_required": True,
                }
            )

        new_referrals = active_cases.filter(
            status=PatientCase.CaseStatus.ASSIGNED,
            assigned_at__gte=timezone.now() - timedelta(days=3),
        )
        for case in new_referrals:
            regular_alerts.append(
                {
                    "id": str(uuid.uuid4()),
                    "alert_type": "new_referral",
                    "severity": "high",
                    "patient_id": str(case.patient.id),
                    "patient_name": case.patient.full_name,
                    "message": f"New referral received from PHC - case requires review",
                    "timestamp": case.assigned_at,
                    "is_read": False,
                    "action_required": False,
                }
            )

        return success_response(
            data={
                "pinned_alerts": pinned_alerts,
                "regular_alerts": regular_alerts,
            }
        )


class FMCRequestDiagnosticsView(APIView):
    """
    POST /api/v1/fmc/request-diagnostics/
    Request diagnostic tests from a patient.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Request diagnostics (FMC5)",
        request=FMCDiagnosticsRequestSerializer,
        description="Sends a diagnostic test request to the patient.",
    )
    def post(self, request):
        serializer = FMCDiagnosticsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            case = PatientCase.objects.get(pk=data["patient_id"], fhc=request.user.managed_fhc)
        except PatientCase.DoesNotExist:
            return error_response("Patient case not found.", http_status=404)

        logger.info(
            "Diagnostics requested for patient %s by FMC %s - tests: %s",
            case.patient.email,
            request.user.managed_fhc.name,
            data["tests"],
        )

        return created_response(
            data={
                "patient_id": str(case.patient.id),
                "tests_requested": data["tests"],
                "urgency": data["urgency"],
                "status": "request_sent",
                "message": "Diagnostic request sent to patient.",
            }
        )


class FMCDiagnosticsStatusView(APIView):
    """
    GET /api/v1/fmc/diagnostics-status/{patient_id}/
    Get diagnostics request status for a patient.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get diagnostics status",
        description="Returns pending and completed diagnostics requests.",
    )
    def get(self, request, patient_id):
        fhc = _get_user_fmc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)

        return success_response(
            data={
                "pending_requests": [],
                "received_results": [],
            }
        )


class FMCDischargeView(APIView):
    """
    POST /api/v1/fmc/discharge/{patient_id}/
    Discharge a patient case with outcome summary.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Discharge patient (FMC8)",
        request=FMCDischargeSerializer,
        description="Closes a patient case with final diagnosis and discharge letter.",
    )
    def post(self, request, patient_id):
        serializer = FMCDischargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            case = PatientCase.objects.get(pk=patient_id, fhc=request.user.managed_fhc)
        except PatientCase.DoesNotExist:
            return error_response("Patient case not found.", http_status=404)

        case.status = PatientCase.CaseStatus.DISCHARGED
        case.closing_score = data.get("closing_score")
        case.closing_notes = data.get("treatment_summary")
        case.closed_at = timezone.now()
        case.save()

        logger.info(
            "Patient %s discharged from FMC %s - condition: %s",
            case.patient.email,
            request.user.managed_fhc.name,
            data.get("condition_confirmed"),
        )

        return success_response(
            data={
                "patient_id": str(case.patient.id),
                "condition_confirmed": data.get("condition_confirmed"),
                "follow_up_plan": data.get("follow_up_plan"),
                "discharge_date": case.closed_at.isoformat(),
                "status": "discharged",
                "message": "Patient discharged successfully.",
            }
        )


class FMC_autoAssignView(APIView):
    """
    POST /api/v1/fmc/auto-assign/
    Auto-assign unassigned patients to clinicians.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Auto-assign patients",
        description="Automatically assigns unassigned patients to available clinicians.",
    )
    def post(self, request):
        fhc = _get_user_fmc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)

        from .models import PatientCase, ClinicianProfile

        unassigned_cases = PatientCase.objects.filter(
            fhc=fhc,
            clinician__isnull=True,
            status__in=[PatientCase.CaseStatus.NEW, PatientCase.CaseStatus.ASSIGNED],
        )

        clinicians = ClinicianProfile.objects.filter(fhc=fhc, is_available=True).order_by(
            "user__full_name"
        )

        if not clinicians.exists():
            return error_response("No available clinicians to assign.", http_status=400)

        assignments = []
        clinician_list = list(clinicians)
        clinician_idx = 0

        for case in unassigned_cases:
            clinician = clinician_list[clinician_idx]
            case.clinician = clinician.user
            case.status = PatientCase.CaseStatus.ASSIGNED
            case.assigned_at = timezone.now()
            case.save()

            assignments.append(
                {
                    "case_id": str(case.id),
                    "patient_name": case.patient.full_name,
                    "clinician_name": clinician.user.full_name,
                }
            )

            clinician_idx = (clinician_idx + 1) % len(clinician_list) if clinician_list else 0

        return success_response(
            data={
                "assignments": assignments,
                "total_assigned": len(assignments),
                "message": f"Auto-assigned {len(assignments)} patients to clinicians.",
            }
        )


# ── PHC Admin: Facility + Staff management ────────────────────────────────────


class PHCProfileView(APIView):
    permission_classes = [IsAuthenticated, IsHCCAdmin]

    def _get_center(self, user):
        try:
            return user.managed_hcc
        except Exception:
            return None

    @extend_schema(tags=["PHC Admin"], summary="Get own PHC facility profile")
    def get(self, request):
        center = self._get_center(request.user)
        if not center:
            return error_response("No PHC facility linked to your account.", http_status=404)
        return success_response(data=HealthCareCenterSerializer(center).data)

    @extend_schema(
        tags=["PHC Admin"],
        request=HealthCareCenterSerializer,
        summary="Update own PHC facility profile",
        description="Cannot change escalates_to — Platform Admin only.",
    )
    def patch(self, request):
        center = self._get_center(request.user)
        if not center:
            return error_response("No PHC facility linked to your account.", http_status=404)
        # Block HCC Admin from changing escalates_to
        data = {k: v for k, v in request.data.items() if k != "escalates_to"}
        serializer = HealthCareCenterSerializer(center, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="PHC profile updated.")


class PHCStaffListView(APIView):
    permission_classes = [IsAuthenticated, IsHCCAdmin]

    @extend_schema(tags=["PHC Admin"], summary="List PHC staff accounts")
    def get(self, request):
        center = getattr(request.user, "managed_hcc", None)
        if not center:
            return error_response("No PHC facility linked to your account.", http_status=404)
        staff = HCCStaffProfile.objects.filter(hcc=center).select_related("user")
        return success_response(data=HCCStaffProfileSerializer(staff, many=True).data)

    @extend_schema(
        tags=["PHC Admin"],
        request=CreateHCCStaffSerializer,
        summary="Create a PHC staff account",
        description="Creates a new PHC staff account. Returns temp_password that should be shared with the new staff member.",
    )
    def post(self, request):
        center = getattr(request.user, "managed_hcc", None)
        if not center:
            return error_response("No PHC facility linked to your account.", http_status=404)

        serializer = CreateHCCStaffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        temp_password = _generate_temp_password()
        user = User.objects.create_user(
            email=data["email"],
            password=temp_password,
            full_name=data["full_name"],
            role=User.Role.HCC_STAFF,
            is_email_verified=True,
        )
        user.must_change_password = True
        user.save(update_fields=["must_change_password"])

        profile = HCCStaffProfile.objects.create(
            user=user,
            hcc=center,
            staff_role=data["staff_role"],
            employee_id=data.get("employee_id", ""),
        )

        logger.info("PHC Staff created: email=%s by admin=%s", user.email, request.user.email)

        return created_response(
            data={
                **HCCStaffProfileSerializer(profile).data,
                "temp_password": temp_password,
            },
            message=f"PHC staff account created. Share temporary password with {user.email}.",
        )


class PHCStaffDetailView(APIView):
    permission_classes = [IsAuthenticated, IsHCCAdmin]

    def _get_staff(self, pk, admin_user):
        center = getattr(admin_user, "managed_hcc", None)
        if not center:
            return None
        try:
            return HCCStaffProfile.objects.select_related("user").get(pk=pk, hcc=center)
        except HCCStaffProfile.DoesNotExist:
            return None

    @extend_schema(tags=["PHC Admin"], summary="Get PHC staff member detail")
    def get(self, request, pk):
        profile = self._get_staff(pk, request.user)
        if not profile:
            return error_response("Staff member not found.", http_status=404)
        return success_response(data=HCCStaffProfileSerializer(profile).data)

    @extend_schema(
        tags=["PHC Admin"], request=HCCStaffProfileSerializer, summary="Update PHC staff member"
    )
    def patch(self, request, pk):
        profile = self._get_staff(pk, request.user)
        if not profile:
            return error_response("Staff member not found.", http_status=404)
        serializer = HCCStaffProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Staff profile updated.")

    @extend_schema(tags=["PHC Admin"], summary="Deactivate PHC staff account")
    def delete(self, request, pk):
        profile = self._get_staff(pk, request.user)
        if not profile:
            return error_response("Staff member not found.", http_status=404)
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])
        profile.is_active = False
        profile.save(update_fields=["is_active"])
        return success_response(message=f"Staff account for {profile.user.email} deactivated.")


# ── FMC Admin: Facility + Staff management ────────────────────────────────────


class FMCProfileView(APIView):
    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    def _get_center(self, user):
        # For FMC admins, they have managed_fhc directly
        if hasattr(user, "managed_fhc") and user.managed_fhc:
            return user.managed_fhc
        # For FMC staff, check their staff profile
        if hasattr(user, "fhc_staff_profile") and user.fhc_staff_profile:
            return user.fhc_staff_profile.fhc
        return None

    @extend_schema(
        tags=["FMC Admin"],
        summary="Get own FMC facility profile",
        description=(
            "Returns FMC record. FMC Admin can see which PHCs route to this FMC "
            "(referring_phcs) but cannot change those links."
        ),
    )
    def get(self, request):
        center = self._get_center(request.user)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        return success_response(data=FederalHealthCenterSerializer(center).data)

    @extend_schema(
        tags=["FMC Admin"],
        request=FederalHealthCenterSerializer,
        summary="Update own FMC facility profile",
    )
    def patch(self, request):
        center = self._get_center(request.user)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        serializer = FederalHealthCenterSerializer(center, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="FMC profile updated.")


class FMCStaffListView(APIView):
    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(tags=["FMC Admin"], summary="List FMC staff accounts")
    def get(self, request):
        center = _get_user_fhc(request.user)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        staff = FHCStaffProfile.objects.filter(fhc=center).select_related("user")
        return success_response(data=FHCStaffProfileSerializer(staff, many=True).data)

    @extend_schema(
        tags=["FMC Admin"], request=CreateFHCStaffSerializer, summary="Create an FMC staff account"
    )
    def post(self, request):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        serializer = CreateFHCStaffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        temp_password = _generate_temp_password()
        user = User.objects.create_user(
            email=data["email"],
            password=temp_password,
            full_name=data["full_name"],
            role=User.Role.FHC_STAFF,
            is_email_verified=True,
        )
        user.must_change_password = True
        user.save(update_fields=["must_change_password"])

        profile = FHCStaffProfile.objects.create(
            user=user,
            fhc=center,
            staff_role=data["staff_role"],
            employee_id=data.get("employee_id", ""),
        )

        send_staff_credentials_email_task.delay(
            user_name=data["full_name"],
            user_email=data["email"],
            temp_password=temp_password,
            facility_name=center.name,
            role=FHCStaffProfile.StaffRole(data["staff_role"]).label,
            unique_id=user.unique_id,
        )

        return created_response(
            data={
                **FHCStaffProfileSerializer(profile).data,
                "temp_password": temp_password,
            },
            message=f"FMC staff account created for {user.email}. Share the temporary password with the new staff member.",
        )


class FMCStaffDetailView(APIView):
    permission_classes = [IsAuthenticated, IsFHCAdmin]

    def _get_staff(self, pk, admin_user):
        center = getattr(admin_user, "managed_fhc", None)
        if not center:
            return None
        try:
            return FHCStaffProfile.objects.select_related("user").get(pk=pk, fhc=center)
        except FHCStaffProfile.DoesNotExist:
            return None

    @extend_schema(tags=["FMC Admin"], summary="Get FMC staff detail")
    def get(self, request, pk):
        profile = self._get_staff(pk, request.user)
        if not profile:
            return error_response("Staff member not found.", http_status=404)
        return success_response(data=FHCStaffProfileSerializer(profile).data)

    @extend_schema(
        tags=["FMC Admin"], request=FHCStaffProfileSerializer, summary="Update FMC staff member"
    )
    def patch(self, request, pk):
        profile = self._get_staff(pk, request.user)
        if not profile:
            return error_response("Staff member not found.", http_status=404)
        serializer = FHCStaffProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Staff profile updated.")

    @extend_schema(tags=["FMC Admin"], summary="Deactivate FMC staff account")
    def delete(self, request, pk):
        profile = self._get_staff(pk, request.user)
        if not profile:
            return error_response("Staff member not found.", http_status=404)
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])
        profile.is_active = False
        profile.save(update_fields=["is_active"])
        return success_response(message=f"Staff account for {profile.user.email} deactivated.")


# ── FMC Admin: Clinician management ──────────────────────────────────────────


class FMCClinicianListView(APIView):
    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(tags=["FMC Admin"], summary="List clinicians for this FMC")
    def get(self, request):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            # Try staff profile for non-admin staff
            if hasattr(request.user, "fhc_staff_profile") and request.user.fhc_staff_profile:
                center = request.user.fhc_staff_profile.fhc
            else:
                return error_response("No FMC facility linked to your account.", http_status=404)
        clinicians = ClinicianProfile.objects.filter(fhc=center).select_related("user")
        return success_response(
            data=ClinicianProfileSerializer(
                clinicians, many=True, context={"request": request}
            ).data
        )

    @extend_schema(
        tags=["FMC Admin"],
        request=CreateClinicianSerializer,
        summary="Create a clinician account",
        description="Starts unverified. Must verify before clinician can access patient data.",
    )
    def post(self, request):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        serializer = CreateClinicianSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        temp_password = _generate_temp_password()
        user = User.objects.create_user(
            email=data["email"],
            password=temp_password,
            full_name=data["full_name"],
            role=User.Role.CLINICIAN,
            is_email_verified=True,
        )
        user.must_change_password = True
        user.save(update_fields=["must_change_password"])

        profile = ClinicianProfile.objects.create(
            user=user,
            fhc=center,
            specialization=data.get(
                "specialization", ClinicianProfile.Specialization.GENERAL_PRACTICE
            ),
            license_number=data.get("license_number", ""),
            years_of_experience=data.get("years_of_experience", 0),
            bio=data.get("bio", ""),
        )

        # Send email with credentials
        try:
            from apps.accounts.tasks import send_staff_credentials_email_task
            from core.utils.celery_helpers import run_task

            run_task(
                send_staff_credentials_email_task,
                user_name=user.full_name,
                user_email=user.email,
                temp_password=temp_password,
                facility_name=center.name,
                role="Clinician",
                unique_id=user.unique_id,
            )
        except Exception as e:
            logger.warning(f"Failed to send clinician credentials email: {e}")

        return created_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data,
            message=f"Clinician account created for {user.email}. Pending verification.",
        )


class FMCClinicianDetailView(APIView):
    permission_classes = [IsAuthenticated, IsFHCAdmin]

    def _get_clinician(self, pk, admin_user):
        center = getattr(admin_user, "managed_fhc", None)
        if not center:
            return None
        try:
            return ClinicianProfile.objects.select_related("user").get(pk=pk, fhc=center)
        except ClinicianProfile.DoesNotExist:
            return None

    @extend_schema(tags=["FMC Admin"], summary="Get clinician detail")
    def get(self, request, pk):
        profile = self._get_clinician(pk, request.user)
        if not profile:
            return error_response("Clinician not found.", http_status=404)
        return success_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data
        )

    @extend_schema(
        tags=["FMC Admin"],
        request=UpdateClinicianProfileSerializer,
        summary="Update clinician profile",
    )
    def patch(self, request, pk):
        profile = self._get_clinician(pk, request.user)
        if not profile:
            return error_response("Clinician not found.", http_status=404)
        serializer = UpdateClinicianProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data,
            message="Clinician profile updated.",
        )


class FMCVerifyClinicianView(APIView):
    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Admin"],
        summary="Verify a clinician account",
        description="Marks clinician as verified. Clinician receives in-app notification.",
    )
    def post(self, request, pk):
        center = _get_user_fhc(request.user)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=403)

        try:
            profile = ClinicianProfile.objects.select_related("user").get(pk=pk)
        except ClinicianProfile.DoesNotExist:
            return error_response("Clinician not found.", http_status=404)

        # Verify the clinician belongs to this FMC
        if profile.fhc != center:
            return error_response("Clinician not found.", http_status=404)

        if profile.is_verified:
            return error_response("This clinician is already verified.")

        profile.is_verified = True
        profile.verified_at = timezone.now()
        profile.save(update_fields=["is_verified", "verified_at"])
        try:
            from apps.notifications.models import Notification
            from apps.notifications.services import NotificationService

            NotificationService.send(
                recipient=profile.user,
                notification_type=Notification.NotificationType.SYSTEM,
                title="Your clinician account has been verified",
                body=(
                    f"Your account has been verified by {center.name}. "
                    "You can now access your assigned patients."
                ),
                priority=Notification.Priority.HIGH,
                data={"action": "open_clinician_dashboard"},
            )
        except Exception:
            pass
        return success_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data,
            message=f"Dr. {profile.user.full_name} has been verified.",
        )


class FMCDeactivateClinicianView(APIView):
    permission_classes = [IsAuthenticated, IsFHCAdmin]

    @extend_schema(
        tags=["FMC Admin"],
        summary="Deactivate a clinician account",
        description="Deactivates clinician account. They cannot log in or access patients.",
    )
    def post(self, request, pk):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=403)

        try:
            profile = ClinicianProfile.objects.select_related("user").get(pk=pk, fhc=center)
        except ClinicianProfile.DoesNotExist:
            return error_response("Clinician not found.", http_status=404)

        # Deactivate the user account
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])

        # Send notification
        try:
            from apps.notifications.models import Notification
            from apps.notifications.services import NotificationService

            NotificationService.send(
                recipient=profile.user,
                notification_type=Notification.NotificationType.SYSTEM,
                title="Your clinician account has been deactivated",
                body=(
                    f"Your account at {center.name} has been deactivated. "
                    "Please contact your administrator for more information."
                ),
                priority=Notification.Priority.HIGH,
            )
        except Exception:
            pass

        return success_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data,
            message=f"Dr. {profile.user.full_name} has been deactivated.",
        )


class FMCActivateClinicianView(APIView):
    permission_classes = [IsAuthenticated, IsFHCAdmin]

    @extend_schema(
        tags=["FMC Admin"],
        summary="Reactivate a clinician account",
        description="Reactivates a previously deactivated clinician account.",
    )
    def post(self, request, pk):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=403)

        try:
            profile = ClinicianProfile.objects.select_related("user").get(pk=pk, fhc=center)
        except ClinicianProfile.DoesNotExist:
            return error_response("Clinician not found.", http_status=404)

        # Reactivate the user account
        profile.user.is_active = True
        profile.user.save(update_fields=["is_active"])

        # Send notification
        try:
            from apps.notifications.models import Notification
            from apps.notifications.services import NotificationService

            NotificationService.send(
                recipient=profile.user,
                notification_type=Notification.NotificationType.SYSTEM,
                title="Your clinician account has been reactivated",
                body=(
                    f"Your account at {center.name} has been reactivated. You can now log in again."
                ),
                priority=Notification.Priority.HIGH,
            )
        except Exception:
            pass

        return success_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data,
            message=f"Dr. {profile.user.full_name} has been reactivated.",
        )


# ── FMC Portal: Case Queue ────────────────────────────────────────────────────


class FMCCaseListView(APIView):
    """
    GET /api/v1/centers/fmc/cases/
    FMC staff and admin see their patient case queue (screen FMC2).
    Optional filters: ?status=open&condition=pcos&severity=severe
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get FMC patient case queue (FMC2)",
        description=(
            "Returns active patient cases for this FMC.\n\n"
            "**Filters:** `?status=open` | `?condition=pcos` | `?severity=severe`\n\n"
            "Default: returns all non-discharged cases."
        ),
    )
    def get(self, request):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)

        qs = PatientCase.objects.filter(fhc=fhc).select_related(
            "patient", "clinician__user", "phc_record", "phc_record__hcc"
        )
        status = request.query_params.get("status")
        condition = request.query_params.get("condition")
        severity = request.query_params.get("severity")
        if status:
            qs = qs.filter(status=status)
        if condition:
            qs = qs.filter(condition=condition)
        if severity:
            qs = qs.filter(severity=severity)
        if not status:
            qs = qs.exclude(status=PatientCase.CaseStatus.DISCHARGED)

        return success_response(data=[_serialize_case(c) for c in qs.order_by("opened_at")])


class FMCCaseDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(tags=["FMC Portal"], summary="Get patient case detail (FMC3)")
    def get(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.select_related("patient", "fhc", "clinician__user").get(
                pk=pk, fhc=fhc
            )
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)
        return success_response(data=_serialize_case(case))


class FMCAssignClinicianView(APIView):
    """
    POST /api/v1/centers/fmc/cases/<uuid:pk>/assign/

    FMC staff assigns a clinician to a case.
    Clinician and patient both receive notifications.
    Body: { "clinician_id": "<uuid>" }
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Assign clinician to case (FMC4)",
        description=(
            "Assigns a verified clinician to an open case.\n\n"
            "Both the clinician and the patient are notified immediately.\n\n"
            'Body: `{ "clinician_id": "<uuid>" }`'
        ),
    )
    def post(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.select_related("patient", "fhc").get(pk=pk, fhc=fhc)
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)
        if not case.is_open():
            return error_response(
                f"Cannot assign a clinician to a case with status '{case.status}'."
            )
        clinician_id = request.data.get("clinician_id")
        if not clinician_id:
            return error_response("clinician_id is required.")
        try:
            clinician = ClinicianProfile.objects.select_related("user").get(
                pk=clinician_id,
                fhc=fhc,
                is_verified=True,
                user__is_active=True,
            )
        except ClinicianProfile.DoesNotExist:
            return error_response(
                "Clinician not found. Ensure they are verified and affiliated with this FMC.",
                http_status=404,
            )

        case.assign_clinician(clinician)

        # Notify clinician
        try:
            from apps.notifications.models import Notification
            from apps.notifications.services import NotificationService

            NotificationService.send(
                recipient=clinician.user,
                notification_type=Notification.NotificationType.SYSTEM,
                title="New patient assigned to you",
                body=(
                    f"You have been assigned a {case.get_severity_display()} "
                    f"{case.get_condition_display()} case for "
                    f"{case.patient.full_name} at {fhc.name}."
                ),
                priority=Notification.Priority.HIGH,
                data={
                    "case_id": str(case.id),
                    "patient_id": str(case.patient.id),
                    "condition": case.condition,
                    "severity": case.severity,
                    "action": "open_clinician_dashboard",
                },
            )
            # Notify patient
            NotificationService.send(
                recipient=case.patient,
                notification_type=Notification.NotificationType.SYSTEM,
                title="A doctor has been assigned to your case",
                body=(
                    f"Dr. {clinician.user.full_name} at {fhc.name} has been "
                    f"assigned to your {case.get_condition_display()} case."
                ),
                priority=Notification.Priority.MEDIUM,
                data={
                    "case_id": str(case.id),
                    "clinician_name": clinician.user.full_name,
                    "fmc_name": fhc.name,
                    "action": "open_risk_details",
                },
            )
        except Exception:
            pass

        return success_response(
            data=_serialize_case(case),
            message=f"Dr. {clinician.user.full_name} assigned. Clinician and patient notified.",
        )


class FMCDischargeCaseView(APIView):
    """
    POST /api/v1/centers/fmc/cases/<uuid:pk>/discharge/

    FMC staff or admin discharges a case (screen FMC8).
    Patient is notified. PHC is notified to resume monitoring.
    Body (optional): { "closing_score": 35, "notes": "..." }
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Discharge patient case (FMC8)",
        description=(
            "Closes a patient case as DISCHARGED.\n\n"
            "- Patient is notified\n"
            "- PHC is notified to resume monitoring\n"
            "- Patient can now change their PHC freely\n\n"
            'Body (optional): `{ "closing_score": 35, "notes": "..." }`'
        ),
    )
    def post(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.select_related("patient", "clinician__user").get(
                pk=pk, fhc=fhc
            )
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)
        if not case.is_open():
            return error_response(f"Case is already closed (status: {case.status}).")

        closing_score = request.data.get("closing_score")
        notes = request.data.get("notes", "")

        if notes:
            case.fmc_notes = (case.fmc_notes + "\n\n" + notes).strip()
            case.save(update_fields=["fmc_notes"])

        case.close(
            status=PatientCase.CaseStatus.DISCHARGED,
            closing_score=int(closing_score) if closing_score else None,
        )

        # Update linked PHCPatientRecord if it exists
        try:
            if hasattr(case, "phc_record") and case.phc_record:
                phc_record = case.phc_record
                phc_record.status = PHCPatientRecord.RecordStatus.DISCHARGED
                phc_record.save(update_fields=["status"])
        except Exception:
            pass

        clinician_name = (
            f"Dr. {case.clinician.user.full_name}" if case.clinician else "your care team"
        )

        # Notify patient
        try:
            from apps.notifications.models import Notification
            from apps.notifications.services import NotificationService

            NotificationService.send(
                recipient=case.patient,
                notification_type=Notification.NotificationType.SYSTEM,
                title="Your case has been discharged",
                body=(
                    f"Your {case.get_condition_display()} case at {fhc.name} has been "
                    f"discharged by {clinician_name}. Continue your daily check-ins."
                ),
                priority=Notification.Priority.MEDIUM,
                data={
                    "case_id": str(case.id),
                    "condition": case.condition,
                    "closing_score": closing_score,
                    "action": "open_risk_details",
                },
            )

            # Notify PHC to resume monitoring
            patient_phc = _get_patient_phc_for_discharge(case.patient)
            if patient_phc and patient_phc.admin_user:
                NotificationService.send(
                    recipient=patient_phc.admin_user,
                    notification_type=Notification.NotificationType.SYSTEM,
                    title="Patient discharged from FMC",
                    body=(
                        f"Patient {case.patient.full_name} has been discharged from "
                        f"{fhc.name}. They are back under PHC-level monitoring."
                    ),
                    priority=Notification.Priority.MEDIUM,
                    data={
                        "case_id": str(case.id),
                        "patient_id": str(case.patient.id),
                        "fmc_name": fhc.name,
                        "action": "open_phc_queue",
                    },
                )
                # Also notify PHC staff
                for staff_profile in patient_phc.get_active_staff():
                    NotificationService.send(
                        recipient=staff_profile.user,
                        notification_type=Notification.NotificationType.SYSTEM,
                        title="Patient returned to PHC monitoring",
                        body=(
                            f"{case.patient.full_name} discharged from {fhc.name}. "
                            "Please resume monitoring."
                        ),
                        priority=Notification.Priority.MEDIUM,
                        data={
                            "case_id": str(case.id),
                            "patient_id": str(case.patient.id),
                            "action": "open_phc_queue",
                        },
                    )
        except Exception:
            pass

        return success_response(
            data=_serialize_case(case),
            message="Case discharged. Patient and PHC have been notified.",
        )


# ── Clinician Portal: Assigned Cases ─────────────────────────────────────────


class ClinicianCaseListView(APIView):
    """
    GET /api/v1/centers/clinician/cases/

    Clinician sees all their assigned patient cases (screen CL2).
    Optional filters: ?status=assigned&condition=pcos
    """

    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(
        tags=["Clinician Portal"],
        summary="List clinician's assigned patient cases (CL2)",
        description=(
            "Returns all cases assigned to the authenticated clinician.\n\n"
            "**Filters:** `?status=assigned` | `?condition=pcos`\n\n"
            "Default: returns all non-discharged cases sorted by severity."
        ),
    )
    def get(self, request):
        try:
            clinician = request.user.clinician_profile
        except Exception:
            return error_response("Clinician profile not found.", http_status=404)

        if not clinician.is_verified:
            return error_response(
                "Your account is not yet verified. Please contact your FMC administrator.",
                http_status=403,
            )

        qs = PatientCase.objects.filter(clinician=clinician).select_related("patient", "fhc")

        status = request.query_params.get("status")
        condition = request.query_params.get("condition")
        if status:
            qs = qs.filter(status=status)
        if condition:
            qs = qs.filter(condition=condition)
        if not status:
            qs = qs.exclude(status=PatientCase.CaseStatus.DISCHARGED)

        return success_response(data=[_serialize_case(c) for c in qs.order_by("opened_at")])


class ClinicianCaseDetailView(APIView):
    """
    GET /api/v1/centers/clinician/cases/<uuid:pk>/
    Clinician views full detail of one of their assigned cases (screen CL3).
    """

    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(
        tags=["Clinician Portal"],
        summary="Get assigned patient case detail (CL3)",
    )
    def get(self, request, pk):
        try:
            clinician = request.user.clinician_profile
        except Exception:
            return error_response("Clinician profile not found.", http_status=404)
        try:
            case = PatientCase.objects.select_related("patient", "fhc", "clinician__user").get(
                pk=pk, clinician=clinician
            )
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)
        return success_response(data=_serialize_case(case))


# ── Clinician Profile ─────────────────────────────────────────────────────────


class ClinicianProfileView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    def _get_profile(self, user):
        try:
            return ClinicianProfile.objects.select_related("fhc").get(user=user)
        except ClinicianProfile.DoesNotExist:
            return None

    @extend_schema(tags=["Clinician Portal"], summary="Get own clinician profile (CL8)")
    def get(self, request):
        profile = self._get_profile(request.user)
        if not profile:
            return error_response("Profile not found. Contact your FMC admin.", http_status=404)
        return success_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data
        )

    @extend_schema(
        tags=["Clinician Portal"],
        request=UpdateClinicianProfileSerializer,
        summary="Update own clinician profile (CL8)",
    )
    def patch(self, request):
        profile = self._get_profile(request.user)
        if not profile:
            return error_response("Profile not found. Contact your FMC admin.", http_status=404)
        serializer = UpdateClinicianProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data,
            message="Profile updated.",
        )


class ClinicianOnboardingView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(
        tags=["Clinician Portal"],
        request=ClinicianOnboardingSerializer,
        summary="Complete clinician onboarding",
    )
    def post(self, request):
        profile = request.user.clinician_profile
        if not profile:
            return error_response("Profile not found. Contact your FMC admin.", http_status=404)

        if profile.onboarded:
            return error_response("Already onboarded.", http_status=400)

        serializer = ClinicianOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        profile.specialization = data["specialization"]
        profile.downstream_expertise = data["downstream_expertise"]
        profile.license_number = data.get("license_number", "")
        profile.years_of_experience = data.get("years_of_experience", 0)
        profile.bio = data.get("bio", "")
        profile.onboarded = True
        profile.onboarded_at = timezone.now()
        profile.save()

        return success_response(
            data=ClinicianProfileSerializer(profile, context={"request": request}).data,
            message="Onboarding completed.",
        )


# ── Clinician Portal: Treatment Plans ──────────────────────────────────────────────


class ClinicianTreatmentPlanView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    def _get_clinician_profile(self, user):
        try:
            return ClinicianProfile.objects.get(user=user)
        except ClinicianProfile.DoesNotExist:
            return None

    @extend_schema(tags=["Clinician Portal"], summary="List treatment plans (CL4)")
    def get(self, request):
        profile = self._get_clinician_profile(request.user)
        if not profile:
            return error_response("Clinician profile not found.", http_status=404)

        plans = TreatmentPlan.objects.filter(clinician=profile).select_related(
            "case", "case__patient"
        )
        return success_response(data=TreatmentPlanSerializer(plans, many=True).data)

    @extend_schema(
        tags=["Clinician Portal"],
        request=TreatmentPlanSerializer,
        summary="Create treatment plan (CL4)",
    )
    def post(self, request):
        profile = self._get_clinician_profile(request.user)
        if not profile:
            return error_response("Clinician profile not found.", http_status=404)

        case_id = request.data.get("case")
        if not case_id:
            return error_response("Case ID is required.")

        try:
            case = PatientCase.objects.get(pk=case_id)
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)

        if case.clinician != profile:
            return error_response("This case is not assigned to you.", http_status=403)

        serializer = TreatmentPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save(clinician=profile, case=case)
        return created_response(
            data=TreatmentPlanSerializer(plan).data, message="Treatment plan created."
        )


class ClinicianTreatmentPlanDetailView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(tags=["Clinician Portal"], summary="Get treatment plan detail (CL4)")
    def get(self, request, pk):
        profile = getattr(request.user, "clinician_profile", None)
        if not profile:
            return error_response("Profile not found.", http_status=404)

        try:
            plan = TreatmentPlan.objects.select_related("case", "case__patient").get(
                pk=pk, clinician=profile
            )
        except TreatmentPlan.DoesNotExist:
            return error_response("Treatment plan not found.", http_status=404)

        return success_response(data=TreatmentPlanSerializer(plan).data)

    @extend_schema(
        tags=["Clinician Portal"],
        request=TreatmentPlanSerializer,
        summary="Update treatment plan (CL4)",
    )
    def patch(self, request, pk):
        profile = getattr(request.user, "clinician_profile", None)
        if not profile:
            return error_response("Profile not found.", http_status=404)

        try:
            plan = TreatmentPlan.objects.get(pk=pk, clinician=profile)
        except TreatmentPlan.DoesNotExist:
            return error_response("Treatment plan not found.", http_status=404)

        serializer = TreatmentPlanSerializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=TreatmentPlanSerializer(plan).data, message="Treatment plan updated."
        )


# ── Clinician Portal: Prescriptions ───────────────────────────────────────────


class ClinicianPrescriptionView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(tags=["Clinician Portal"], summary="Create/list prescriptions (CL5)")
    def get(self, request):
        profile = getattr(request.user, "clinician_profile", None)
        if not profile:
            return error_response("Profile not found.", http_status=404)

        prescriptions = Prescription.objects.filter(clinician=profile).select_related("patient")
        data = [
            {
                "id": str(p.id),
                "patient_id": str(p.patient_id),
                "medications": p.medications,
                "is_active": p.is_active,
                "created_at": p.created_at.isoformat(),
            }
            for p in prescriptions
        ]
        return success_response(data=data)

    def post(self, request):
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService

        profile = getattr(request.user, "clinician_profile", None)
        if not profile:
            return error_response("Profile not found.", http_status=404)

        patient_id = request.data.get("patient_id")
        medications = request.data.get("medications", [])

        if not patient_id:
            return error_response("Patient ID is required.")

        try:
            patient = User.objects.get(pk=patient_id)
        except User.DoesNotExist:
            return error_response("Patient not found.", http_status=404)

        prescription = Prescription.objects.create(
            clinician=profile, patient=patient, medications=medications
        )

        try:
            NotificationService.send(
                recipient=patient,
                notification_type=Notification.NotificationType.SYSTEM,
                title="New Prescription",
                body=f"Dr. {request.user.full_name} has prescribed medications for you.",
                priority=Notification.Priority.HIGH,
            )
        except Exception:
            pass

        return created_response(
            data={
                "id": str(prescription.id),
                "message": "Prescription created and patient notified.",
            }
        )


class ClinicianPrescriptionDetailView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(tags=["Clinician Portal"], summary="Update prescription (CL5)")
    def patch(self, request, pk):
        profile = getattr(request.user, "clinician_profile", None)
        if not profile:
            return error_response("Profile not found.", http_status=404)

        try:
            prescription = Prescription.objects.get(pk=pk, clinician=profile)
        except Prescription.DoesNotExist:
            return error_response("Prescription not found.", http_status=404)

        if "medications" in request.data:
            prescription.medications = request.data["medications"]
        if "is_active" in request.data:
            prescription.is_active = request.data["is_active"]
        prescription.save()

        return success_response(
            data={"id": str(prescription.id), "message": "Prescription updated."}
        )


# ── Clinician Portal: Communication ───────────────────────────────────────────


class ClinicianMessageView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(tags=["Clinician Portal"], summary="Send patient message (CL6)")
    def post(self, request, patient_id):
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService

        try:
            patient = User.objects.get(pk=patient_id)
        except User.DoesNotExist:
            return error_response("Patient not found.", http_status=404)

        message_type = request.data.get("message_type", "CLINICAL_UPDATE")
        body = request.data.get("body", "")

        if not body:
            return error_response("Message body is required.")

        try:
            NotificationService.send(
                recipient=patient,
                notification_type=Notification.NotificationType.MESSAGE,
                title=f"Message from Dr. {request.user.full_name}",
                body=body,
                priority=Notification.Priority.MEDIUM,
                data={"message_type": message_type, "sender": request.user.full_name},
            )
        except Exception:
            pass

        return success_response(message="Message sent to patient.")


class ClinicianAppointmentView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(tags=["Clinician Portal"], summary="Book patient appointment (CL6)")
    def post(self, request, patient_id):
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService

        try:
            patient = User.objects.get(pk=patient_id)
        except User.DoesNotExist:
            return error_response("Patient not found.", http_status=404)

        appointment_date = request.data.get("appointment_date")
        appointment_type = request.data.get("appointment_type", "FOLLOW_UP")

        if not appointment_date:
            return error_response("Appointment date is required.")

        try:
            NotificationService.send(
                recipient=patient,
                notification_type=Notification.NotificationType.APPOINTMENT,
                title="Appointment Booked",
                body=f"Dr. {request.user.full_name} has booked an appointment: {appointment_type} on {appointment_date}",
                priority=Notification.Priority.HIGH,
                data={"appointment_date": appointment_date, "appointment_type": appointment_type},
            )
        except Exception:
            pass

        return success_response(message="Appointment booked.")


# ── Clinician Portal: Letters ───────────────────────────────────────────────────


class ClinicianLetterView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(tags=["Clinician Portal"], summary="Generate clinical letter (CL6)")
    def post(self, request, patient_id):
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService

        try:
            patient = User.objects.get(pk=patient_id)
        except User.DoesNotExist:
            return error_response("Patient not found.", http_status=404)

        letter_type = request.data.get("letter_type", "TREATMENT_SUMMARY")
        content = request.data.get("content", "")

        try:
            NotificationService.send(
                recipient=patient,
                notification_type=Notification.NotificationType.LETTER,
                title=f"Clinical Letter - {letter_type.replace('_', ' ').title()}",
                body=f"Dr. {request.user.full_name} has sent you a clinical letter.",
                priority=Notification.Priority.MEDIUM,
                data={"letter_type": letter_type, "content": content[:500] if content else ""},
            )
        except Exception:
            pass

        return success_response(message="Clinical letter generated and sent.")


# ── Clinician Portal: Analytics ────────────────────────────────────────────────


class ClinicianAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(tags=["Clinician Portal"], summary="Get clinician analytics (CL7)")
    def get(self, request):
        from datetime import timedelta
        from django.utils import timezone

        profile = getattr(request.user, "clinician_profile", None)
        if not profile:
            return error_response("Profile not found.", http_status=404)

        range_param = request.query_params.get("range", "30d")

        if range_param == "7d":
            start_date = timezone.now() - timedelta(days=7)
        elif range_param == "90d":
            start_date = timezone.now() - timedelta(days=90)
        else:
            start_date = timezone.now() - timedelta(days=30)

        assigned_cases = PatientCase.objects.filter(clinician=profile, assigned_at__gte=start_date)
        active_cases = assigned_cases.exclude(status=PatientCase.CaseStatus.DISCHARGED)
        resolved_cases = assigned_cases.filter(status=PatientCase.CaseStatus.DISCHARGED)

        avg_treatment_days = 0
        if resolved_cases.exists():
            resolved_with_dates = resolved_cases.exclude(
                assigned_at__isnull=True, closed_at__isnull=True
            )
            if resolved_with_dates.exists():
                total_days = sum(
                    (c.closed_at - c.assigned_at).days
                    for c in resolved_with_dates
                    if c.closed_at and c.assigned_at
                )
                avg_treatment_days = total_days / resolved_with_dates.count()

        return success_response(
            data={
                "total_assigned": assigned_cases.count(),
                "active_cases": active_cases.count(),
                "resolved_cases": resolved_cases.count(),
                "avg_treatment_duration_days": round(avg_treatment_days, 1),
                "condition_distribution": {"pcos": 0, "hormonal": 0, "metabolic": 0},
                "outcomes": {
                    "resolved": resolved_cases.count(),
                    "under_treatment": active_cases.count(),
                    "referred_on": 0,
                },
            }
        )


class ClinicianNotificationsListView(APIView):
    permission_classes = [IsAuthenticated, IsClinician]

    @extend_schema(tags=["Clinician Portal"], summary="List notifications/conversations")
    def get(self, request):
        from apps.notifications.models import Notification

        qs = Notification.objects.filter(
            recipient=request.user, notification_type__in=["clinician_msg", "message"]
        ).order_by("-created_at")[:50]

        conversations = {}
        for n in qs:
            sender_id = n.data.get("sender_id", n.sender_id if hasattr(n, "sender_id") else None)
            if not sender_id:
                continue
            if sender_id not in conversations:
                conversations[sender_id] = {
                    "id": sender_id,
                    "patient": {"id": sender_id, "full_name": n.data.get("sender", "Patient")},
                    "last_message": n.body[:100],
                    "last_message_at": n.created_at.isoformat(),
                    "unread_count": 0,
                }
            if not n.is_read:
                conversations[sender_id]["unread_count"] += 1

        return success_response(data=list(conversations.values()))

    @extend_schema(tags=["Clinician Portal"], summary="Mark conversation as read")
    def patch(self, request, pk):
        from apps.notifications.models import Notification

        notifications = Notification.objects.filter(
            recipient=request.user,
            data__sender_id=pk,
            is_read=False,
        )
        for n in notifications:
            n.mark_read()

        return success_response(message="Marked as read.")

    @extend_schema(tags=["Clinician Portal"], summary="Archive conversation")
    def post(self, request, pk):
        from apps.notifications.models import Notification

        notifications = Notification.objects.filter(
            recipient=request.user,
            data__sender_id=pk,
        )
        notifications.update(is_archived=True)

        return success_response(message="Archived.")

    def delete(self, request, pk):
        from apps.notifications.models import Notification

        Notification.objects.filter(
            recipient=request.user,
            data__sender_id=pk,
        ).delete()

        return success_response(message="Deleted.")


# ── Patient: Change Requests ──────────────────────────────────────────────────


class ChangeRequestListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Patient Portal"], summary="List own change requests")
    def get(self, request):
        requests = ChangeRequest.objects.filter(patient=request.user)
        return success_response(
            data=ChangeRequestSerializer(requests, many=True, context={"request": request}).data
        )

    @extend_schema(
        tags=["Patient Portal"],
        summary="Submit a change request",
        description=(
            "Submit a request to change your home PHC or report an issue.\n\n"
            "**CHANGE_PHC:** Include `requested_hcc` UUID.\n"
            "**REPORT_ISSUE / OTHER:** Just include `description`."
        ),
    )
    def post(self, request):
        serializer = ChangeRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        change_request = serializer.save()
        return created_response(
            data=ChangeRequestSerializer(change_request, context={"request": request}).data,
            message="Request submitted. We will notify you when it is reviewed.",
        )


class ChangeRequestDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Patient Portal"], summary="Get change request detail")
    def get(self, request, pk):
        try:
            change_request = ChangeRequest.objects.get(pk=pk, patient=request.user)
        except ChangeRequest.DoesNotExist:
            return error_response("Request not found.", http_status=404)
        return success_response(
            data=ChangeRequestSerializer(change_request, context={"request": request}).data
        )


# ── Platform Admin: Full center management ────────────────────────────────────


class HCCAdminListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(tags=["Platform Admin — Centers"], summary="[Platform Admin] List all PHCs")
    def get(self, request):
        centers = HealthCareCenter.objects.all().order_by("state", "name")
        results = [{
            "id": str(c.id),
            "name": c.name,
            "address": c.address,
            "state": c.state,
            "lga": c.lga,
            "phone": c.phone,
            "email": c.email,
            "status": c.status,
            "tier": "PHC",
        } for c in centers]
        return success_response(data={
            "results": results,
            "count": len(results)
        })


class CentersAdminListAllView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(tags=["Platform Admin — Centers"], summary="[Platform Admin] List ALL centers (PHC, FMC, etc)")
    def get(self, request):
        results = []
        tier = request.query_params.get("tier", "").lower()

        if not tier or tier == "phc":
            for c in HealthCareCenter.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": c.lga,
                    "zone": "",
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "PHC",
                    "escalates_to": str(c.escalates_to_state_hospital_id) if c.escalates_to_state_hospital_id else "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        if not tier or tier == "fmc":
            for c in FederalHealthCenter.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": "",
                    "zone": c.zone,
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "FMC",
                    "escalates_to": str(c.escalates_to_state_teaching_id) if c.escalates_to_state_teaching_id else "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        if not tier or tier == "sth":
            for c in StateHospital.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": c.lga,
                    "zone": c.zone,
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "STH",
                    "escalates_to": str(c.escalates_to_state_teaching_id) if c.escalates_to_state_teaching_id else "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        if not tier or tier == "stth":
            for c in StateTeachingHospital.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": "",
                    "zone": c.zone,
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "STTH",
                    "escalates_to": str(c.escalates_to_fmc_id) if c.escalates_to_fmc_id else "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        if not tier or tier == "fth":
            for c in FederalTeachingHospital.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": "",
                    "zone": c.zone,
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "FTH",
                    "escalates_to": "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        if not tier or tier == "hmo":
            for c in HealthInsuranceOrganization.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": "",
                    "zone": c.zone,
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "HMO",
                    "license_number": c.license_number,
                    "escalates_to": "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        if not tier or tier == "cln":
            for c in Clinic.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": c.lga,
                    "zone": c.zone,
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "CLN",
                    "escalates_to": "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        if not tier or tier == "pvt":
            for c in PrivateHospital.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": c.lga,
                    "zone": c.zone,
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "PVT",
                    "escalates_to": "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        if not tier or tier == "ptth":
            for c in PrivateTeachingHospital.objects.all().order_by("state", "name"):
                results.append({
                    "id": str(c.id),
                    "code": c.code,
                    "name": c.name,
                    "address": c.address,
                    "state": c.state,
                    "lga": "",
                    "zone": c.zone,
                    "phone": c.phone,
                    "email": c.email,
                    "status": c.status,
                    "tier": "PTTH",
                    "escalates_to": "",
                    "admin_user": c.admin_user.full_name if c.admin_user else "",
                    "admin_email": c.admin_user.email if c.admin_user else "",
                })

        return success_response(data={
            "results": results,
            "count": len(results)
        })

    @extend_schema(
        tags=["Platform Admin — Centers"],
        request=HealthCareCenterSerializer,
        summary="[Platform Admin] Create a new facility",
        description="Create a new facility of any type (PHC, FMC, STH, etc.)",
    )
    def post(self, request):
        data = request.data
        tier = data.get("tier", "PHC").upper()
        
        # Get country if provided
        country = None
        if data.get("country"):
            try:
                country = Country.objects.get(pk=data.get("country"))
            except Country.DoesNotExist:
                pass

        facility_data = {
            "name": data.get("name"),
            "code": data.get("code"),
            "address": data.get("address", ""),
            "state": data.get("state", ""),
            "lga": data.get("lga", ""),
            "zone": data.get("zone", ""),
            "phone": data.get("phone", ""),
            "email": data.get("email", ""),
            "status": data.get("status", "active"),
            "facility_type": data.get("facility_type", "public"),
            "country": country,
        }

        if tier == "PHC":
            facility = HealthCareCenter.objects.create(**facility_data)
        elif tier == "FMC":
            facility = FederalHealthCenter.objects.create(**facility_data)
        elif tier in ("STH", "STGH"):
            facility = StateHospital.objects.create(**facility_data)
        elif tier == "STTH":
            facility = StateTeachingHospital.objects.create(**facility_data)
        elif tier == "FTH":
            facility = FederalTeachingHospital.objects.create(**facility_data)
        elif tier == "HMO":
            facility_data["license_number"] = data.get("license_number", "")
            facility = HealthInsuranceOrganization.objects.create(**facility_data)
        elif tier == "CLN":
            facility = Clinic.objects.create(**facility_data)
        elif tier == "PVT":
            facility = PrivateHospital.objects.create(**facility_data)
        elif tier == "PTTH":
            facility = PrivateTeachingHospital.objects.create(**facility_data)
        else:
            return error_response(f"Invalid facility tier: {tier}", http_status=400)

        return created_response(
            data={"id": str(facility.id), "name": facility.name},
            message=f"{tier} '{facility.name}' created successfully.",
        )


class CentersAdminDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def _get_facility(self, facility_id: str, tier: str):
        """Get facility by ID and tier."""
        tier = tier.upper()
        try:
            if tier == "PHC":
                return HealthCareCenter.objects.get(pk=facility_id), "PHC"
            elif tier == "FMC":
                return FederalHealthCenter.objects.get(pk=facility_id), "FMC"
            elif tier in ("STH", "STGH"):
                return StateHospital.objects.get(pk=facility_id), "STH"
            elif tier == "STTH":
                return StateTeachingHospital.objects.get(pk=facility_id), "STTH"
            elif tier == "FTH":
                return FederalTeachingHospital.objects.get(pk=facility_id), "FTH"
            elif tier == "HMO":
                return HealthInsuranceOrganization.objects.get(pk=facility_id), "HMO"
            elif tier == "CLN":
                return Clinic.objects.get(pk=facility_id), "CLN"
            elif tier == "PVT":
                return PrivateHospital.objects.get(pk=facility_id), "PVT"
            elif tier == "PTTH":
                return PrivateTeachingHospital.objects.get(pk=facility_id), "PTTH"
        except (
            HealthCareCenter.DoesNotExist,
            FederalHealthCenter.DoesNotExist,
            StateHospital.DoesNotExist,
            StateTeachingHospital.DoesNotExist,
            FederalTeachingHospital.DoesNotExist,
            HealthInsuranceOrganization.DoesNotExist,
            Clinic.DoesNotExist,
            PrivateHospital.DoesNotExist,
            PrivateTeachingHospital.DoesNotExist,
        ):
            return None, tier
        return None, tier

    def _get_role_for_tier(self, tier: str):
        """Get the appropriate admin role for a facility tier."""
        role_map = {
            "PHC": "hcc_admin",
            "FMC": "fhc_admin",
            "STH": "sth_admin",
            "STTH": "stth_admin",
            "FTH": "fth_admin",
            "HMO": "hmo_admin",
            "CLN": "clinic_admin",
            "PVT": "pvt_admin",
            "PTTH": "ptth_admin",
        }
        return role_map.get(tier, "admin")

    @extend_schema(
        tags=["Platform Admin — Centers"],
        summary="[Platform Admin] Get facility detail",
    )
    def get(self, request, pk):
        tier = request.query_params.get("tier", "PHC").upper()
        facility, found_tier = self._get_facility(pk, tier)
        if not facility:
            return error_response(f"Facility not found.", http_status=404)
        
        # Build response based on tier
        data = {
            "id": str(facility.id),
            "code": facility.code,
            "name": facility.name,
            "address": facility.address,
            "state": facility.state,
            "lga": getattr(facility, "lga", ""),
            "zone": getattr(facility, "zone", ""),
            "phone": facility.phone,
            "email": facility.email,
            "status": facility.status,
            "tier": found_tier,
            "facility_type": getattr(facility, "facility_type", "public"),
            "admin_user": facility.admin_user.full_name if facility.admin_user else "",
            "admin_email": facility.admin_user.email if facility.admin_user else "",
            "admin_user_id": str(facility.admin_user.id) if facility.admin_user else None,
        }
        
        # Add escalation fields based on tier
        if found_tier == "PHC":
            data["escalates_to"] = str(facility.escalates_to_state_hospital_id) if facility.escalates_to_state_hospital_id else ""
            data["escalates_to_name"] = facility.escalates_to_state_hospital.name if facility.escalates_to_state_hospital else ""
        elif found_tier == "FMC":
            data["escalates_to_state_teaching"] = str(facility.escalates_to_state_teaching_id) if facility.escalates_to_state_teaching_id else ""
            data["escalates_to_federal_teaching"] = str(facility.escalates_to_federal_teaching_id) if facility.escalates_to_federal_teaching_id else ""
            data["escalates_to_state_teaching_name"] = facility.escalates_to_state_teaching.name if facility.escalates_to_state_teaching else ""
            data["escalates_to_federal_teaching_name"] = facility.escalates_to_federal_teaching.name if facility.escalates_to_federal_teaching else ""
        elif found_tier == "STH":
            data["escalates_to_state_teaching"] = str(facility.escalates_to_state_teaching_id) if facility.escalates_to_state_teaching_id else ""
            data["escalates_to_state_teaching_name"] = facility.escalates_to_state_teaching.name if facility.escalates_to_state_teaching else ""
        elif found_tier == "STTH":
            data["escalates_to_fmc"] = str(facility.escalates_to_fmc_id) if facility.escalates_to_fmc_id else ""
            data["escalates_to_federal_teaching"] = str(facility.escalates_to_federal_teaching_id) if facility.escalates_to_federal_teaching_id else ""
            data["escalates_to_fmc_name"] = facility.escalates_to_fmc.name if facility.escalates_to_fmc else ""
            data["escalates_to_federal_teaching_name"] = facility.escalates_to_federal_teaching.name if facility.escalates_to_federal_teaching else ""
        
        if found_tier == "HMO":
            data["license_number"] = getattr(facility, "license_number", "")
        
        return success_response(data=data)

    @extend_schema(
        tags=["Platform Admin — Centers"],
        summary="[Platform Admin] Update facility",
        description="Update facility details. Use admin_email to assign an existing user as admin.",
    )
    def patch(self, request, pk):
        tier = request.query_params.get("tier", "PHC").upper()
        facility, found_tier = self._get_facility(pk, tier)
        if not facility:
            return error_response("Facility not found.", http_status=404)
        
        data = request.data
        User = get_user_model()
        
        # Track if admin is being changed
        old_admin_email = facility.admin_user.email if facility.admin_user else None
        new_admin_email = data.get("admin_email")
        
        # Update basic fields
        if "name" in data:
            facility.name = data["name"]
        if "address" in data:
            facility.address = data["address"]
        if "phone" in data:
            facility.phone = data["phone"]
        if "email" in data:
            facility.email = data["email"]
        if "status" in data:
            facility.status = data["status"]
        if "state" in data:
            facility.state = data["state"]
        if "lga" in data:
            facility.lga = data.get("lga", "")
        if "zone" in data:
            facility.zone = data.get("zone", "")
        
        # Update escalation fields based on tier
        if found_tier == "PHC" and "escalates_to" in data:
            if data["escalates_to"]:
                try:
                    facility.escalates_to_state_hospital_id = data["escalates_to"]
                except:
                    facility.escalates_to_state_hospital = None
            else:
                facility.escalates_to_state_hospital = None
        
        # Handle admin user assignment
        if new_admin_email:
            try:
                user = User.objects.get(email__iexact=new_admin_email)
                facility.admin_user = user
            except User.DoesNotExist:
                return error_response(f"No user found with email {new_admin_email}. Please create the user first.", http_status=400)
        
        facility.save()
        
        # Send email notification if admin was assigned/changed
        if new_admin_email and new_admin_email != old_admin_email:
            try:
                from apps.accounts.tasks import send_facility_admin_assignment_email_task
                send_facility_admin_assignment_email_task.delay(
                    user_name=facility.admin_user.full_name,
                    user_email=facility.admin_user.email,
                    facility_name=facility.name,
                    facility_type=found_tier,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to send admin assignment email: {e}")
        
        # Return updated data
        return success_response(
            data={
                "id": str(facility.id),
                "name": facility.name,
                "admin_user": facility.admin_user.full_name if facility.admin_user else "",
                "admin_email": facility.admin_user.email if facility.admin_user else "",
            },
            message="Facility updated successfully." + (" An email has been sent to the new admin." if new_admin_email and new_admin_email != old_admin_email else ""),
        )


class CountryListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(tags=["Platform Admin — Locations"], summary="List all countries")
    def get(self, request):
        countries = Country.objects.filter(is_active=True).order_by("name")
        results = [{"id": str(c.id), "name": c.name, "code": c.code} for c in countries]
        return success_response(data={"results": results, "count": len(results)})


class StateListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(tags=["Platform Admin — Locations"], summary="List states by country")
    def get(self, request):
        country_id = request.query_params.get("country")
        if country_id:
            states = State.objects.filter(country_id=country_id, is_active=True).order_by("name")
        else:
            states = State.objects.filter(is_active=True).order_by("name")
        results = [{"id": str(s.id), "name": s.name, "code": s.code, "zone": s.zone} for s in states]
        return success_response(data={"results": results, "count": len(results)})


class HCCAdminDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def _get(self, pk):
        try:
            return HealthCareCenter.objects.get(pk=pk)
        except HealthCareCenter.DoesNotExist:
            return None

    @extend_schema(tags=["Platform Admin — Centers"], summary="[Platform Admin] Get PHC detail")
    def get(self, request, pk):
        center = self._get(pk)
        if not center:
            return error_response("PHC not found.", http_status=404)
        return success_response(data=HealthCareCenterSerializer(center).data)

    @extend_schema(
        tags=["Platform Admin — Centers"],
        request=HealthCareCenterSerializer,
        summary="[Platform Admin] Update PHC",
        description="Platform Admin can set escalates_to to link this PHC to an FMC.",
    )
    def patch(self, request, pk):
        center = self._get(pk)
        if not center:
            return error_response("PHC not found.", http_status=404)
        serializer = HealthCareCenterSerializer(center, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="PHC updated.")

    @extend_schema(tags=["Platform Admin — Centers"], summary="[Platform Admin] Delete PHC")
    def delete(self, request, pk):
        center = self._get(pk)
        if not center:
            return error_response("PHC not found.", http_status=404)
        name = center.name
        center.delete()
        return success_response(message=f"PHC '{name}' deleted.")


class FHCAdminListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(tags=["Platform Admin — Centers"], summary="[Platform Admin] List all FMCs")
    def get(self, request):
        centers = FederalHealthCenter.objects.all().order_by("state", "name")
        results = [{
            "id": str(c.id),
            "name": c.name,
            "address": c.address,
            "state": c.state,
            "zone": c.zone,
            "phone": c.phone,
            "email": c.email,
            "status": c.status,
            "tier": "FMC",
        } for c in centers]
        return success_response(data={
            "results": results,
            "count": len(results)
        })

    @extend_schema(
        tags=["Platform Admin — Centers"],
        request=FederalHealthCenterSerializer,
        summary="[Platform Admin] Create an FMC",
    )
    def post(self, request):
        serializer = FederalHealthCenterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        center = serializer.save()
        return created_response(
            data=FederalHealthCenterSerializer(center).data,
            message=f"FMC '{center.name}' created.",
        )


class FHCAdminDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def _get(self, pk):
        try:
            return FederalHealthCenter.objects.get(pk=pk)
        except FederalHealthCenter.DoesNotExist:
            return None

    @extend_schema(tags=["Platform Admin — Centers"], summary="[Platform Admin] Get FMC detail")
    def get(self, request, pk):
        center = self._get(pk)
        if not center:
            return error_response("FMC not found.", http_status=404)
        return success_response(data=FederalHealthCenterSerializer(center).data)

    @extend_schema(
        tags=["Platform Admin — Centers"],
        request=FederalHealthCenterSerializer,
        summary="[Platform Admin] Update FMC",
    )
    def patch(self, request, pk):
        center = self._get(pk)
        if not center:
            return error_response("FMC not found.", http_status=404)
        serializer = FederalHealthCenterSerializer(center, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="FMC updated.")

    @extend_schema(tags=["Platform Admin — Centers"], summary="[Platform Admin] Delete FMC")
    def delete(self, request, pk):
        center = self._get(pk)
        if not center:
            return error_response("FMC not found.", http_status=404)
        name = center.name
        center.delete()
        return success_response(message=f"FMC '{name}' deleted.")


# ── Private helpers ───────────────────────────────────────────────────────────

import logging

logger = logging.getLogger(__name__)


def _get_user_hcc(user):
    """Returns the HCC linked to an hcc_admin or hcc_staff user."""
    if user.role == "hcc_admin":
        try:
            return user.managed_hcc
        except Exception:
            return None
    if user.role == "hcc_staff":
        try:
            return user.hcc_staff_profile.hcc
        except Exception:
            return None
    return None


def _get_user_fhc(user):
    """Returns the FHC linked to an fhc_admin, fhc_staff, or clinician user."""
    if user.role == "fhc_admin":
        try:
            return user.managed_fhc
        except Exception:
            return None
    if user.role == "fhc_staff":
        try:
            return user.fhc_staff_profile.fhc
        except Exception:
            return None
    if user.role == "clinician":
        try:
            return user.clinician_profile.fhc
        except Exception:
            return None
    return None


def _get_user_clinician(user):
    """Returns the ClinicianProfile linked to a clinician user."""
    if user.role == "clinician":
        try:
            return user.clinician_profile
        except Exception:
            return None
    return None


def _get_patient_phc_for_discharge(patient):
    """Returns the patient's current registered PHC for discharge notifications."""
    try:
        return patient.onboarding_profile.registered_hcc
    except Exception:
        return None


def _notify_fmc_of_escalation(case, hcc, fmc, urgency):
    """Notifies FMC admin and staff when PHC escalates a patient."""
    try:
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService

        urgency_labels = {
            "urgent": "URGENT",
            "priority": "Priority",
            "routine": "Routine",
        }
        urgency_label = urgency_labels.get(urgency, "Priority")

        data = {
            "case_id": str(case.id),
            "patient_id": str(case.patient.id),
            "condition": case.condition,
            "severity": case.severity,
            "hcc_name": hcc.name,
            "urgency": urgency,
            "action": "open_fmc_queue",
        }

        if fmc.admin_user:
            NotificationService.send(
                recipient=fmc.admin_user,
                notification_type=Notification.NotificationType.RISK_UPDATE,
                title=f"[{urgency_label}] PHC escalation: {case.get_condition_display()}",
                body=(
                    f"{hcc.name} has escalated patient {case.patient.full_name} "
                    f"({case.get_condition_display()}) to your facility. "
                    "Please assign a clinician."
                ),
                priority=Notification.Priority.HIGH
                if urgency == "urgent"
                else Notification.Priority.MEDIUM,
                data=data,
            )

        for staff_profile in fmc.get_active_staff():
            NotificationService.send(
                recipient=staff_profile.user,
                notification_type=Notification.NotificationType.RISK_UPDATE,
                title=f"New referral from {hcc.name}",
                body=(
                    f"Patient {case.patient.full_name} referred for "
                    f"{case.get_condition_display()}. Urgency: {urgency_label}."
                ),
                priority=Notification.Priority.HIGH
                if urgency == "urgent"
                else Notification.Priority.MEDIUM,
                data=data,
            )
    except Exception as e:
        logger.error("Failed to notify FMC of escalation: %s", e)


def _notify_patient_escalated(patient, hcc, fmc):
    """Notifies patient they have been referred to an FMC by their PHC."""
    try:
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService

        NotificationService.send(
            recipient=patient,
            notification_type=Notification.NotificationType.SYSTEM,
            title="You have been referred to a specialist centre",
            body=(
                f"{hcc.name} has referred you to {fmc.name} for specialist review. "
                "A doctor will be assigned to your case soon."
            ),
            priority=Notification.Priority.HIGH,
            data={
                "fmc_name": fmc.name,
                "hcc_name": hcc.name,
                "action": "open_risk_details",
            },
        )
    except Exception as e:
        logger.error("Failed to notify patient of escalation: %s", e)


def _notify_patient_phc_discharged(record):
    """Notifies patient when PHC staff discharges them at PHC level."""
    try:
        from apps.notifications.models import Notification
        from apps.notifications.services import NotificationService

        NotificationService.send(
            recipient=record.patient,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Your PHC case has been closed",
            body=(
                f"Your {record.get_condition_display()} monitoring case at "
                f"{record.hcc.name} has been closed. Continue your daily check-ins."
            ),
            priority=Notification.Priority.LOW,
            data={
                "record_id": str(record.id),
                "condition": record.condition,
                "action": "open_risk_details",
            },
        )
    except Exception as e:
        logger.error("Failed to notify patient of PHC discharge: %s", e)


def _serialize_phc_record(record: PHCPatientRecord) -> dict:
    """Serializes a PHCPatientRecord for API responses."""
    return {
        "id": str(record.id),
        "patient": {
            "id": str(record.patient.id),
            "full_name": record.patient.full_name,
            "email": record.patient.email,
        },
        "hcc": record.hcc.name if record.hcc else None,
        "condition": record.condition,
        "condition_label": record.get_condition_display(),
        "severity": record.severity,
        "severity_label": record.get_severity_display(),
        "status": record.status,
        "status_label": record.get_status_display(),
        "opening_score": record.opening_score,
        "latest_score": record.latest_score,
        "notes": record.notes,
        "last_advice_at": record.last_advice_at.isoformat() if record.last_advice_at else None,
        "next_followup": str(record.next_followup) if record.next_followup else None,
        "escalated_to_case_id": str(record.escalated_to_case.id)
        if record.escalated_to_case
        else None,
        "opened_at": record.opened_at.isoformat(),
        "closed_at": record.closed_at.isoformat() if record.closed_at else None,
    }


def _serialize_case(case: PatientCase) -> dict:
    """Serializes a PatientCase for API responses."""
    # Try to get referring PHC from related PHCPatientRecord
    referring_hcc = None
    try:
        phc_record = getattr(case, "phc_record", None)
        if phc_record and hasattr(phc_record, "hcc") and phc_record.hcc:
            referring_hcc = {
                "id": str(phc_record.hcc.id),
                "name": phc_record.hcc.name,
            }
    except Exception:
        pass

    return {
        "id": str(case.id),
        "patient": {
            "id": str(case.patient.id),
            "full_name": case.patient.full_name,
            "email": case.patient.email,
        },
        "fhc": case.fhc.name if case.fhc else None,
        "hcc": referring_hcc,
        "clinician": {
            "id": str(case.clinician.id),
            "name": f"Dr. {case.clinician.user.full_name}",
            "specialization": case.clinician.get_specialization_display(),
        }
        if case.clinician
        else None,
        "condition": case.condition,
        "condition_label": case.get_condition_display(),
        "severity": case.severity,
        "severity_label": case.get_severity_display(),
        "status": case.status,
        "status_label": case.get_status_display(),
        "opening_score": case.opening_score,
        "closing_score": case.closing_score,
        "fmc_notes": case.fmc_notes,
        "opened_at": case.opened_at.isoformat(),
        "assigned_at": case.assigned_at.isoformat() if case.assigned_at else None,
        "closed_at": case.closed_at.isoformat() if case.closed_at else None,
    }


# ── FMC Consultation Notes & Treatment Plans ────────────────────────────────────────


class FMCConsultationNotesView(APIView):
    """
    GET /api/v1/centers/fmc/cases/<uuid:pk>/consultation-notes/
    POST /api/v1/centers/fmc/cases/<uuid:pk>/consultation-notes/

    Get all consultation notes for a case, or create a new one.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get consultation notes (FMC10)",
        description="Retreives all consultation notes for a patient case.",
    )
    def get(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.get(pk=pk, fhc=fhc)
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)
        notes = case.consultation_notes.all()
        return success_response(data=ConsultationNoteSerializer(notes, many=True).data)

    @extend_schema(
        tags=["FMC Portal"],
        summary="Create consultation note (FMC10)",
        description=(
            "Creates a new consultation note for a patient case.\n\n"
            'Body: `{ "note_type": "initial|followup|routine|urgent", '
            '"content": "...", '
            '"vital_signs": {...}, '
            '"diagnosis": {...} }`'
        ),
    )
    def post(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.get(pk=pk, fhc=fhc)
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)

        serializer = CreateConsultationNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        clinician = _get_user_clinician(request.user)
        if not clinician:
            return error_response("Only clinicians can create consultation notes.", http_status=403)

        note = ConsultationNote.objects.create(
            case=case,
            clinician=clinician,
            **serializer.validated_data,
        )
        return success_response(data=ConsultationNoteSerializer(note).data, http_status=201)


class FMCConsultationNoteDetailView(APIView):
    """
    GET/PATCH/DELETE /api/v1/centers/fmc/consultation-notes/<uuid:pk>/

    Retrieve, update, or delete a specific consultation note.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get consultation note detail (FMC10)",
    )
    def get(self, request, pk):
        try:
            note = ConsultationNote.objects.select_related("case__fhc", "clinician__user").get(
                pk=pk
            )
        except ConsultationNote.DoesNotExist:
            return error_response("Consultation note not found.", http_status=404)

        fhc = _get_user_fhc(request.user)
        if note.case.fhc != fhc:
            return error_response("Consultation note not found.", http_status=404)

        return success_response(data=ConsultationNoteSerializer(note).data)

    @extend_schema(
        tags=["FMC Portal"],
        summary="Update consultation note (FMC10)",
    )
    def patch(self, request, pk):
        try:
            note = ConsultationNote.objects.select_related("case__fhc", "clinician__user").get(
                pk=pk
            )
        except ConsultationNote.DoesNotExist:
            return error_response("Consultation note not found.", http_status=404)

        fhc = _get_user_fhc(request.user)
        if note.case.fhc != fhc:
            return error_response("Consultation note not found.", http_status=404)

        serializer = CreateConsultationNoteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        for key, value in serializer.validated_data.items():
            setattr(note, key, value)
        note.save()

        return success_response(data=ConsultationNoteSerializer(note).data)

    @extend_schema(tags=["FMC Portal"], summary="Delete consultation note (FMC10)")
    def delete(self, request, pk):
        try:
            note = ConsultationNote.objects.select_related("case__fhc").get(pk=pk)
        except ConsultationNote.DoesNotExist:
            return error_response("Consultation note not found.", http_status=404)

        fhc = _get_user_fhc(request.user)
        if note.case.fhc != fhc:
            return error_response("Consultation note not found.", http_status=404)

        note.delete()
        return success_response(data={"deleted": True})


class FMCTreatmentPlansView(APIView):
    """
    GET /api/v1/centers/fmc/cases/<uuid:pk>/treatment-plans/
    POST /api/v1/centers/fmc/cases/<uuid:pk>/treatment-plans/

    Get all treatment plans for a case, or create a new one.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get treatment plans (FMC11)",
        description="Retrieves all treatment plans for a patient case.",
    )
    def get(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.get(pk=pk, fhc=fhc)
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)
        plans = case.treatment_plans.all()
        return success_response(data=TreatmentPlanSerializer(plans, many=True).data)

    @extend_schema(
        tags=["FMC Portal"],
        summary="Create treatment plan (FMC11)",
        description=(
            "Creates a new treatment plan for a patient case.\n\n"
            'Body: `{ "title": "...", '
            '"description": "...", '
            '"medications": {...}, '
            '"lifestyle": {...}, '
            '"follow_up_days": 30 }`'
        ),
    )
    def post(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.get(pk=pk, fhc=fhc)
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)

        serializer = CreateTreatmentPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        clinician = _get_user_clinician(request.user)
        if not clinician:
            return error_response("Only clinicians can create treatment plans.", http_status=403)

        plan = TreatmentPlan.objects.create(
            case=case,
            clinician=clinician,
            **serializer.validated_data,
        )
        return success_response(data=TreatmentPlanSerializer(plan).data, http_status=201)


class FMCTreatmentPlanDetailView(APIView):
    """
    GET/PATCH/DELETE /api/v1/centers/fmc/treatment-plans/<uuid:pk>/

    Retrieve, update, or delete a specific treatment plan.
    """

    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(
        tags=["FMC Portal"],
        summary="Get treatment plan detail (FMC11)",
    )
    def get(self, request, pk):
        try:
            plan = TreatmentPlan.objects.select_related("case__fhc", "clinician__user").get(pk=pk)
        except TreatmentPlan.DoesNotExist:
            return error_response("Treatment plan not found.", http_status=404)

        fhc = _get_user_fhc(request.user)
        if plan.case.fhc != fhc:
            return error_response("Treatment plan not found.", http_status=404)

        return success_response(data=TreatmentPlanSerializer(plan).data)

    @extend_schema(
        tags=["FMC Portal"],
        summary="Update treatment plan (FMC11)",
    )
    def patch(self, request, pk):
        try:
            plan = TreatmentPlan.objects.select_related("case__fhc", "clinician__user").get(pk=pk)
        except TreatmentPlan.DoesNotExist:
            return error_response("Treatment plan not found.", http_status=404)

        fhc = _get_user_fhc(request.user)
        if plan.case.fhc != fhc:
            return error_response("Treatment plan not found.", http_status=404)

        serializer = CreateTreatmentPlanSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        for key, value in serializer.validated_data.items():
            setattr(plan, key, value)
        plan.save()

        return success_response(data=TreatmentPlanSerializer(plan).data)

    @extend_schema(tags=["FMC Portal"], summary="Delete treatment plan (FMC11)")
    def delete(self, request, pk):
        try:
            plan = TreatmentPlan.objects.select_related("case__fhc").get(pk=pk)
        except TreatmentPlan.DoesNotExist:
            return error_response("Treatment plan not found.", http_status=404)

        fhc = _get_user_fhc(request.user)
        if plan.case.fhc != fhc:
            return error_response("Treatment plan not found.", http_status=404)

        plan.delete()
        return success_response(data={"deleted": True})
