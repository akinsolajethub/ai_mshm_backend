"""
apps/settings_app/models.py
────────────────────────────
All user settings documents.
Mirrors the Flutter Settings screens exactly.
"""
import uuid
from django.db import models
from django.conf import settings



# ── Notification Preferences ──────────────────────────────────────────────────

class NotificationPreferences(models.Model):
    """One-to-one per user. Mirrors NotificationSettingsScreen."""
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False) 
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs")

    # Check-in reminder times (stored as "HH:MM")
    morning_time = models.CharField(max_length=5, default="08:00")
    evening_time = models.CharField(max_length=5, default="20:00")

    # Notification type toggles
    morning_checkin_enabled  = models.BooleanField(default=True)
    evening_checkin_enabled  = models.BooleanField(default=True)
    weekly_prompts_enabled   = models.BooleanField(default=True)
    period_alerts_enabled    = models.BooleanField(default=True)
    risk_score_updates_enabled = models.BooleanField(default=True)
    wearable_sync_reminders  = models.BooleanField(default=False)

    # Quiet hours
    do_not_disturb = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Preferences"

    def __str__(self):
        return f"NotifPrefs({self.user.email})"


# ── Connected Devices ─────────────────────────────────────────────────────────

class ConnectedDevice(models.Model):
    """Each row represents one linked wearable device."""

    class DeviceType(models.TextChoices):
        APPLE_WATCH = "apple_watch", "Apple Watch"
        FITBIT      = "fitbit",      "Fitbit"
        GARMIN      = "garmin",      "Garmin"
        OURA_RING   = "oura_ring",   "Oura Ring"
        WHOOP       = "whoop",       "WHOOP"

    class SyncFrequency(models.TextChoices):
        FIVE_MIN    = "5min",   "Every 5 min"
        FIFTEEN_MIN = "15min",  "Every 15 min"
        THIRTY_MIN  = "30min",  "Every 30 min"
        ONE_HOUR    = "1h",     "Every hour"
        TWO_HOURS   = "2h",     "Every 2 hours"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False) 
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="connected_devices")
    device_type = models.CharField(max_length=20, choices=DeviceType.choices)
    device_name = models.CharField(max_length=100, blank=True)  # e.g. "Apple Watch Series 9"

    is_connected     = models.BooleanField(default=True)
    background_sync  = models.BooleanField(default=True)
    sync_frequency   = models.CharField(max_length=10, choices=SyncFrequency.choices, default=SyncFrequency.FIFTEEN_MIN)

    last_synced_at   = models.DateTimeField(null=True, blank=True)
    data_quality_pct = models.PositiveSmallIntegerField(default=0)  # 0–100

    # OAuth / API tokens stored encrypted (placeholder — use django-encrypted-model-fields in prod)
    access_token  = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "device_type")]
        verbose_name = "Connected Device"

    def __str__(self):
        return f"{self.device_type} → {self.user.email}"


# ── Data & Privacy ────────────────────────────────────────────────────────────

class PrivacySettings(models.Model):
    """One-to-one per user. Mirrors DataPrivacyScreen."""
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False) 
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="privacy_settings")

    # Data layer visibility
    behavioral_data_enabled = models.BooleanField(default=True)
    wearable_data_enabled   = models.BooleanField(default=True)
    clinical_data_enabled   = models.BooleanField(default=True)

    # Consent
    share_with_clinician     = models.BooleanField(default=True)
    anonymized_research      = models.BooleanField(default=False)
    model_improvement        = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Privacy Settings"

    def __str__(self):
        return f"PrivacySettings({self.user.email})"
