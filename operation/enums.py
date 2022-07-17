from django.db import models


class AssetType(models.TextChoices):
    ESCALATOR = "ESCALATOR"
    LIFT = "LIFT"


class AssetStatus(models.TextChoices):
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    IN_OPERATION = "IN_OPERATION"


class VehicleStatus(models.TextChoices):
    IN_SERVICE = "IN_SERVICE"
    NOT_SPOTTED = "NOT_SPOTTED"
    DECOMMISSIONED = "DECOMMISSIONED"
    TESTING = "TESTING"
    UNKNOWN = "UNKNOWN"
