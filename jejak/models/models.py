from django.contrib.gis.db import models

from jejak.models.abstracts import RangeAbstractModel


class Trip(models.Model):
    identifier = models.CharField(max_length=64, unique=True, null=False)
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
    dir = models.CharField(max_length=3)
    speed = models.PositiveSmallIntegerField()
    angle = models.PositiveSmallIntegerField()
    bus = models.ForeignKey(
        to="jejak.Bus",
        on_delete=models.PROTECT,
    )
