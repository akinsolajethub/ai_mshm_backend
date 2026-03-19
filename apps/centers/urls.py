"""
apps/centers/urls.py
─────────────────────
Base prefix: /api/v1/centers/

PUBLIC:
  GET  /phc/                                — PHC list (?state= &lga=)
  GET  /fmc/                                — FMC list

PHC PORTAL (hcc_admin or hcc_staff):
  GET             /phc/queue/               — patient queue (PHC2)
  GET/PATCH       /phc/queue/<uuid>/        — patient record detail (PHC3)
  POST            /phc/queue/<uuid>/escalate/ — escalate to FMC (PHC6)
  POST            /phc/walk-in/             — register walk-in patient (PHC4)

PHC ADMIN (hcc_admin only):
  GET/PATCH       /phc/profile/
  GET/POST        /phc/staff/
  GET/PATCH/DELETE /phc/staff/<uuid>/

FMC PORTAL (fhc_admin or fhc_staff):
  GET             /fmc/cases/               — case queue (FMC2)
  GET             /fmc/cases/<uuid>/        — case detail (FMC3)
  POST            /fmc/cases/<uuid>/assign/ — assign clinician (FMC4)
  POST            /fmc/cases/<uuid>/discharge/ — discharge case (FMC8)

FMC ADMIN (fhc_admin only):
  GET/PATCH       /fmc/profile/
  GET/POST        /fmc/staff/
  GET/PATCH/DELETE /fmc/staff/<uuid>/
  GET/POST        /fmc/clinicians/
  GET/PATCH       /fmc/clinicians/<uuid>/
  POST            /fmc/clinicians/<uuid>/verify/

CLINICIAN:
  GET             /clinician/cases/         — assigned cases (CL2)
  GET             /clinician/cases/<uuid>/  — case detail (CL3)
  GET/PATCH       /clinician/profile/       — own profile (CL8)

PATIENT:
  GET/POST        /change-request/
  GET             /change-request/<uuid>/

PLATFORM ADMIN:
  GET/POST        /admin/phc/
  GET/PATCH/DELETE /admin/phc/<uuid>/
  GET/POST        /admin/fmc/
  GET/PATCH/DELETE /admin/fmc/<uuid>/
"""
from django.urls import path
from .views import (
    # Public
    HCCListPublicView, FHCListPublicView,
    # PHC Portal
    PHCPatientQueueView, PHCPatientRecordView, PHCEscalateView, PHCWalkInView,
    # PHC Admin
    PHCProfileView, PHCStaffListView, PHCStaffDetailView,
    # FMC Portal
    FMCCaseListView, FMCCaseDetailView, FMCAssignClinicianView, FMCDischargeCaseView,
    # FMC Admin
    FMCProfileView, FMCStaffListView, FMCStaffDetailView,
    FMCClinicianListView, FMCClinicianDetailView, FMCVerifyClinicianView,
    # Clinician
    ClinicianCaseListView, ClinicianCaseDetailView, ClinicianProfileView,
    # Patient
    ChangeRequestListView, ChangeRequestDetailView,
    # Platform Admin
    HCCAdminListView, HCCAdminDetailView, FHCAdminListView, FHCAdminDetailView,
)

app_name = "centers"

urlpatterns = [

    # ── Public ───────────────────────────────────────────────────────────────
    path("phc/",  HCCListPublicView.as_view(),  name="phc-list-public"),
    path("fmc/",  FHCListPublicView.as_view(),  name="fmc-list-public"),

    # ── PHC Portal (staff + admin) ────────────────────────────────────────────
    path("phc/queue/",                        PHCPatientQueueView.as_view(),   name="phc-queue"),
    path("phc/queue/<uuid:pk>/",              PHCPatientRecordView.as_view(),  name="phc-record-detail"),
    path("phc/queue/<uuid:pk>/escalate/",     PHCEscalateView.as_view(),       name="phc-escalate"),
    path("phc/walk-in/",                      PHCWalkInView.as_view(),         name="phc-walk-in"),

    # ── PHC Admin ─────────────────────────────────────────────────────────────
    path("phc/profile/",                      PHCProfileView.as_view(),        name="phc-profile"),
    path("phc/staff/",                        PHCStaffListView.as_view(),      name="phc-staff-list"),
    path("phc/staff/<uuid:pk>/",              PHCStaffDetailView.as_view(),    name="phc-staff-detail"),

    # ── FMC Portal (staff + admin) ────────────────────────────────────────────
    path("fmc/cases/",                        FMCCaseListView.as_view(),       name="fmc-case-list"),
    path("fmc/cases/<uuid:pk>/",              FMCCaseDetailView.as_view(),     name="fmc-case-detail"),
    path("fmc/cases/<uuid:pk>/assign/",       FMCAssignClinicianView.as_view(),name="fmc-case-assign"),
    path("fmc/cases/<uuid:pk>/discharge/",    FMCDischargeCaseView.as_view(),  name="fmc-case-discharge"),

    # ── FMC Admin ─────────────────────────────────────────────────────────────
    path("fmc/profile/",                      FMCProfileView.as_view(),        name="fmc-profile"),
    path("fmc/staff/",                        FMCStaffListView.as_view(),      name="fmc-staff-list"),
    path("fmc/staff/<uuid:pk>/",              FMCStaffDetailView.as_view(),    name="fmc-staff-detail"),
    path("fmc/clinicians/",                   FMCClinicianListView.as_view(),  name="fmc-clinician-list"),
    path("fmc/clinicians/<uuid:pk>/",         FMCClinicianDetailView.as_view(),name="fmc-clinician-detail"),
    path("fmc/clinicians/<uuid:pk>/verify/",  FMCVerifyClinicianView.as_view(),name="fmc-clinician-verify"),

    # ── Clinician ─────────────────────────────────────────────────────────────
    path("clinician/cases/",                  ClinicianCaseListView.as_view(), name="clinician-case-list"),
    path("clinician/cases/<uuid:pk>/",        ClinicianCaseDetailView.as_view(),name="clinician-case-detail"),
    path("clinician/profile/",                ClinicianProfileView.as_view(),  name="clinician-profile"),

    # ── Patient ───────────────────────────────────────────────────────────────
    path("change-request/",                   ChangeRequestListView.as_view(), name="change-request-list"),
    path("change-request/<uuid:pk>/",         ChangeRequestDetailView.as_view(),name="change-request-detail"),

    # ── Platform Admin ────────────────────────────────────────────────────────
    # path("admin/phc/",                        HCCAdminListView.as_view(),      name="admin-phc-list"),
    # path("admin/phc/<uuid:pk>/",              HCCAdminDetailView.as_view(),    name="admin-phc-detail"),
    # path("admin/fmc/",                        FHCAdminListView.as_view(),      name="admin-fmc-list"),
    # path("admin/fmc/<uuid:pk>/",              FHCAdminDetailView.as_view(),    name="admin-fmc-detail"),
]