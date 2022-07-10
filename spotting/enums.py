from django.db import models


class SpottingEventType(models.TextChoices):
    DEPOT = "DEPOT"
    LOCATION = "LOCATION"
    BETWEEN_STATIONS = "BETWEEN_STATIONS"


class VehicleStatus(models.TextChoices):
    IN_SERVICE = "IN_SERVICE"
    NOT_SPOTTED = "NOT_SPOTTED"
    DECOMMISSIONED = "DECOMMISSIONED"
    TESTING = "TESTING"
    UNKNOWN = "UNKNOWN"
