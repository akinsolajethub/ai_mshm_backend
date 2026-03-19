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
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.responses import success_response, created_response, error_response
from core.permissions.roles import (
    IsHCCAdmin, IsAnyPHCUser,
    IsFHCAdmin, IsAnyFMCUser,
    IsClinician, IsPatient,
)
from .models import (
    HealthCareCenter, FederalHealthCenter,
    HCCStaffProfile, FHCStaffProfile, ClinicianProfile,
    PHCPatientRecord, PatientCase, ChangeRequest,
)
from .serializers import (
    HealthCareCenterSerializer, HealthCareCenterPublicSerializer,
    FederalHealthCenterSerializer, FederalHealthCenterPublicSerializer,
    HCCStaffProfileSerializer, CreateHCCStaffSerializer,
    FHCStaffProfileSerializer, CreateFHCStaffSerializer,
    ClinicianProfileSerializer, UpdateClinicianProfileSerializer,
    CreateClinicianSerializer, ChangeRequestSerializer,
    PHCWalkInSerializer,
)

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
        qs    = HealthCareCenter.objects.filter(status=HealthCareCenter.CenterStatus.ACTIVE)
        state = request.query_params.get("state")
        lga   = request.query_params.get("lga")
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
        return success_response(
            data=FederalHealthCenterPublicSerializer(centers, many=True).data
        )


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
            "- `severity` — `mild` | `moderate`"
        ),
    )
    def get(self, request):
        hcc = _get_user_hcc(request.user)
        if not hcc:
            return error_response("No PHC facility linked to your account.", http_status=404)

        qs = PHCPatientRecord.objects.filter(
            hcc=hcc
        ).select_related("patient", "escalated_to_case")

        status    = request.query_params.get("status")
        condition = request.query_params.get("condition")
        severity  = request.query_params.get("severity")

        if status:
            qs = qs.filter(status=status)
        if condition:
            qs = qs.filter(condition=condition)
        if severity:
            qs = qs.filter(severity=severity)

        # Default: exclude discharged and escalated
        if not status:
            qs = qs.exclude(
                status__in=[
                    PHCPatientRecord.RecordStatus.DISCHARGED,
                    PHCPatientRecord.RecordStatus.ESCALATED,
                ]
            )

        return success_response(
            data=[_serialize_phc_record(r) for r in qs.order_by("-opened_at")]
        )


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
        data           = {k: v for k, v in request.data.items() if k in allowed_fields}

        # Validate status transitions
        new_status = data.get("status")
        if new_status:
            valid_transitions = {
                PHCPatientRecord.RecordStatus.NEW:          [PHCPatientRecord.RecordStatus.UNDER_REVIEW],
                PHCPatientRecord.RecordStatus.UNDER_REVIEW: [PHCPatientRecord.RecordStatus.ACTION_TAKEN,
                                                              PHCPatientRecord.RecordStatus.DISCHARGED],
                PHCPatientRecord.RecordStatus.ACTION_TAKEN: [PHCPatientRecord.RecordStatus.DISCHARGED],
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
            "Body (optional): `{ \"urgency\": \"urgent\", \"notes\": \"...\" }`\n"
            "urgency: `routine` | `priority` | `urgent`"
        ),
    )
    def post(self, request, pk):
        hcc = _get_user_hcc(request.user)
        if not hcc:
            return error_response("No PHC facility linked to your account.", http_status=404)

        try:
            record = PHCPatientRecord.objects.select_related(
                "patient", "hcc"
            ).get(pk=pk, hcc=hcc)
        except PHCPatientRecord.DoesNotExist:
            return error_response("Record not found.", http_status=404)

        if not record.is_open():
            return error_response(
                f"Cannot escalate a record with status '{record.status}'."
            )

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
        notes   = request.data.get("notes", "")

        # Add PHC notes before escalating
        if notes:
            record.notes = (record.notes + "\n\n" + notes).strip()
            record.save(update_fields=["notes"])

        # Create PatientCase at FMC
        # Map PHCPatientRecord condition to PatientCase condition
        condition_map = {
            PHCPatientRecord.Condition.PCOS:           PatientCase.Condition.PCOS,
            PHCPatientRecord.Condition.MATERNAL:       PatientCase.Condition.MATERNAL,
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
        record.status            = PHCPatientRecord.RecordStatus.ESCALATED
        record.closed_at         = timezone.now()
        record.save(update_fields=["escalated_to_case", "status", "closed_at"])

        logger.info(
            "PHC '%s' escalated patient %s to FMC '%s'. Case: %s",
            hcc.name, record.patient.email, fmc.name, case.id,
        )

        # Notify FMC admin + staff
        _notify_fmc_of_escalation(
            case=case, hcc=hcc, fmc=fmc, urgency=urgency,
        )

        # Notify patient they have been referred
        _notify_patient_escalated(patient=record.patient, hcc=hcc, fmc=fmc)

        return success_response(
            data={
                "phc_record_id": str(record.id),
                "case_id":       str(case.id),
                "fmc_name":      fmc.name,
                "urgency":       urgency,
                "status":        record.status,
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

        # Create onboarding profile and link to this PHC
        from apps.onboarding.models import OnboardingProfile
        profile = OnboardingProfile.objects.create(
            user=patient,
            full_name=data["full_name"],
            age=data.get("age"),
            state=hcc.state,
            lga=hcc.lga,
            registered_hcc=hcc,
        )

        # Create PHC patient record
        condition_map = {
            "pcos":           PHCPatientRecord.Condition.PCOS,
            "maternal":       PHCPatientRecord.Condition.MATERNAL,
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

        # TODO: Send temp_password to patient via SMS/email
        # AuthService.send_walkin_welcome(patient, temp_password)

        logger.info(
            "Walk-in patient registered: %s at PHC '%s' by staff %s",
            patient.email, hcc.name, request.user.email,
        )

        return created_response(
            data={
                "patient_id":     str(patient.id),
                "patient_email":  patient.email,
                "patient_name":   patient.full_name,
                "phc_record_id":  str(record.id),
                "registered_hcc": hcc.name,
                "temp_password":  temp_password,  # Staff shares this with patient
            },
            message=(
                f"Patient registered successfully and linked to {hcc.name}. "
                "Share the temporary password with the patient."
            ),
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
            email=data["email"], password=temp_password,
            full_name=data["full_name"], role=User.Role.HCC_STAFF, is_email_verified=True,
        )
        profile = HCCStaffProfile.objects.create(
            user=user, hcc=center,
            staff_role=data["staff_role"], employee_id=data.get("employee_id", ""),
        )
        return created_response(
            data=HCCStaffProfileSerializer(profile).data,
            message=f"PHC staff account created for {user.email}.",
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

    @extend_schema(tags=["PHC Admin"], request=HCCStaffProfileSerializer, summary="Update PHC staff member")
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
    permission_classes = [IsAuthenticated, IsFHCAdmin]

    def _get_center(self, user):
        try:
            return user.managed_fhc
        except Exception:
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

    @extend_schema(tags=["FMC Admin"], request=FederalHealthCenterSerializer, summary="Update own FMC facility profile")
    def patch(self, request):
        center = self._get_center(request.user)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        serializer = FederalHealthCenterSerializer(center, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="FMC profile updated.")


class FMCStaffListView(APIView):
    permission_classes = [IsAuthenticated, IsFHCAdmin]

    @extend_schema(tags=["FMC Admin"], summary="List FMC staff accounts")
    def get(self, request):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        staff = FHCStaffProfile.objects.filter(fhc=center).select_related("user")
        return success_response(data=FHCStaffProfileSerializer(staff, many=True).data)

    @extend_schema(tags=["FMC Admin"], request=CreateFHCStaffSerializer, summary="Create an FMC staff account")
    def post(self, request):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        serializer = CreateFHCStaffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        temp_password = _generate_temp_password()
        user = User.objects.create_user(
            email=data["email"], password=temp_password,
            full_name=data["full_name"], role=User.Role.FHC_STAFF, is_email_verified=True,
        )
        profile = FHCStaffProfile.objects.create(
            user=user, fhc=center,
            staff_role=data["staff_role"], employee_id=data.get("employee_id", ""),
        )
        return created_response(
            data=FHCStaffProfileSerializer(profile).data,
            message=f"FMC staff account created for {user.email}.",
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

    @extend_schema(tags=["FMC Admin"], request=FHCStaffProfileSerializer, summary="Update FMC staff member")
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
    permission_classes = [IsAuthenticated, IsFHCAdmin]

    @extend_schema(tags=["FMC Admin"], summary="List clinicians for this FMC")
    def get(self, request):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        clinicians = ClinicianProfile.objects.filter(fhc=center).select_related("user")
        return success_response(
            data=ClinicianProfileSerializer(clinicians, many=True, context={"request": request}).data
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
            email=data["email"], password=temp_password,
            full_name=data["full_name"], role=User.Role.CLINICIAN, is_email_verified=True,
        )
        profile = ClinicianProfile.objects.create(
            user=user, fhc=center,
            specialization=data.get("specialization", ClinicianProfile.Specialization.GENERAL_PRACTICE),
            license_number=data.get("license_number", ""),
            years_of_experience=data.get("years_of_experience", 0),
            bio=data.get("bio", ""),
        )
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

    @extend_schema(tags=["FMC Admin"], request=UpdateClinicianProfileSerializer, summary="Update clinician profile")
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
    permission_classes = [IsAuthenticated, IsFHCAdmin]

    @extend_schema(
        tags=["FMC Admin"],
        summary="Verify a clinician account",
        description="Marks clinician as verified. Clinician receives in-app notification.",
    )
    def post(self, request, pk):
        center = getattr(request.user, "managed_fhc", None)
        if not center:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            profile = ClinicianProfile.objects.select_related("user").get(pk=pk, fhc=center)
        except ClinicianProfile.DoesNotExist:
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
            "patient", "clinician__user"
        )
        status    = request.query_params.get("status")
        condition = request.query_params.get("condition")
        severity  = request.query_params.get("severity")
        if status:
            qs = qs.filter(status=status)
        if condition:
            qs = qs.filter(condition=condition)
        if severity:
            qs = qs.filter(severity=severity)
        if not status:
            qs = qs.exclude(status=PatientCase.CaseStatus.DISCHARGED)

        return success_response(
            data=[_serialize_case(c) for c in qs.order_by("opened_at")]
        )


class FMCCaseDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAnyFMCUser]

    @extend_schema(tags=["FMC Portal"], summary="Get patient case detail (FMC3)")
    def get(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.select_related(
                "patient", "fhc", "clinician__user"
            ).get(pk=pk, fhc=fhc)
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
            "Body: `{ \"clinician_id\": \"<uuid>\" }`"
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
                pk=clinician_id, fhc=fhc, is_verified=True, user__is_active=True,
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
                    "case_id":    str(case.id),
                    "patient_id": str(case.patient.id),
                    "condition":  case.condition,
                    "severity":   case.severity,
                    "action":     "open_clinician_dashboard",
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
                    "case_id":        str(case.id),
                    "clinician_name": clinician.user.full_name,
                    "fmc_name":       fhc.name,
                    "action":         "open_risk_details",
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
            "Body (optional): `{ \"closing_score\": 35, \"notes\": \"...\" }`"
        ),
    )
    def post(self, request, pk):
        fhc = _get_user_fhc(request.user)
        if not fhc:
            return error_response("No FMC facility linked to your account.", http_status=404)
        try:
            case = PatientCase.objects.select_related(
                "patient", "clinician__user"
            ).get(pk=pk, fhc=fhc)
        except PatientCase.DoesNotExist:
            return error_response("Case not found.", http_status=404)
        if not case.is_open():
            return error_response(
                f"Case is already closed (status: {case.status})."
            )

        closing_score = request.data.get("closing_score")
        notes         = request.data.get("notes", "")

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
                    "case_id":       str(case.id),
                    "condition":     case.condition,
                    "closing_score": closing_score,
                    "action":        "open_risk_details",
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
                        "case_id":    str(case.id),
                        "patient_id": str(case.patient.id),
                        "fmc_name":   fhc.name,
                        "action":     "open_phc_queue",
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
                            "case_id":    str(case.id),
                            "patient_id": str(case.patient.id),
                            "action":     "open_phc_queue",
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
                "Your account is not yet verified. "
                "Please contact your FMC administrator.",
                http_status=403,
            )

        qs = PatientCase.objects.filter(
            clinician=clinician
        ).select_related("patient", "fhc")

        status    = request.query_params.get("status")
        condition = request.query_params.get("condition")
        if status:
            qs = qs.filter(status=status)
        if condition:
            qs = qs.filter(condition=condition)
        if not status:
            qs = qs.exclude(status=PatientCase.CaseStatus.DISCHARGED)

        return success_response(
            data=[_serialize_case(c) for c in qs.order_by("opened_at")]
        )


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
            case = PatientCase.objects.select_related(
                "patient", "fhc", "clinician__user"
            ).get(pk=pk, clinician=clinician)
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
        return success_response(data=HealthCareCenterSerializer(centers, many=True).data)

    @extend_schema(
        tags=["Platform Admin — Centers"],
        request=HealthCareCenterSerializer,
        summary="[Platform Admin] Create a PHC",
        description="After creation, set escalates_to to link this PHC to an FMC.",
    )
    def post(self, request):
        serializer = HealthCareCenterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        center = serializer.save()
        return created_response(
            data=HealthCareCenterSerializer(center).data,
            message=f"PHC '{center.name}' created.",
        )


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
        return success_response(data=FederalHealthCenterSerializer(centers, many=True).data)

    @extend_schema(tags=["Platform Admin — Centers"], request=FederalHealthCenterSerializer, summary="[Platform Admin] Create an FMC")
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

    @extend_schema(tags=["Platform Admin — Centers"], request=FederalHealthCenterSerializer, summary="[Platform Admin] Update FMC")
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
            "urgent":   "URGENT",
            "priority": "Priority",
            "routine":  "Routine",
        }
        urgency_label = urgency_labels.get(urgency, "Priority")

        data = {
            "case_id":    str(case.id),
            "patient_id": str(case.patient.id),
            "condition":  case.condition,
            "severity":   case.severity,
            "hcc_name":   hcc.name,
            "urgency":    urgency,
            "action":     "open_fmc_queue",
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
                priority=Notification.Priority.HIGH if urgency == "urgent" else Notification.Priority.MEDIUM,
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
                priority=Notification.Priority.HIGH if urgency == "urgent" else Notification.Priority.MEDIUM,
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
                "action":   "open_risk_details",
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
                "action":    "open_risk_details",
            },
        )
    except Exception as e:
        logger.error("Failed to notify patient of PHC discharge: %s", e)


