from django.db import models


class TemporaryMediaType(models.TextChoices):
    # Which kind of object this media connects to.
    # Will be used as a source of logic
    # Format: <app>_<model>_<field - if multiple fields>
    SPOTTING_EVENT = "SPOTTING_EVENT"
    INCIDENT_CALENDAR_INCIDENT = "INCIDENT_CALENDAR_INCIDENT"
