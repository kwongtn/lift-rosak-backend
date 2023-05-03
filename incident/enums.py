from django.db import models


class IncidentSeverity(models.TextChoices):
    CRITICAL = "CRITICAL"
    TRIVIA = "TRIVIA"
    STATUS = "STATUS"


class CalendarIncidentSeverity(models.TextChoices):
    # Entire / parts of line being broken
    # Train crashes
    CRITICAL = "CRITICAL"

    # Single vehicle disruptions etc.
    MINOR = "MINOR"
    MILESTONE = "MILESTONE"
