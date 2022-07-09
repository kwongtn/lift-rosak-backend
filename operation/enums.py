from django.db import models


class AssetType(models.TextChoices):
    ESCALATOR = "ESCALATOR"
    LIFT = "LIFT"


class AssetStatus(models.TextChoices):
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    IN_OPERATION = "IN_OPERATION"
