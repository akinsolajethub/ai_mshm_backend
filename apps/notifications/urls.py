"""
apps/notifications/urls.py
Base prefix: /api/v1/notifications/
"""
from django.urls import path
from .views import (
    NotificationListView,
    NotificationUnreadCountView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
    NotificationDeleteView,
)

app_name = "notifications"

urlpatterns = [
    path("",                        NotificationListView.as_view(),       name="list"),
    path("unread-count/",           NotificationUnreadCountView.as_view(), name="unread-count"),
    path("mark-all-read/",          NotificationMarkAllReadView.as_view(), name="mark-all-read"),
    path("<int:pk>/read/",          NotificationMarkReadView.as_view(),    name="mark-read"),
    path("<int:pk>/",               NotificationDeleteView.as_view(),      name="delete"),
]
