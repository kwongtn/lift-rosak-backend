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
    # A moderation decision: the row exists, but it must never appear in the
    # public feed — not by default and not through an explicit ``status``
    # filter, which is why the public-feed resolver excludes it after the
    # optional narrowing. Admins still see it in the console (they need it to
    # un-hide it) and the owner still sees their own submission under ``mine``;
    # everyone else sees nothing.
    HIDDEN = "hidden"


class IngestPlatform(models.TextChoices):
    # Source platform of an automatically ingested post stored on
    # SocialMediaLink. One member only — a second platform is a new enum
    # member plus its own fetch function, never a speculative placeholder.
    X = "x"


class PassengerStatus(models.TextChoices):
    NORMAL = "NORMAL"
    BUSY = "BUSY"
    CROWDED = "CROWDED"
    EXTREMELY_CROWDED = "EXTREMELY_CROWDED"
    BACKLOGGED = "BACKLOGGED"
    DELAYED = "DELAYED"
    DISRUPTED = "DISRUPTED"
