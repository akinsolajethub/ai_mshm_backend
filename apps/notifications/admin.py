from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display   = ("recipient", "notification_type", "priority", "title", "is_read", "created_at")
    list_filter    = ("notification_type", "priority", "is_read")
    search_fields  = ("recipient__email", "title", "body")
    raw_id_fields  = ("recipient",)
    readonly_fields = ("created_at", "read_at")
    ordering       = ("-created_at",)
