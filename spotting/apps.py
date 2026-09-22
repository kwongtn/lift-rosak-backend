import os

import firebase_admin
from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class SpottingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "spotting"

    def ready(self):
        credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if credentials and not os.path.isfile(credentials):
            raise ImproperlyConfigured(
                f"GOOGLE_APPLICATION_CREDENTIALS points at '{credentials}' which is not a file. "
                "If it is a directory, Docker created it because the host file was missing."
            )
        firebase_admin.initialize_app()
