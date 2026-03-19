"""
apps/settings_app/serializers.py
"""
import re
from rest_framework import serializers
from .models import NotificationPreferences, ConnectedDevice, PrivacySettings


class NotificationPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model  = NotificationPreferences
        fields = [
            "morning_time", "evening_time",
            "morning_checkin_enabled", "evening_checkin_enabled",
            "weekly_prompts_enabled", "period_alerts_enabled",
            "risk_score_updates_enabled", "wearable_sync_reminders",
            "do_not_disturb", "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def _validate_time_format(self, value):
        if not re.match(r"^\d{2}:\d{2}$", value):
            raise serializers.ValidationError("Time must be in HH:MM format.")
        h, m = map(int, value.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise serializers.ValidationError("Invalid time value.")
        return value

    def validate_morning_time(self, value):
        return self._validate_time_format(value)

    def validate_evening_time(self, value):
        return self._validate_time_format(value)


class ConnectedDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ConnectedDevice
        fields = [
            "id", "device_type", "device_name",
            "is_connected", "background_sync", "sync_frequency",
            "last_synced_at", "data_quality_pct", "connected_at", "updated_at",
        ]
        read_only_fields = ["id", "last_synced_at", "data_quality_pct", "connected_at", "updated_at"]


class ConnectDeviceSerializer(serializers.ModelSerializer):
    """Used when connecting a new device."""
    class Meta:
        model  = ConnectedDevice
        fields = ["device_type", "device_name", "sync_frequency", "background_sync"]

    def validate_device_type(self, value):
        user = self.context["request"].user
        if ConnectedDevice.objects.filter(user=user, device_type=value, is_connected=True).exists():
            raise serializers.ValidationError("This device is already connected.")
        return value


class UpdateDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ConnectedDevice
        fields = ["device_name", "sync_frequency", "background_sync"]


class PrivacySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PrivacySettings
        fields = [
            "behavioral_data_enabled", "wearable_data_enabled", "clinical_data_enabled",
            "share_with_clinician", "anonymized_research", "model_improvement",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]
