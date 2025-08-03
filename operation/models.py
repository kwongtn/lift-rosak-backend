from colorfield.fields import ColorField
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BTreeIndex
from django_choices_field import TextChoicesField
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from operation.enums import (
    AssetStatus,
    AssetType,
    LineStatus,
    VehicleStatus,
    WheelStatus,
)


class Line(TimeStampedModel):
    official_numbering = models.CharField(
        null=True,
        blank=True,
        default=None,
        max_length=5,
    )
    code = models.CharField(
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
    calendar_incidents = models.ManyToManyField(
        to="incident.CalendarIncident",
        # through="operation.VehicleLine",
        # related_name="lines",
    )
    status = TextChoicesField(
        max_length=32,
        choices_enum=LineStatus,
        default=LineStatus.ACTIVE,
    )
    telegram_channel_id = models.TextField(
        unique=True,
        default=None,
        null=True,
        blank=True,
    )

    def __str__(self) -> str:
        if self.official_numbering:
            return f"{self.official_numbering} - {self.display_name}"
        else:
            return f"ID:{self.id} - {self.code}"

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                name="%(app_label)s_%(class)s_unique_line_code",
            ),
            models.UniqueConstraint(
                fields=["display_name"],
                name="%(app_label)s_%(class)s_unique_display_name",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["code"]),
            BTreeIndex(fields=["display_name"]),
            BTreeIndex(fields=["display_color"]),
        ]


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
        constraints = [
            models.UniqueConstraint(
                fields=["display_name"],
                name="%(app_label)s_%(class)s_unique_display_name",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["display_name"]),
        ]


class StationMedia(models.Model):
    station = models.ForeignKey(
        "operation.Station",
        on_delete=models.PROTECT,
    )
    media = models.ForeignKey(
        "common.Media",
        on_delete=models.PROTECT,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["station", "media"],
                name="%(app_label)s_%(class)s_unique_station_media",
            ),
        ]


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
        null=True,
        blank=True,
        default=None,
    )

    override_internal_representation_constraint = models.BooleanField(default=False)

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
        constraints = [
            models.UniqueConstraint(
                fields=["station", "line"],
                name="%(app_label)s_%(class)s_unique_station_line",
            ),
            models.UniqueConstraint(
                fields=["line", "internal_representation"],
                name="%(app_label)s_%(class)s_unique_line_internal_representation",
                condition=models.Q(internal_representation__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["internal_representation"],
                name="%(app_label)s_%(class)s_unique_internal_representation",
                condition=models.Q(
                    models.Q(override_internal_representation_constraint=False)
                    & models.Q(internal_representation__isnull=False)
                ),
            ),
        ]
        indexes = [
            BTreeIndex(fields=["display_name"]),
            BTreeIndex(fields=["internal_representation"]),
        ]


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

    history = HistoricalRecords()

    class Meta:
        ordering = ["officialid"]
        constraints = [
            models.UniqueConstraint(
                fields=["officialid"],
                name="%(app_label)s_%(class)s_unique_officialid",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["short_description"]),
            BTreeIndex(fields=["long_description"]),
        ]


class AssetMedia(models.Model):
    asset = models.ForeignKey(
        "operation.Asset",
        on_delete=models.PROTECT,
    )
    media = models.ForeignKey(
        "common.Media",
        on_delete=models.PROTECT,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "media"],
                name="%(app_label)s_%(class)s_unique_asset_media",
            ),
        ]


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

    wheel_status = TextChoicesField(
        choices_enum=WheelStatus,
        max_length=16,
        blank=True,
        null=True,
        default=None,
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

    history = HistoricalRecords()

    def __str__(self) -> str:
        return f"{self.identification_no}_{','.join(self.lines.values_list('code', flat=True))}"

    class Meta:
        ordering = ["identification_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["identification_no", "vehicle_type"],
                name="%(app_label)s_%(class)s_unique_identification_no_vehicle_type",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["identification_no"]),
        ]


class VehicleLine(models.Model):
    vehicle = models.ForeignKey(
        to="operation.Vehicle",
        null=False,
        blank=False,
        on_delete=models.CASCADE,
    )
    line = models.ForeignKey(
        to="operation.Line",
        null=False,
        blank=False,
        on_delete=models.CASCADE,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle", "line"],
                name="%(app_label)s_%(class)s_unique_vehicle_line",
            ),
        ]


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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["internal_name"],
                name="%(app_label)s_%(class)s_unique_internal_name",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["internal_name"]),
            BTreeIndex(fields=["display_name"]),
        ]


# class VehicleSnapshot(TimeStampedModel):
#     vehicle = models.ForeignKey(
#         to="operation.Vehicle",
#         null=False,
#         blank=False,
#         on_delete=models.CASCADE,
#         related_name="snapshots",
#         related_query_name="snapshot",
#         db_constraint=False,
#     )
