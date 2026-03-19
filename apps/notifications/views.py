"""
apps/notifications/views.py
────────────────────────────
REST endpoints for in-app notifications.
Real-time push happens via WebSocket (consumers.py).
"""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from core.responses import success_response, error_response
from core.pagination import StandardResultsPagination
from .models import Notification
from .serializers import NotificationSerializer


class NotificationListView(APIView):
    """
    GET  /api/v1/notifications/        → paginated list (newest first)
    Query params: ?unread_only=true
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Notifications"], summary="List in-app notifications")
    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user)

        if request.query_params.get("unread_only", "").lower() == "true":
            qs = qs.filter(is_read=False)

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = NotificationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class NotificationUnreadCountView(APIView):
    """GET /api/v1/notifications/unread-count/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Notifications"], summary="Get unread notification count")
    def get(self, request):
        count = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count()
        return success_response(data={"unread_count": count})


class NotificationMarkReadView(APIView):
    """PATCH /api/v1/notifications/<id>/read/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Notifications"], summary="Mark a notification as read")
    def patch(self, request, pk: int):
        try:
            notif = Notification.objects.get(pk=pk, recipient=request.user)
        except Notification.DoesNotExist:
            return error_response("Notification not found.", http_status=404)
        notif.mark_read()
        return success_response(data=NotificationSerializer(notif).data, message="Marked as read.")


class NotificationMarkAllReadView(APIView):
    """PATCH /api/v1/notifications/mark-all-read/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Notifications"], summary="Mark all notifications as read")
    def patch(self, request):
        qs = Notification.objects.filter(recipient=request.user, is_read=False)
        count = qs.count()
        qs.update(is_read=True, read_at=timezone.now())
        return success_response(data={"marked_count": count}, message="All notifications marked as read.")


class NotificationDeleteView(APIView):
    """DELETE /api/v1/notifications/<id>/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Notifications"], summary="Delete a notification")
    def delete(self, request, pk: int):
        try:
            notif = Notification.objects.get(pk=pk, recipient=request.user)
        except Notification.DoesNotExist:
            return error_response("Notification not found.", http_status=404)
        notif.delete()
        return success_response(message="Notification deleted.", http_status=204)
