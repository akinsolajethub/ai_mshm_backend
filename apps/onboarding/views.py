"""
apps/onboarding/views.py
─────────────────────────
Step-based onboarding endpoints — one view per step.

FLOW:
    PATCH /api/v1/onboarding/step/1/       →  Personal Info
    PATCH /api/v1/onboarding/step/2/       →  Physical Measurements
    PATCH /api/v1/onboarding/step/3/       →  Skin Changes
    PATCH /api/v1/onboarding/step/4/       →  Menstrual History
    PATCH /api/v1/onboarding/step/5/       →  Wearable Setup
    POST  /api/v1/onboarding/step/6/rppg/  →  rPPG Baseline
    PATCH /api/v1/onboarding/step/7/       →  PHC Registration (optional)
    POST  /api/v1/onboarding/complete/     →  Mark complete
    GET   /api/v1/onboarding/profile/      →  Full onboarding data

PHC CHANGE BLOCK (Step 7):
  If the patient has an active ASSIGNED or UNDER_TREATMENT PatientCase,
  they cannot change their PHC. The view returns a 400 error explaining
  which FMC currently holds their active case and when they can change.

  OPEN cases (no clinician assigned) are fine — the patient can change
  their PHC. The signals.py will automatically close the old case and
  open a new one at the new FMC.

  If the patient genuinely needs to change during active treatment
  (e.g. they moved cities), they must submit a ChangeRequest.
  Platform Admin handles these manually.

PHC REMINDER (OnboardingCompleteView):
  If patient skipped step 7 (no PHC set), a reminder task is scheduled:
    - With Celery: fires 24 hours later
    - FREE_TIER: fires inline immediately
"""
from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.responses import success_response, error_response
from .serializers import (
    Step1PersonalInfoSerializer,
    Step2PhysicalMeasurementsSerializer,
    Step3SkinChangesSerializer,
    Step4MenstrualHistorySerializer,
    Step5WearableSerializer,
    Step6RppgSerializer,
    Step7PHCRegistrationSerializer,
    OnboardingProfileSerializer,
)
from .services import OnboardingService


# ── Step 1: Personal Info ─────────────────────────────────────────────────────

class OnboardingStep1View(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        request=Step1PersonalInfoSerializer,
        responses={200: Step1PersonalInfoSerializer},
        summary="Step 1 – Personal Info",
        description=(
            "Submit personal info.\n\n"
            "- `full_name` — string\n"
            "- `age` — integer (10–120)\n"
            "- `ethnicity` — `white` | `black` | `hispanic` | `asian` | "
            "`south_asian` | `middle_eastern` | `mixed` | `prefer_not`"
        ),
    )
    def patch(self, request):
        profile = OnboardingService.get_or_create_profile(request.user)
        serializer = Step1PersonalInfoSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        OnboardingService.advance_step(request.user, 1)
        return success_response(
            data=serializer.data,
            message="Step 1 (Personal Info) saved successfully.",
        )


# ── Step 2: Physical Measurements ─────────────────────────────────────────────

class OnboardingStep2View(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        request=Step2PhysicalMeasurementsSerializer,
        responses={200: Step2PhysicalMeasurementsSerializer},
        summary="Step 2 – Physical Measurements",
        description=(
            "Submit physical measurements. BMI is computed automatically.\n\n"
            "- `height_cm` — float (50–300)\n"
            "- `weight_kg` — float (20–500)"
        ),
    )
    def patch(self, request):
        profile = OnboardingService.get_or_create_profile(request.user)
        serializer = Step2PhysicalMeasurementsSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        OnboardingService.advance_step(request.user, 2)
        return success_response(
            data=serializer.data,
            message="Step 2 (Physical Measurements) saved successfully.",
        )


# ── Step 3: Skin Changes ──────────────────────────────────────────────────────

class OnboardingStep3View(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        request=Step3SkinChangesSerializer,
        responses={200: Step3SkinChangesSerializer},
        summary="Step 3 – Skin Changes",
        description=(
            "Submit skin change info (Acanthosis Nigricans screening).\n\n"
            "- `has_skin_changes` — boolean"
        ),
    )
    def patch(self, request):
        profile = OnboardingService.get_or_create_profile(request.user)
        serializer = Step3SkinChangesSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        OnboardingService.advance_step(request.user, 3)
        return success_response(
            data=serializer.data,
            message="Step 3 (Skin Changes) saved successfully.",
        )


# ── Step 4: Menstrual History ─────────────────────────────────────────────────

