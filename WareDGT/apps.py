from django.apps import AppConfig


class WaredgtConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'WareDGT'

    def ready(self):
        # Import signal handlers
        from . import signals  # noqa: F401

