"""
apps/notifications/serializers.py
"""

from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    patient_id = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "notification_type",
            "priority",
            "title",
            "body",
            "data",
            "patient_id",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_patient_id(self, obj):
        return obj.data.get("patient_id") if obj.data else None
