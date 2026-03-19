"""
apps/centers/tests/test_centers.py
────────────────────────────────────
Tests for HCC, FHC, and ClinicianProfile endpoints.
Also tests the critical escalation logic in centers/signals.py.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.centers.models import (
    HealthCareCenter,
    FederalHealthCenter,
    ClinicianProfile,
    RiskSeverity,
)

User = get_user_model()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def hcc(db):
    return HealthCareCenter.objects.create(
        name="Test General Hospital",
        code="TGH-001",
        state="Lagos",
        lga="Lagos Island",
        status=HealthCareCenter.CenterStatus.ACTIVE,
        notify_on_severe=True,
        notify_on_very_severe=True,
    )


@pytest.fixture
def fhc(db):
    return FederalHealthCenter.objects.create(
        name="Federal Medical Centre Test",
        code="FMC-TST-001",
        state="FCT",
        zone="North Central",
        status=FederalHealthCenter.CenterStatus.ACTIVE,
    )


@pytest.fixture
def patient(db):
    return User.objects.create_user(
        email="patient@test.com",
        full_name="Test Patient",
        password="TestPass1234!",
        role="patient",
        is_email_verified=True,
    )


@pytest.fixture
def clinician_user(db):
    return User.objects.create_user(
        email="clinician@test.com",
        full_name="Dr. Test Clinician",
        password="TestPass1234!",
        role="clinician",
        is_email_verified=True,
    )


@pytest.fixture
def hcc_admin_user(db, hcc):
    user = User.objects.create_user(
        email="hcc.admin@test.com",
        full_name="HCC Admin",
        password="TestPass1234!",
        role="hcc_admin",
        is_email_verified=True,
    )
    hcc.admin_user = user
    hcc.save(update_fields=["admin_user"])
    return user


@pytest.fixture
def fhc_admin_user(db, fhc):
    user = User.objects.create_user(
        email="fhc.admin@test.com",
        full_name="FHC Admin",
        password="TestPass1234!",
        role="fhc_admin",
        is_email_verified=True,
    )
    fhc.admin_user = user
    fhc.save(update_fields=["admin_user"])
    return user


@pytest.fixture
def platform_admin(db):
    return User.objects.create_superuser(
        email="admin@test.com",
        full_name="Platform Admin",
        password="AdminPass1234!",
    )


@pytest.fixture
def clinician_profile(db, clinician_user, hcc):
    return ClinicianProfile.objects.create(
        user=clinician_user,
        specialization=ClinicianProfile.Specialization.OBSTETRICS_GYNAE,
        license_number="MDCN-2020-12345",
        years_of_experience=5,
        center_type=ClinicianProfile.CenterType.HCC,
        hcc=hcc,
        is_verified=True,
    )


def _auth(api_client, user, password="TestPass1234!"):
    resp = api_client.post(
        reverse("v1:accounts:login"),
        {"email": user.email, "password": password},
        format="json",
    )
    token = resp.data["data"]["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


# ── Public center lists ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPublicCenterLists:

    def test_hcc_list_no_auth_required(self, api_client, hcc):
        url = reverse("v1:centers:hcc-list-public")
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["code"] == "TGH-001"

    def test_fhc_list_no_auth_required(self, api_client, fhc):
        url = reverse("v1:centers:fhc-list-public")
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["code"] == "FMC-TST-001"

    def test_inactive_hcc_not_in_list(self, api_client, hcc):
        hcc.status = HealthCareCenter.CenterStatus.INACTIVE
        hcc.save(update_fields=["status"])
        url = reverse("v1:centers:hcc-list-public")
        resp = api_client.get(url)
        assert resp.data["data"] == []

    def test_hcc_list_returns_minimal_fields(self, api_client, hcc):
        url = reverse("v1:centers:hcc-list-public")
        resp = api_client.get(url)
        item = resp.data["data"][0]
        assert "id" in item
        assert "name" in item
        assert "code" in item
        # Sensitive fields not exposed
        assert "notify_on_severe" not in item
        assert "admin_user" not in item


# ── Clinician profile ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestClinicianProfile:

    url = reverse("v1:centers:clinician-profile")

    def test_get_profile_not_found_returns_404(self, api_client, clinician_user):
        _auth(api_client, clinician_user)
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_create_profile_linked_to_hcc(self, api_client, clinician_user, hcc):
        _auth(api_client, clinician_user)
        resp = api_client.post(self.url, {
            "specialization": "obstetrics_gynae",
            "license_number": "MDCN-2021-99999",
            "years_of_experience": 3,
            "center_type": "hcc",
            "hcc": hcc.pk,
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert ClinicianProfile.objects.filter(user=clinician_user).exists()
        profile = ClinicianProfile.objects.get(user=clinician_user)
        assert profile.hcc == hcc
        assert profile.center_type == "hcc"

    def test_create_profile_linked_to_fhc(self, api_client, clinician_user, fhc):
        _auth(api_client, clinician_user)
        resp = api_client.post(self.url, {
            "specialization": "internal_medicine",
            "license_number": "MDCN-2021-88888",
            "years_of_experience": 10,
            "center_type": "fhc",
            "fhc": fhc.pk,
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        profile = ClinicianProfile.objects.get(user=clinician_user)
        assert profile.fhc == fhc
        assert profile.center_type == "fhc"

    def test_cannot_link_to_both_hcc_and_fhc(self, api_client, clinician_user, hcc, fhc):
        _auth(api_client, clinician_user)
        resp = api_client.post(self.url, {
            "specialization": "general_practice",
            "center_type": "hcc",
            "hcc": hcc.pk,
            "fhc": fhc.pk,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_hcc_type_without_hcc_fails(self, api_client, clinician_user):
        _auth(api_client, clinician_user)
        resp = api_client.post(self.url, {
            "specialization": "general_practice",
            "center_type": "hcc",
            # hcc not provided
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_create_duplicate_profile(self, api_client, clinician_user, clinician_profile):
        _auth(api_client, clinician_user)
        resp = api_client.post(self.url, {
            "specialization": "cardiology",
            "center_type": "hcc",
            "hcc": clinician_profile.hcc.pk,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_profile_success(self, api_client, clinician_user, clinician_profile):
        _auth(api_client, clinician_user)
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.data["data"]
        assert data["specialization"] == "obstetrics_gynae"
        assert data["center_type"] == "hcc"
        assert data["center_name"] == "Test General Hospital"

    def test_update_bio(self, api_client, clinician_user, clinician_profile):
        _auth(api_client, clinician_user)
        resp = api_client.patch(self.url, {
            "bio": "Updated bio text.",
        }, format="json")
        assert resp.status_code == status.HTTP_200_OK
        clinician_profile.refresh_from_db()
        assert clinician_profile.bio == "Updated bio text."

    def test_patient_cannot_access_clinician_endpoint(self, api_client, patient):
        _auth(api_client, patient)
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_cannot_access(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ── Admin endpoints ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAdminHCCManagement:

    list_url = reverse("v1:centers:admin-hcc-list")

    def test_admin_can_list_all_hcc(self, api_client, platform_admin, hcc):
        _auth(api_client, platform_admin, password="AdminPass1234!")
        resp = api_client.get(self.list_url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) >= 1

    def test_admin_can_create_hcc(self, api_client, platform_admin):
        _auth(api_client, platform_admin, password="AdminPass1234!")
        resp = api_client.post(self.list_url, {
            "name": "New Hospital",
            "code": "NH-001",
            "state": "Abuja",
            "lga": "Abuja Municipal",
            "status": "active",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert HealthCareCenter.objects.filter(code="NH-001").exists()

    def test_non_admin_cannot_access(self, api_client, patient):
        _auth(api_client, patient)
        resp = api_client.get(self.list_url)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_update_hcc(self, api_client, platform_admin, hcc):
        _auth(api_client, platform_admin, password="AdminPass1234!")
        url = reverse("v1:centers:admin-hcc-detail", kwargs={"pk": hcc.pk})
        resp = api_client.patch(url, {"notify_on_severe": False}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        hcc.refresh_from_db()
        assert hcc.notify_on_severe is False

    def test_admin_can_delete_hcc(self, api_client, platform_admin, hcc):
        _auth(api_client, platform_admin, password="AdminPass1234!")
        url = reverse("v1:centers:admin-hcc-detail", kwargs={"pk": hcc.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_200_OK
        assert not HealthCareCenter.objects.filter(pk=hcc.pk).exists()


@pytest.mark.django_db
class TestAdminFHCManagement:

    list_url = reverse("v1:centers:admin-fhc-list")

    def test_admin_can_list_fhc(self, api_client, platform_admin, fhc):
        _auth(api_client, platform_admin, password="AdminPass1234!")
        resp = api_client.get(self.list_url)
        assert resp.status_code == status.HTTP_200_OK

    def test_admin_can_create_fhc(self, api_client, platform_admin):
        _auth(api_client, platform_admin, password="AdminPass1234!")
        resp = api_client.post(self.list_url, {
            "name": "Federal Medical Centre Kano",
            "code": "FMC-KAN-001",
            "state": "Kano",
            "zone": "North West",
            "status": "active",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED

    def test_fhc_notify_on_very_severe_always_true(self, api_client, platform_admin):
        """notify_on_very_severe must always be True for FHC — non-editable."""
        _auth(api_client, platform_admin, password="AdminPass1234!")
        resp = api_client.post(self.list_url, {
            "name": "FHC Force Test",
            "code": "FHC-FRC-001",
            "state": "Lagos",
            "zone": "South West",
            "status": "active",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        fhc = FederalHealthCenter.objects.get(code="FHC-FRC-001")
        assert fhc.notify_on_very_severe is True


# ── Escalation logic ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestEscalationNotifications:

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_severe_notifies_clinician_and_hcc_admin(
        self, mock_push, patient, clinician_profile, hcc_admin_user
    ):
        from apps.notifications.models import Notification
        from apps.centers.signals import notify_center_of_critical_risk

        # Patch the clinician lookup to return our fixture profile
        with patch(
            "apps.centers.signals.ClinicianProfile.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.first.return_value = clinician_profile
            notify_center_of_critical_risk(
                patient=patient,
                condition="pcos",
                severity=RiskSeverity.SEVERE,
                score=75,
                previous_score=55,
            )

        # Clinician should be notified
        assert Notification.objects.filter(
            recipient=clinician_profile.user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
        ).exists()

        # HCC admin should be notified
        assert Notification.objects.filter(
            recipient=hcc_admin_user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_very_severe_notifies_fhc_admin(
        self, mock_push, patient, fhc, fhc_admin_user, clinician_user
    ):
        from apps.notifications.models import Notification
        from apps.centers.signals import notify_center_of_critical_risk

        # Create clinician linked to FHC
        fhc_clinician = ClinicianProfile.objects.create(
            user=clinician_user,
            specialization=ClinicianProfile.Specialization.GENERAL_PRACTICE,
            center_type=ClinicianProfile.CenterType.FHC,
            fhc=fhc,
            is_verified=True,
        )

        with patch(
            "apps.centers.signals.ClinicianProfile.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.first.return_value = fhc_clinician
            notify_center_of_critical_risk(
                patient=patient,
                condition="cardiovascular",
                severity=RiskSeverity.VERY_SEVERE,
                score=92,
                previous_score=70,
            )

        # FHC admin must be notified for very severe
        assert Notification.objects.filter(
            recipient=fhc_admin_user,
            notification_type=Notification.NotificationType.RISK_UPDATE,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_mild_does_not_escalate(self, mock_push, patient, clinician_profile, hcc_admin_user):
        from apps.notifications.models import Notification
        from apps.centers.signals import notify_center_of_critical_risk

        with patch("apps.centers.signals.ClinicianProfile.objects.filter") as mock_filter:
            mock_filter.return_value.first.return_value = clinician_profile
            notify_center_of_critical_risk(
                patient=patient,
                condition="pcos",
                severity=RiskSeverity.MILD,
                score=22,
                previous_score=18,
            )

        # No escalation notifications for mild
        assert not Notification.objects.filter(
            recipient=hcc_admin_user,
        ).exists()

    @patch("apps.notifications.services.NotificationService._push_to_channel")
    def test_moderate_does_not_escalate(self, mock_push, patient, clinician_profile, hcc_admin_user):
        from apps.notifications.models import Notification
        from apps.centers.signals import notify_center_of_critical_risk

        with patch("apps.centers.signals.ClinicianProfile.objects.filter") as mock_filter:
            mock_filter.return_value.first.return_value = clinician_profile
            notify_center_of_critical_risk(
                patient=patient,
                condition="maternal",
                severity=RiskSeverity.MODERATE,
                score=45,
                previous_score=30,
            )

        assert not Notification.objects.filter(
            recipient=hcc_admin_user,
        ).exists()


# ── RiskSeverity enum ─────────────────────────────────────────────────────────

class TestRiskSeverity:

    def test_all_four_levels_exist(self):
        levels = [c[0] for c in RiskSeverity.choices]
        assert "mild" in levels
        assert "moderate" in levels
        assert "severe" in levels
        assert "very_severe" in levels

    def test_values_are_strings(self):
        for value, _ in RiskSeverity.choices:
            assert isinstance(value, str)

    def test_labels_are_human_readable(self):
        labels = dict(RiskSeverity.choices)
        assert labels["very_severe"] == "Very Severe"
        assert labels["mild"] == "Mild"
