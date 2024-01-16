from django.db import models


class UserJejakTransactionCategory(models.TextChoices):
    MONTHLY_RENEWAL = "MONTHLY_RENEWAL"
    TOP_UP = "TOP_UP"

    COUNT_ROWS = "COUNT_ROWS"
    BUS_LOCATION_HISTORY = "BUS_LOCATION_HISTORY"
    BANDWIDTH = "BANDWIDTH"


class CreditType(models.TextChoices):
    PAID = "PAID"
    FREE = "FREE"
    SPECIAL = "SPECIAL"


class TemporaryMediaType(models.TextChoices):
    # Which kind of object this media connects to.
    # Will be used as a source of logic
    # Format: <app>_<model>_<field - if multiple fields>
    SPOTTING_EVENT = "SPOTTING_EVENT"
    INCIDENT_CALENDAR_INCIDENT = "INCIDENT_CALENDAR_INCIDENT"


class TemporaryMediaStatus(models.TextChoices):
    CLEARED = "CLEARED"
    TRUSTED_CLEARED = "TRUSTED_CLEARED"

    # Manual intervention that decides to allow media to pass
    OVERRIDE_CLEARED = "OVERRIDE_CLEARED"

    # Blocked due to some reason. Possible not passing NSFW check
    BLOCKED = "BLOCKED"

    PENDING = "PENDING"
    RETRY_ELAPSED = "RETRY_ELAPSED"
    INVALID_UPLOAD = "INVALID_UPLOAD"

    # Pending garbage collection
    TO_DELETE = "TO_DELETE"


class ClearanceType(models.TextChoices):
    TRUSTED_MEDIA_UPLOADER = "TRUSTED_MEDIA_UPLOADER"
