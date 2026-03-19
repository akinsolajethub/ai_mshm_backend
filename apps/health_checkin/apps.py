from django.apps import AppConfig


class HealthCheckinConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name               = "apps.health_checkin"
    verbose_name       = "Health Check-ins"
