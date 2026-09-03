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


class CalendarIncidentStatus(models.TextChoices):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    LIVE = "live"
    REJECTED = "rejected"
    # Only ever SET on chronologies (mark-for-delete flow). Never wired into
    # incident approval flows — incidents never carry this status.
    PENDING_DELETION = "pending_deletion"


class SocialMediaLinkStatus(models.TextChoices):
    LIVE = "live"
    PENDING_APPROVAL = "pending_approval"
