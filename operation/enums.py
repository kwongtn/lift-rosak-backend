from django.db import models


class AssetType(models.TextChoices):
    ESCALATOR = "ESCALATOR"
    LIFT = "LIFT"
