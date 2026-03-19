from django.apps import AppConfig


class SettingsAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.settings_app"
    verbose_name = "User Settings"

    def ready(self):
        import apps.settings_app.signals  # noqa
