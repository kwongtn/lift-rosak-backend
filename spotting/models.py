from django.contrib.gis.db import models
from django.db.models import F, Q
from model_utils.models import TimeStampedModel

from operation.enums import VehicleStatus
from spotting.enums import SpottingEventType


class Event(TimeStampedModel):
    spotting_date = models.DateField()
    reporter = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )
    vehicle = models.ForeignKey(
        to="operation.Vehicle",
        on_delete=models.PROTECT,
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

    location = models.PointField(
        blank=True,
        null=True,
        default=None,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(
                    Q(type=SpottingEventType.BETWEEN_STATIONS)
                    & Q(origin_station__isnull=False)
                    & Q(destination_station__isnull=False)
                    & Q(location__isnull=True)
                    & ~Q(origin_station=F("destination_station"))
                    & ~Q(destination_station=F("origin_station"))
                )
                | Q(
                    Q(type=SpottingEventType.LOCATION)
                    & Q(origin_station__isnull=True)
                    & Q(destination_station__isnull=True)
                    & Q(location__isnull=False)
                )
                | Q(
                    Q(type=SpottingEventType.DEPOT)
                    & Q(origin_station__isnull=True)
                    & Q(destination_station__isnull=True)
                    & Q(location__isnull=True)
                ),
                name="%(app_label)s_%(class)s_value_relevant",
            ),
        ]
