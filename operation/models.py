from colorfield.fields import ColorField
from django.contrib.gis.db import models
from model_utils.models import TimeStampedModel

from operation.enums import AssetStatus, AssetType, VehicleStatus


class Line(TimeStampedModel):
    code = models.CharField(
        unique=True,
        null=False,
        blank=False,
        max_length=32,
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
    vehicles = models.ManyToManyField(
        to="operation.Vehicle",
        through="operation.VehicleLine",
        related_name="vehicle_lines",
    )

    def __str__(self) -> str:
        return f"{self.id} - {self.code}"

    class Meta:
        ordering = ["code"]


class Station(TimeStampedModel):
    display_name = models.TextField()
    location = models.PointField(
        null=True,
        blank=True,
        default=None,
    )
    lines = models.ManyToManyField(
        to="operation.Line",
        through="operation.StationLine",
    )
    medias = models.ManyToManyField(
        to="common.Media",
        through="operation.StationMedia",
    )

    def __str__(self) -> str:
        return f"{self.display_name}"

    class Meta:
        ordering = ["display_name"]


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
        related_name="station_lines",
    )
    display_name = models.TextField()
    internal_representation = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        default=None,
    )

    def __str__(self) -> str:
        display_name = (
            self.station.display_name
            if self.display_name is None
            else self.display_name
        )
        representation = (
            f" ({self.internal_representation})" if self.internal_representation else ""
        )
        return f"{self.id} - {display_name} {representation}"

    class Meta:
        ordering = ["internal_representation"]


class Asset(TimeStampedModel):
    officialid = models.CharField(
        default=None,
        null=True,
        blank=True,
        max_length=64,
    )
    station = models.ForeignKey(
        to="operation.Station",
        on_delete=models.PROTECT,
        related_name="assets",
    )
    short_description = models.CharField(
        default="",
        blank=True,
        null=False,
        max_length=96,
    )
    long_description = models.TextField(
        default="",
        blank=True,
        null=False,
    )
    asset_type = models.TextField(choices=AssetType.choices)
    medias = models.ManyToManyField(
        to="common.Media",
        through="operation.AssetMedia",
    )
    status = models.CharField(
        max_length=32,
        choices=AssetStatus.choices,
    )

    class Meta:
        ordering = ["officialid"]


class AssetMedia(models.Model):
    asset = models.ForeignKey(
        "operation.Asset",
        on_delete=models.PROTECT,
    )
    media = models.ForeignKey(
        "common.Media",
        on_delete=models.PROTECT,
    )


class Vehicle(models.Model):
    identification_no = models.CharField(
        max_length=16,
        null=False,
    )
    nickname = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        default=None,
    )
    vehicle_type = models.ForeignKey(
        to="operation.VehicleType",
        on_delete=models.PROTECT,
        related_name="vehicles",
    )
    status = models.CharField(
        max_length=32,
        choices=VehicleStatus.choices,
    )
    lines = models.ManyToManyField(
        to="operation.Line",
        through="operation.VehicleLine",
        related_name="line_vehicles",
    )

    notes = models.TextField(
        default="",
        blank=True,
    )
    in_service_since = models.DateField(
        default=None,
        null=True,
        blank=True,
    )

    def __str__(self) -> str:
        return f"{self.identification_no}"

    class Meta:
        ordering = ["identification_no"]


class VehicleLine(models.Model):
    vehicle = models.ForeignKey(
        to="operation.Vehicle",
        null=False,
        blank=False,
        on_delete=models.PROTECT,
    )
    line = models.ForeignKey(
        to="operation.Line",
        null=False,
        blank=False,
        on_delete=models.PROTECT,
    )


class VehicleType(models.Model):
    internal_name = models.CharField(
        max_length=16,
        blank=True,
        null=True,
        default=None,
        unique=True,
    )
    display_name = models.CharField(
        max_length=64,
        null=False,
        blank=False,
    )
    description = models.TextField(
        default="",
        blank=True,
    )

    def __str__(self) -> str:
        display_name = (
            self.internal_name if self.internal_name else self.display_name[:16]
        )

        return f"{self.id} - {display_name}"
