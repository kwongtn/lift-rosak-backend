from colorfield.fields import ColorField
from django.contrib.gis.db import models
from model_utils.models import TimeStampedModel

from operation.enums import AssetType

# Create your models here.


class Line(TimeStampedModel):
    code = models.TextField(
        unique=True,
        null=False,
        blank=False,
    )
    display_name = models.TextField(
        null=False,
        blank=False,
    )
    display_color = ColorField(
        null=False,
        blank=False,
    )
    stations = models.ManyToManyField(
        to="operation.Station",
        through="operation.StationLine",
    )


class Station(TimeStampedModel):
    display_name = models.TextField()
    internal_representation = models.TextField(
        unique=True,
        null=True,
        default=None,
    )
    location = models.PointField()
    lines = models.ManyToManyField(
        to="operation.Line",
        through="operation.StationLine",
    )
    medias = models.ManyToManyField(
        to="common.Media",
        through="operation.StationMedia",
    )


class StationMedia(models.Model):
    station = models.ForeignKey(
        "operation.Station",
        on_delete=models.PROTECT,
    )
    media = models.ForeignKey(
        "common.Media",
        on_delete=models.PROTECT,
    )


class StationLine(TimeStampedModel):
    station = models.ForeignKey(
        to="operation.Station",
        on_delete=models.PROTECT,
    )
    line = models.ForeignKey(
        to="operation.Line",
        on_delete=models.PROTECT,
    )
    # display_name = models.TextField()


class Asset(TimeStampedModel):
    officialid = models.TextField()
    stations = models.ForeignKey(
        to="operation.Station",
        on_delete=models.PROTECT,
    )
    short_description = models.TextField(
        default="",
        null=False,
    )
    long_description = models.TextField(
        default="",
        null=False,
    )
    asset_type = models.TextField(choices=AssetType.choices)
    medias = models.ManyToManyField(
        to="common.Media",
        through="operation.AssetMedia",
    )


class AssetMedia(models.Model):
    asset = models.ForeignKey(
        "operation.Asset",
        on_delete=models.PROTECT,
    )
    media = models.ForeignKey(
        "common.Media",
        on_delete=models.PROTECT,
    )
