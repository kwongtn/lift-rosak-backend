from django.db import models


class SpottingEventType(models.TextChoices):
    DEPOT = "DEPOT"
    LOCATION = "LOCATION"
    BETWEEN_STATIONS = "BETWEEN_STATIONS"
    JUST_SPOTTING = "JUST_SPOTTING"
    AT_STATION = "AT_STATION"


class SpottingVehicleStatus(models.TextChoices):
    IN_SERVICE = "IN_SERVICE"
    NOT_IN_SERVICE = "NOT_IN_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"
    TESTING = "TESTING"

    NOT_SPOTTED = "NOT_SPOTTED"
    MARRIED = "MARRIED"
    UNKNOWN = "UNKNOWN"


class SpottingWheelStatus(models.TextChoices):
    FRESH = "FRESH"
    NEAR_PERFECT = "NEAR_PERFECT"
    FLAT = "FLAT"
    WORN_OUT = "WORN_OUT"
    WORRYING = "WORRYING"
