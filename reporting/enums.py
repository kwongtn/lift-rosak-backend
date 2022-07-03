from django.db import models


class ReportType(models.TextChoices):
    COSMETIC_BREAKDOWN = "COSMETIC_BREAKDOWN"
    FUNCTIONAL_BREAKDOWN = "FUNCTIONAL_BREAKDOWN"