class OnboardingStep4View(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        request=Step4MenstrualHistorySerializer,
        responses={200: Step4MenstrualHistorySerializer},
        summary="Step 4 – Menstrual History",
        description=(
            "Submit menstrual history.\n\n"
            "- `cycle_length_days` — integer (1–90)\n"
            "- `periods_per_year` — integer (0–14)\n"
            "- `cycle_regularity` — `regular` | `irregular`"
        ),
    )
    def patch(self, request):
        profile = OnboardingService.get_or_create_profile(request.user)
        serializer = Step4MenstrualHistorySerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        OnboardingService.advance_step(request.user, 4)
        return success_response(
            data=serializer.data,
            message="Step 4 (Menstrual History) saved successfully.",
        )


# ── Step 5: Wearable Setup ────────────────────────────────────────────────────

class OnboardingStep5View(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        request=Step5WearableSerializer,
        responses={200: Step5WearableSerializer},
        summary="Step 5 – Wearable Setup",
        description=(
            "Submit wearable device selection.\n\n"
            "- `selected_wearable` — `apple_watch` | `fitbit` | `garmin` | `oura_ring` | `none`"
        ),
    )
    def patch(self, request):
        profile = OnboardingService.get_or_create_profile(request.user)
        serializer = Step5WearableSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        OnboardingService.advance_step(request.user, 5)
        return success_response(
            data=serializer.data,
            message="Step 5 (Wearable Setup) saved successfully.",
        )


# ── Step 6: rPPG Baseline ─────────────────────────────────────────────────────

class OnboardingRppgView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        request=Step6RppgSerializer,
        summary="Step 6 – rPPG Baseline",
        description=(
            "Mark the rPPG baseline scan as captured.\n\n"
            "- `baseline_captured` — must be `true`"
        ),
    )
    def post(self, request):
        serializer = Step6RppgSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not serializer.validated_data["baseline_captured"]:
            return error_response("baseline_captured must be true to record the scan.")

        profile = OnboardingService.get_or_create_profile(request.user)
        profile.rppg_baseline_captured = True
        profile.rppg_captured_at       = timezone.now()
        profile.save(update_fields=["rppg_baseline_captured", "rppg_captured_at"])
        OnboardingService.advance_step(request.user, 6)

        return success_response(
            message="rPPG baseline recorded successfully.",
            data={
                "rppg_baseline_captured": profile.rppg_baseline_captured,
                "rppg_captured_at":       profile.rppg_captured_at,
            },
        )


# ── Step 7: PHC Registration ──────────────────────────────────────────────────

class OnboardingStep7View(APIView):
    """
    PATCH /api/v1/onboarding/step/7/

    Patient selects or changes their home Primary Health Centre.
    Also used from the P9 Profile Settings screen to update the PHC later.

    BLOCKED if the patient has an active ASSIGNED or UNDER_TREATMENT case:
      The patient cannot change their PHC while a clinician is actively
      treating them. They must wait until the case is discharged, or submit
      a ChangeRequest for urgent situations.

    ALLOWED if the patient has an OPEN case (no clinician assigned yet):
      The change is permitted. signals.py will automatically close the old
      case and open a new one at the new FMC's queue.

    FRONTEND FLOW:
      1. Patient enters their state and LGA
      2. Call GET /api/v1/centers/phc/?state=X&lga=Y for filtered options
      3. Patient selects a PHC from the list
      4. Submit state, lga, and registered_hcc (UUID) here
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        request=Step7PHCRegistrationSerializer,
        summary="Step 7 – PHC Registration (optional, also used from P9 settings)",
        description=(
            "Patient selects their nearest PHC. Optional during onboarding.\n\n"
            "**Blocked** if patient has an active ASSIGNED or UNDER_TREATMENT case "
            "at a clinic. Returns 400 with case details.\n\n"
            "**Allowed** if case is OPEN (no clinician assigned) — old case will "
            "be automatically rerouted.\n\n"
            "**Frontend flow:**\n"
            "1. Patient enters `state` and `lga`\n"
            "2. Call `GET /api/v1/centers/phc/?state=X&lga=Y`\n"
            "3. Patient picks a PHC\n"
            "4. Submit `state`, `lga`, `registered_hcc` here\n\n"
            "Can also be called with `registered_hcc: null` to clear the PHC selection."
        ),
    )
    def patch(self, request):
        user    = request.user
        profile = OnboardingService.get_or_create_profile(user)

        new_hcc_id = request.data.get("registered_hcc")

        # ── Check if patient is trying to change an existing PHC ─────────────
        if new_hcc_id and profile.registered_hcc_id and str(profile.registered_hcc_id) != str(new_hcc_id):
            block_error = _check_active_case_block(user)
            if block_error:
                return block_error

        serializer = Step7PHCRegistrationSerializer(
            profile, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        OnboardingService.advance_step(user, 7)

        return success_response(
            data=serializer.data,
            message="Step 7 (PHC Registration) saved.",
        )


# ── Complete Onboarding ───────────────────────────────────────────────────────

class OnboardingCompleteView(APIView):
    """
    POST /api/v1/onboarding/complete/

    Call after all required steps (1–5). Steps 6 and 7 are optional.
    Sets onboarding_completed=True. Frontend redirects to /dashboard.

    If patient skipped step 7 (no PHC registered), schedules a reminder:
      - Celery workers: fires after 24 hours
      - FREE_TIER: fires inline immediately
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        summary="Mark onboarding as complete",
        description=(
            "Finalises onboarding and sets `onboarding_completed = true`.\n\n"
            "If the patient has not set a home PHC, a reminder notification "
            "is scheduled for 24 hours later."
        ),
    )
    def post(self, request):
        user = request.user
        user.onboarding_completed = True
        user.onboarding_step      = max(user.onboarding_step, 6)
        user.save(update_fields=["onboarding_completed", "onboarding_step"])

        profile = OnboardingService.get_or_create_profile(user)
        _schedule_phc_reminder_if_needed(user, profile)

        return success_response(
            message="Onboarding complete. Welcome to AI-MSHM!",
            data={
                "redirect":             "/dashboard",
                "onboarding_completed": user.onboarding_completed,
                "onboarding_step":      user.onboarding_step,
                "profile":              OnboardingProfileSerializer(profile).data,
            },
        )