def _serialize_phc_record(record: PHCPatientRecord) -> dict:
    """Serializes a PHCPatientRecord for API responses."""
    return {
        "id":            str(record.id),
        "patient": {
            "id":        str(record.patient.id),
            "full_name": record.patient.full_name,
            "email":     record.patient.email,
        },
        "hcc":           record.hcc.name if record.hcc else None,
        "condition":     record.condition,
        "condition_label": record.get_condition_display(),
        "severity":      record.severity,
        "severity_label": record.get_severity_display(),
        "status":        record.status,
        "status_label":  record.get_status_display(),
        "opening_score": record.opening_score,
        "latest_score":  record.latest_score,
        "notes":         record.notes,
        "last_advice_at": record.last_advice_at.isoformat() if record.last_advice_at else None,
        "next_followup": str(record.next_followup) if record.next_followup else None,
        "escalated_to_case_id": str(record.escalated_to_case.id) if record.escalated_to_case else None,
        "opened_at":     record.opened_at.isoformat(),
        "closed_at":     record.closed_at.isoformat() if record.closed_at else None,
    }


def _serialize_case(case: PatientCase) -> dict:
    """Serializes a PatientCase for API responses."""
    return {
        "id":            str(case.id),
        "patient": {
            "id":        str(case.patient.id),
            "full_name": case.patient.full_name,
            "email":     case.patient.email,
        },
        "fhc":           case.fhc.name if case.fhc else None,
        "clinician": {
            "id":             str(case.clinician.id),
            "name":           f"Dr. {case.clinician.user.full_name}",
            "specialization": case.clinician.get_specialization_display(),
        } if case.clinician else None,
        "condition":     case.condition,
        "condition_label": case.get_condition_display(),
        "severity":      case.severity,
        "severity_label": case.get_severity_display(),
        "status":        case.status,
        "status_label":  case.get_status_display(),
        "opening_score": case.opening_score,
        "closing_score": case.closing_score,
        "fmc_notes":     case.fmc_notes,
        "opened_at":     case.opened_at.isoformat(),
        "assigned_at":   case.assigned_at.isoformat() if case.assigned_at else None,
        "closed_at":     case.closed_at.isoformat() if case.closed_at else None,
    }