"""
apps/settings_app/urls.py
Base prefix: /api/v1/settings/
"""
from django.urls import path
from .views import (
    NotificationPreferencesView,
    ConnectedDeviceListView,
    ConnectedDeviceDetailView,
    SyncDeviceView,
    PrivacySettingsView,
    ExportDataView,
    DeleteAccountView,
)

app_name = "settings_app"

urlpatterns = [
    path("notifications/",          NotificationPreferencesView.as_view(), name="notification-prefs"),
    path("devices/",                ConnectedDeviceListView.as_view(),     name="device-list"),
    path("devices/<int:pk>/",       ConnectedDeviceDetailView.as_view(),   name="device-detail"),
    path("devices/<int:pk>/sync/",  SyncDeviceView.as_view(),              name="device-sync"),
    path("privacy/",                PrivacySettingsView.as_view(),         name="privacy"),
    path("privacy/export/",         ExportDataView.as_view(),              name="export-data"),
    path("privacy/delete-account/", DeleteAccountView.as_view(),           name="delete-account"),
]