# ── Full Profile (read-only) ──────────────────────────────────────────────────

class OnboardingProfileView(APIView):
    """
    GET /api/v1/onboarding/profile/

    Returns the full onboarding profile including the patient's registered PHC
    and the PHC's linked FMC (escalation_fmc_detail). Used by P9 profile screen.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Onboarding"],
        summary="Get current user's full onboarding profile",
        responses={200: OnboardingProfileSerializer},
        description=(
            "Returns all saved onboarding data including registered PHC "
            "and the PHC's escalation FMC. Creates empty profile if none exists."
        ),
    )
    def get(self, request):
        profile = OnboardingService.get_or_create_profile(request.user)
        return success_response(
            data=OnboardingProfileSerializer(profile).data
        )


# ── Private helpers ───────────────────────────────────────────────────────────

def _check_active_case_block(user):
    """
    Checks if the patient has an active ASSIGNED or UNDER_TREATMENT case.
    If so, returns an error_response blocking the PHC change.
    Returns None if the change is allowed.

    OPEN cases are fine — signals.py handles rerouting automatically.
    Only ASSIGNED and UNDER_TREATMENT cases block the change because
    a clinician is actively involved in the patient's care.
    """
    from apps.centers.models import PatientCase

    blocking_case = PatientCase.objects.filter(
        patient=user,
        status__in=[
            PatientCase.CaseStatus.ASSIGNED,
            PatientCase.CaseStatus.UNDER_TREATMENT,
        ],
    ).select_related("fhc", "clinician__user").first()

    if not blocking_case:
        return None  # No block — change is allowed

    fmc_name       = blocking_case.fhc.name if blocking_case.fhc else "your current FMC"
    clinician_name = (
        f"Dr. {blocking_case.clinician.user.full_name}"
        if blocking_case.clinician
        else "a clinician"
    )

    return error_response(
        f"You cannot change your health centre while you have an active case. "
        f"{clinician_name} at {fmc_name} is currently managing your "
        f"{blocking_case.get_condition_display()} case. "
        f"You can update your health centre once your case is discharged. "
        f"If you need to change urgently due to relocation, please submit a "
        f"Change Request from your profile settings.",
        http_status=400,
    )


def _schedule_phc_reminder_if_needed(user, profile):
    """
    Dispatches the PHC registration reminder task if no PHC is set.
    FREE_TIER: runs inline. With Celery: delayed 24 hours.
    Never raises — failure is logged silently.
    """
    if profile.registered_hcc is not None:
        return

    try:
        from apps.notifications.tasks import remind_patient_to_set_phc_task

        if getattr(settings, "FREE_TIER", False):
            remind_patient_to_set_phc_task.run(str(user.id))
        else:
            remind_patient_to_set_phc_task.apply_async(
                args=[str(user.id)],
                countdown=86400,  # 24 hours
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            "Failed to schedule PHC reminder for user %s: %s", user.id, e
        )