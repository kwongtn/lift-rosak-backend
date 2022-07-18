import firebase_admin
from django.apps import AppConfig


class SpottingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "spotting"

    def ready(self):
        firebase_admin.initialize_app()
