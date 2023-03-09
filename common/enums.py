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
