from django.db import models


class IncidentSeverity(models.TextChoices):
    CRITICAL = "CRITICAL"
    TRIVIA = "TRIVIA"
    STATUS = "STATUS"


class CalendarIncidentSeverity(models.TextChoices):
    # Entire / parts of line being broken
    # Train crashes
    MAJOR = "MAJOR"

    # Single vehicle disruptions etc.
    MINOR = "MINOR"
    OTHERS = "OTHERS"


class CalendarIncidentChronologyIndicator(models.TextChoices):
    GREEN = "GREEN"
    RED = "RED"
    BLUE = "BLUE"
    GRAY = "GRAY"
    LOADING = "LOADING"
