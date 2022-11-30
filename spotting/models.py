from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BTreeIndex
from django.db.models import F, Q
from model_utils.models import TimeStampedModel

from generic.models import WebLocationModel
from operation.enums import VehicleStatus
from spotting.enums import SpottingEventType


class LocationEvent(WebLocationModel):
    event = models.ForeignKey(
        to="spotting.Event",
        on_delete=models.CASCADE,
    )

    # Override to be not null
    location = models.PointField(
        blank=False,
        null=False,
    )


class Event(TimeStampedModel):
    spotting_date = models.DateField()
    reporter = models.ForeignKey(
        to="common.User",
        on_delete=models.CASCADE,
    )
    vehicle = models.ForeignKey(
        to="operation.Vehicle",
        on_delete=models.CASCADE,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )
    status = models.CharField(
        max_length=32,
        choices=VehicleStatus.choices,
    )

    type = models.CharField(
        max_length=32,
        choices=SpottingEventType.choices,
    )

    is_anonymous = models.BooleanField(default=False)

    origin_station = models.ForeignKey(
        to="operation.Station",
        null=True,
        default=None,
        blank=True,
        on_delete=models.PROTECT,
        related_name="origin_station_event",
    )
    destination_station = models.ForeignKey(
        to="operation.Station",
        null=True,
        default=None,
        blank=True,
        on_delete=models.PROTECT,
        related_name="destination_station_event",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(
                    Q(type=SpottingEventType.BETWEEN_STATIONS)
                    & Q(origin_station__isnull=False)
                    & Q(destination_station__isnull=False)
                    & ~Q(origin_station=F("destination_station"))
                    & ~Q(destination_station=F("origin_station"))
                )
                | Q(
                    Q(type=SpottingEventType.AT_STATION)
                    & Q(origin_station__isnull=False)
                    & Q(destination_station__isnull=True)
                )
                | Q(
                    Q(
                        type__in=[
                            SpottingEventType.DEPOT,
                            SpottingEventType.JUST_SPOTTING,
                            SpottingEventType.LOCATION,
                        ]
                    )
                    & Q(origin_station__isnull=True)
                    & Q(destination_station__isnull=True)
                ),
                name="%(app_label)s_%(class)s_value_relevant",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["vehicle", "-spotting_date"]),
        ]


class EventRead(TimeStampedModel):
    reader = models.ForeignKey(
        to="common.User",
        on_delete=models.CASCADE,
    )
    event = models.ForeignKey(
        to="spotting.Event",
        on_delete=models.CASCADE,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("reader_id", "event_id"),
                name="%(app_label)s_%(class)s_reader_event_unique",
            ),
        ]
