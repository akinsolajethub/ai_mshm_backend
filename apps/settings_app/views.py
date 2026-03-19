"""
apps/settings_app/views.py
───────────────────────────
All settings endpoints. Three groups:
  1. Notification Preferences
  2. Connected Devices
  3. Privacy Settings
"""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from core.throttles import SensitiveEndpointThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.responses import success_response, created_response, error_response
from .models import NotificationPreferences, ConnectedDevice, PrivacySettings
from .serializers import (
    NotificationPreferencesSerializer,
    ConnectedDeviceSerializer,
    ConnectDeviceSerializer,
    UpdateDeviceSerializer,
    PrivacySettingsSerializer,
)


class NotificationPreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_prefs(self, user):
        prefs, _ = NotificationPreferences.objects.get_or_create(user=user)
        return prefs

    @extend_schema(tags=["Settings"], summary="Get notification preferences")
    def get(self, request):
        prefs = self._get_prefs(request.user)
        return success_response(data=NotificationPreferencesSerializer(prefs).data)

    @extend_schema(tags=["Settings"], request=NotificationPreferencesSerializer,
                   summary="Update notification preferences")
    def patch(self, request):
        prefs = self._get_prefs(request.user)
        serializer = NotificationPreferencesSerializer(prefs, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Notification preferences saved.")


@extend_schema(operation_id="device_list")
class ConnectedDeviceListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Settings"], summary="List connected devices")
    def get(self, request):
        devices = ConnectedDevice.objects.filter(user=request.user, is_connected=True)
        return success_response(data=ConnectedDeviceSerializer(devices, many=True).data)

    @extend_schema(tags=["Settings"], request=ConnectDeviceSerializer,
                   summary="Connect a new wearable device")
    def post(self, request):
        serializer = ConnectDeviceSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        device = serializer.save(user=request.user)
        return created_response(
            data=ConnectedDeviceSerializer(device).data,
            message=f"{device.get_device_type_display()} connected successfully.",
        )


@extend_schema(operation_id="device_list")
class ConnectedDeviceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_device(self, pk, user):
        try:
            return ConnectedDevice.objects.get(pk=pk, user=user)
        except ConnectedDevice.DoesNotExist:
            return None

    @extend_schema(tags=["Settings"], summary="Get a connected device")
    def get(self, request, pk):
        device = self._get_device(pk, request.user)
        if not device:
            return error_response("Device not found.", http_status=404)
        return success_response(data=ConnectedDeviceSerializer(device).data)

    @extend_schema(tags=["Settings"], request=UpdateDeviceSerializer,
                   summary="Update device sync settings")
    def patch(self, request, pk):
        device = self._get_device(pk, request.user)
        if not device:
            return error_response("Device not found.", http_status=404)
        serializer = UpdateDeviceSerializer(device, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=ConnectedDeviceSerializer(device).data,
                                message="Device settings updated.")

    @extend_schema(tags=["Settings"], summary="Disconnect a device")
    def delete(self, request, pk):
        device = self._get_device(pk, request.user)
        if not device:
            return error_response("Device not found.", http_status=404)
        device.is_connected = False
        device.save(update_fields=["is_connected", "updated_at"])
        return success_response(message=f"{device.get_device_type_display()} disconnected.")


class SyncDeviceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Settings"], summary="Trigger manual device sync")
    def post(self, request, pk):
        try:
            device = ConnectedDevice.objects.get(pk=pk, user=request.user, is_connected=True)
        except ConnectedDevice.DoesNotExist:
            return error_response("Device not found.", http_status=404)
        device.last_synced_at = timezone.now()
        device.save(update_fields=["last_synced_at", "updated_at"])
        return success_response(data=ConnectedDeviceSerializer(device).data,
                                message="Sync initiated successfully.")


class PrivacySettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_privacy(self, user):
        prefs, _ = PrivacySettings.objects.get_or_create(user=user)
        return prefs

    @extend_schema(tags=["Settings"], summary="Get privacy settings")
    def get(self, request):
        prefs = self._get_privacy(request.user)
        return success_response(data=PrivacySettingsSerializer(prefs).data)

    @extend_schema(tags=["Settings"], request=PrivacySettingsSerializer,
                   summary="Update privacy and consent settings")
    def patch(self, request):
        prefs = self._get_privacy(request.user)
        serializer = PrivacySettingsSerializer(prefs, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Privacy settings saved.")


class ExportDataView(APIView):
    throttle_classes = [SensitiveEndpointThrottle]
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Settings"], summary="Request a full data export")
    def post(self, request):
        # TODO: dispatch Celery task to compile and email export
        return success_response(
            message="Your data export has been queued. You will receive a download link by email."
        )


class DeleteAccountView(APIView):
    throttle_classes = [SensitiveEndpointThrottle]
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Settings"], summary="Permanently delete account and all data")
    def delete(self, request):
        request.user.delete()
        return success_response(message="Account permanently deleted.")
