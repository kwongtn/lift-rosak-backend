from django.db import models


class SpottingEventType(models.TextChoices):
    DEPOT = "DEPOT"
    LOCATION = "LOCATION"
    BETWEEN_STATIONS = "BETWEEN_STATIONS"
    JUST_SPOTTING = "JUST_SPOTTING"
