from colorfield.fields import ColorField
from django.db import models
from location_field.models.plain import PlainLocationField
from model_utils.models import TimeStampedModel

from operation.enums import AssetType

# Create your models here.


class Line(TimeStampedModel):
    code = models.TextField()
    display_name = models.TextField()
    display_color = ColorField()


class Station(TimeStampedModel):
    display_name = models.TextField()
    location = PlainLocationField()
    line = models.ManyToManyField(
        field="operation.Station",
        through="operation.StationLine",
    )


class StationLine(TimeStampedModel):
    station = models.ForeignKey(to="operation.Station")
    line = models.ForeignKey(to="opetation.Line")
    display_name = models.TextField()


class Asset(TimeStampedModel):
    officialid = models.TextField()
    station = models.ForeignKey(to="operation.Station")
    asset_type = models.TextField(choices=AssetType)
