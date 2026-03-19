"""
apps/notifications/models.py
─────────────────────────────
In-app notification model stored in MongoDB.
Push / email notifications are dispatched via Celery tasks.
"""
import uuid
from django.db import models
from django.conf import settings


class Notification(models.Model):

    class NotificationType(models.TextChoices):
        MORNING_CHECKIN  = "morning_checkin",  "Morning Check-in Reminder"
        EVENING_CHECKIN  = "evening_checkin",  "Evening Check-in Reminder"
        WEEKLY_PROMPT    = "weekly_prompt",    "Weekly Tool Prompt"
        PERIOD_ALERT     = "period_alert",     "Period Tracking Alert"
        RISK_UPDATE      = "risk_update",      "Risk Score Update"
        WEARABLE_SYNC    = "wearable_sync",    "Wearable Sync Reminder"
        SYSTEM           = "system",           "System Notification"
        CLINICIAN_MSG    = "clinician_msg",    "Message from Clinician"

    class Priority(models.TextChoices):
        LOW    = "low",    "Low"
        MEDIUM = "medium", "Medium"
        HIGH   = "high",   "High"

    id    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False) 
    recipient        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices)
    priority         = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)

    title   = models.CharField(max_length=255)
    body    = models.TextField()
    data    = models.JSONField(default=dict, blank=True)   # arbitrary extra payload

    is_read    = models.BooleanField(default=False, db_index=True)
    read_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        indexes = [
            models.Index(fields=["recipient", "is_read"]),
            models.Index(fields=["recipient", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.notification_type}] → {self.recipient.email}"

    def mark_read(self):
        from django.utils import timezone
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])
