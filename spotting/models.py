from django.contrib.gis.db import models
from django.db.models import Q
from model_utils.models import TimeStampedModel

from spotting.enums import SpottingEventType, VehicleStatus


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
                ),
                name="between_station_spotting_type_has_origin_destination_station",
            ),
            models.CheckConstraint(
                check=Q(
                    Q(type=SpottingEventType.BETWEEN_STATIONS)
                    & Q(location__isnull=True)
                ),
                name="between_station_spotting_type_has_no_location",
            ),
            models.CheckConstraint(
                check=Q(
                    Q(type=SpottingEventType.LOCATION)
                    & Q(origin_station__isnull=True)
                    & Q(destination_station__isnull=True)
                ),
                name="location_spotting_type_has_no_origin_destination_station",
            ),
            models.CheckConstraint(
                check=Q(Q(type=SpottingEventType.LOCATION) & Q(location__isnull=True)),
                name="location_spotting_type_has_location",
            ),
            models.CheckConstraint(
                check=Q(
                    Q(type=SpottingEventType.DEPOT)
                    & Q(origin_station__isnull=True)
                    & Q(destination_station__isnull=True)
                    & Q(location__isnull=True)
                ),
                name="depot_spotting_type_has_no_origin_destination_station_location",
            ),
        ]
