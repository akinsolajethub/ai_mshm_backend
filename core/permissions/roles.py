"""
core/permissions/roles.py
──────────────────────────
Custom DRF permission classes for all AI-MSHM user roles.

ROLE HIERARCHY (highest → lowest access):
  ADMIN        — Platform superuser. Django /admin/ only.
  FHC_ADMIN    — FMC facility admin. Manages staff + clinician accounts.
  FHC_STAFF    — FMC case coordinator. Manages High/Critical patient queue.
  CLINICIAN    — Licensed doctor at an FMC. Treats assigned patients.
  HCC_ADMIN    — PHC facility admin. Manages staff accounts.
  HCC_STAFF    — PHC health worker. Screens Low/Moderate patients.
  PATIENT      — End user. Sees only their own health data.

USAGE IN VIEWS:
    from core.permissions.roles import (
        IsPatient, IsClinician, IsHCCStaff, IsHCCAdmin,
        IsFHCStaff, IsFHCAdmin, IsAnyPHCUser, IsAnyFMCUser,
        IsEmailVerified, IsClinicianVerified, IsOnboardingComplete,
    )

    class SomeView(APIView):
        permission_classes = [IsAuthenticated, IsHCCStaff, IsEmailVerified]

COMPOSITES:
    IsAnyPHCUser  = hcc_admin OR hcc_staff
    IsAnyFMCUser  = fhc_admin OR fhc_staff OR clinician
    IsCenterAdmin = hcc_admin OR fhc_admin
"""
from rest_framework.permissions import BasePermission


# ── Email / verification guards ───────────────────────────────────────────────

class IsEmailVerified(BasePermission):
    """
    Blocks access for users who have not verified their email address.
    Always use in combination with IsAuthenticated — never standalone.

    Applied to: all authenticated endpoints after registration.
    """
    message = "Please verify your email address before accessing this resource."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_email_verified
        )


class IsClinicianVerified(BasePermission):
    """
    Blocks access for clinicians whose ClinicianProfile has not been verified
    by their FMC Admin.

    Applied to: all Clinician portal endpoints (CL1–CL8).
    A clinician account may exist but cannot access patient data until
    their profile is reviewed and approved by the FHC Admin.
    """
    message = "Your clinician profile has not been verified by your FMC administrator yet."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.role != "clinician":
            return False
        try:
            return request.user.clinician_profile.is_verified
        except Exception:
            return False


# ── Single-role permissions ───────────────────────────────────────────────────

class IsPatient(BasePermission):
    """
    Allows access only to users with role='patient'.
    Applied to: Patient portal endpoints (P1–P9).
    """
    message = "This endpoint is only available to patients."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "patient"
        )


class IsClinician(BasePermission):
    """
    Allows access only to users with role='clinician'.
    Applied to: Clinician portal endpoints (CL1–CL8).
    Note: combine with IsClinicianVerified for sensitive data endpoints.
    """
    message = "This endpoint is only available to clinicians."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "clinician"
        )


class IsHCCStaff(BasePermission):
    """
    Allows access only to users with role='hcc_staff' (PHC health workers).
    Applied to: PHC portal endpoints (PHC1–PHC9) that are staff-level actions
    such as patient reviews, lifestyle advice, and walk-in registration.
    """
    message = "This endpoint is only available to PHC staff."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "hcc_staff"
        )


class IsHCCAdmin(BasePermission):
    """
    Allows access only to users with role='hcc_admin' (PHC facility admins).
    Applied to: PHC staff management endpoints — creating/deactivating
    PHC staff accounts, viewing facility analytics, updating facility profile.
    """
    message = "This endpoint is only available to PHC administrators."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "hcc_admin"
        )


class IsFHCStaff(BasePermission):
    """
    Allows access only to users with role='fhc_staff' (FMC case coordinators).
    Applied to: FMC portal endpoints (FMC1–FMC9) for queue management,
    clinician assignment, diagnostics requests, and case status updates.
    """
    message = "This endpoint is only available to FMC staff."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "fhc_staff"
        )


class IsFHCAdmin(BasePermission):
    """
    Allows access only to users with role='fhc_admin' (FMC facility admins).
    Applied to: FMC staff + clinician management endpoints — creating accounts,
    verifying clinicians, updating facility profile, viewing facility analytics.
    """
    message = "This endpoint is only available to FMC administrators."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "fhc_admin"
        )


# ── Composite / grouped permissions ──────────────────────────────────────────

class IsAnyPHCUser(BasePermission):
    """
    Allows access to both PHC admins (hcc_admin) and PHC staff (hcc_staff).
    Applied to: PHC portal endpoints where both roles can view the same data
    (e.g. patient queue, facility profile) but may have different write rights
    enforced at the view level.
    """
    message = "This endpoint requires a PHC staff or administrator account."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("hcc_admin", "hcc_staff")
        )


class IsAnyFMCUser(BasePermission):
    """
    Allows access to FMC admins (fhc_admin), FMC staff (fhc_staff),
    and Clinicians (clinician) — all of whom are affiliated with an FMC.
    Applied to: shared FMC/Clinician portal read endpoints.
    """
    message = "This endpoint requires an FMC staff, FMC administrator, or clinician account."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("fhc_admin", "fhc_staff", "clinician")
        )


class IsCenterAdmin(BasePermission):
    """
    Allows access to either PHC admins (hcc_admin) or FMC admins (fhc_admin).
    Applied to: facility management endpoints available to both admin types.
    """
    message = "This endpoint requires a center administrator account."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("hcc_admin", "fhc_admin")
        )


class IsPatientOrClinician(BasePermission):
    """
    Allows access to patients and clinicians.
    Applied to: shared read endpoints for health data that both roles can view
    (e.g. a clinician viewing a patient's shared summary).
    """
    message = "This endpoint requires a patient or clinician account."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("patient", "clinician")
        )


# ── State-based guards ────────────────────────────────────────────────────────

class IsOnboardingComplete(BasePermission):
    """
    Blocks access until the patient has completed all onboarding steps.
    Applied to: dashboard, health check-in, and prediction endpoints.
    Ensures patients provide baseline health data before using the system.
    """
    message = "Please complete your onboarding before accessing this feature."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.onboarding_completed
        )


# ── Object-level permissions ──────────────────────────────────────────────────

class IsOwnerOrReadOnly(BasePermission):
    """
    Object-level: only the object's owner can write; others may read.
    Assumes the model has a `user` FK/OneToOne field pointing to the user.
    Applied to: health check-in records, symptom logs.
    """
    def has_object_permission(self, request, view, obj):
        from rest_framework.permissions import SAFE_METHODS
        if request.method in SAFE_METHODS:
            return True
        return obj.user == request.user


class IsOwner(BasePermission):
    """
    Object-level: only the object's owner can read or write.
    Assumes the model has a `user` FK/OneToOne field pointing to the user.
    Applied to: prediction results, onboarding profiles.
    """
    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        return obj.user == request.user
