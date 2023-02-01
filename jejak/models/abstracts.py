from django.contrib.postgres.fields import DateTimeRangeField
from django.db import models


class RangeAbstractModel(models.Model):
    dt_range = DateTimeRangeField(default_bounds="[]")

    class Meta:
        abstract = True


class IdentifierDetailAbstractModel(models.Model):
    identifier = models.CharField(max_length=64, unique=True, null=False)
    details = models.TextField(default="", blank=True)

    class Meta:
        abstract = True


class ForeignKeyCompositeIdentifierDetailAbstractModel(IdentifierDetailAbstractModel):
    identifier = models.CharField(max_length=64, null=False)

    class Meta:
        abstract = True
