from django.contrib.gis.db import models

from jejak.models.abstracts import (
    ForeignKeyCompositeIdentifierDetailAbstractModel,
    RangeAbstractModel,
)


class Trip(ForeignKeyCompositeIdentifierDetailAbstractModel):
    bus = models.ForeignKey(
        to="jejak.Bus",
        on_delete=models.PROTECT,
    )
    provider = models.ForeignKey(
        to="jejak.Provider",
        on_delete=models.PROTECT,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["identifier", "bus", "provider"],
                name="%(app_label)s_%(class)s_trip_bus_provider_unique",
            )
        ]


class TripRange(RangeAbstractModel):
    trip = models.ForeignKey(
        "jejak.Trip",
        on_delete=models.PROTECT,
    )


class Location(models.Model):
    dt_received = models.DateTimeField(editable=False)
    dt_gps = models.DateTimeField(editable=False)
    location = models.PointField()
    dir = models.CharField(max_length=5, null=True, blank=True)
    speed = models.PositiveSmallIntegerField(null=True, blank=True)
    angle = models.PositiveSmallIntegerField(null=True, blank=True)
    bus = models.ForeignKey(
        to="jejak.Bus",
        on_delete=models.PROTECT,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dt_received", "dt_gps", "bus"],
                name="%(app_label)s_%(class)s_unique_received_gps_time_bus",
            ),
        ]
