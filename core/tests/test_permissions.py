"""
core/tests/test_permissions.py
────────────────────────────────
Tests for all custom permission classes.
"""
import pytest
from unittest.mock import MagicMock
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from core.permissions import (
    IsEmailVerified,
    IsPatient,
    IsClinician,
    IsPatientOrClinician,
    IsOnboardingComplete,
    IsOwner,
    IsOwnerOrReadOnly,
    IsHCCAdmin,
    IsFHCAdmin,
    IsCenterAdmin,
)

User = get_user_model()


def _make_request(user):
    req = MagicMock()
    req.user = user
    req.method = "GET"
    return req


def _make_user(
    role="patient",
    is_email_verified=True,
    onboarding_completed=True,
    is_authenticated=True,
):
    user = MagicMock(spec=User)
    user.role = role
    user.is_email_verified = is_email_verified
    user.onboarding_completed = onboarding_completed
    user.is_authenticated = is_authenticated
    user.is_anonymous = not is_authenticated
    return user


@pytest.mark.django_db
class TestIsEmailVerified:
    def test_verified_user_passes(self):
        user = _make_user(is_email_verified=True)
        perm = IsEmailVerified()
        assert perm.has_permission(_make_request(user), None) is True

    def test_unverified_user_blocked(self):
        user = _make_user(is_email_verified=False)
        perm = IsEmailVerified()
        assert perm.has_permission(_make_request(user), None) is False


class TestIsPatient:
    def test_patient_passes(self):
        user = _make_user(role="patient")
        perm = IsPatient()
        assert perm.has_permission(_make_request(user), None) is True

    def test_clinician_blocked(self):
        user = _make_user(role="clinician")
        perm = IsPatient()
        assert perm.has_permission(_make_request(user), None) is False

    def test_admin_blocked(self):
        user = _make_user(role="admin")
        perm = IsPatient()
        assert perm.has_permission(_make_request(user), None) is False


class TestIsClinician:
    def test_clinician_passes(self):
        user = _make_user(role="clinician")
        perm = IsClinician()
        assert perm.has_permission(_make_request(user), None) is True

    def test_patient_blocked(self):
        user = _make_user(role="patient")
        perm = IsClinician()
        assert perm.has_permission(_make_request(user), None) is False


class TestIsPatientOrClinician:
    def test_patient_passes(self):
        user = _make_user(role="patient")
        perm = IsPatientOrClinician()
        assert perm.has_permission(_make_request(user), None) is True

    def test_clinician_passes(self):
        user = _make_user(role="clinician")
        perm = IsPatientOrClinician()
        assert perm.has_permission(_make_request(user), None) is True

    def test_admin_blocked(self):
        user = _make_user(role="admin")
        perm = IsPatientOrClinician()
        assert perm.has_permission(_make_request(user), None) is False


class TestIsOnboardingComplete:
    def test_completed_passes(self):
        user = _make_user(onboarding_completed=True)
        perm = IsOnboardingComplete()
        assert perm.has_permission(_make_request(user), None) is True

    def test_incomplete_blocked(self):
        user = _make_user(onboarding_completed=False)
        perm = IsOnboardingComplete()
        assert perm.has_permission(_make_request(user), None) is False


class TestIsOwner:
    def test_owner_has_object_permission(self):
        user = _make_user()
        obj = MagicMock()
        obj.user = user
        perm = IsOwner()
        assert perm.has_object_permission(_make_request(user), None, obj) is True

    def test_non_owner_blocked(self):
        user = _make_user()
        other_user = _make_user(role="clinician")
        obj = MagicMock()
        obj.user = other_user
        perm = IsOwner()
        assert perm.has_object_permission(_make_request(user), None, obj) is False


class TestIsOwnerOrReadOnly:
    def test_owner_can_write(self):
        user = _make_user()
        obj = MagicMock()
        obj.user = user
        req = _make_request(user)
        req.method = "PUT"
        perm = IsOwnerOrReadOnly()
        assert perm.has_object_permission(req, None, obj) is True

    def test_non_owner_can_read(self):
        user = _make_user()
        other_user = _make_user(role="clinician")
        obj = MagicMock()
        obj.user = other_user
        req = _make_request(user)
        req.method = "GET"
        perm = IsOwnerOrReadOnly()
        assert perm.has_object_permission(req, None, obj) is True

    def test_non_owner_cannot_write(self):
        user = _make_user()
        other_user = _make_user(role="clinician")
        obj = MagicMock()
        obj.user = other_user
        req = _make_request(user)
        req.method = "DELETE"
        perm = IsOwnerOrReadOnly()
        assert perm.has_object_permission(req, None, obj) is False


class TestIsHCCAdmin:
    def test_hcc_admin_passes(self):
        user = _make_user(role="hcc_admin")
        perm = IsHCCAdmin()
        assert perm.has_permission(_make_request(user), None) is True

    def test_patient_blocked(self):
        user = _make_user(role="patient")
        perm = IsHCCAdmin()
        assert perm.has_permission(_make_request(user), None) is False

    def test_clinician_blocked(self):
        user = _make_user(role="clinician")
        perm = IsHCCAdmin()
        assert perm.has_permission(_make_request(user), None) is False

    def test_fhc_admin_blocked(self):
        user = _make_user(role="fhc_admin")
        perm = IsHCCAdmin()
        assert perm.has_permission(_make_request(user), None) is False


class TestIsFHCAdmin:
    def test_fhc_admin_passes(self):
        user = _make_user(role="fhc_admin")
        perm = IsFHCAdmin()
        assert perm.has_permission(_make_request(user), None) is True

    def test_hcc_admin_blocked(self):
        user = _make_user(role="hcc_admin")
        perm = IsFHCAdmin()
        assert perm.has_permission(_make_request(user), None) is False


class TestIsCenterAdmin:
    def test_hcc_admin_passes(self):
        user = _make_user(role="hcc_admin")
        perm = IsCenterAdmin()
        assert perm.has_permission(_make_request(user), None) is True

    def test_fhc_admin_passes(self):
        user = _make_user(role="fhc_admin")
        perm = IsCenterAdmin()
        assert perm.has_permission(_make_request(user), None) is True

    def test_patient_blocked(self):
        user = _make_user(role="patient")
        perm = IsCenterAdmin()
        assert perm.has_permission(_make_request(user), None) is False

    def test_clinician_blocked(self):
        user = _make_user(role="clinician")
        perm = IsCenterAdmin()
        assert perm.has_permission(_make_request(user), None) is False
