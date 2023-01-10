from django.db import models

from jejak.models.abstracts import IdentifierDetailAbstractModel, RangeAbstractModel


class BusType(models.Model):
    title = models.TextField(default="", blank=True)
    description = models.TextField(default="", blank=True)


class Bus(IdentifierDetailAbstractModel):
    type = models.ForeignKey(
        "jejak.BusType", on_delete=models.CASCADE, null=True, blank=True
    )


class Accessibility(IdentifierDetailAbstractModel):
    pass


class AccessibilityBusRange(RangeAbstractModel):
    accessibility = models.ForeignKey(
        "jejak.Accessibility",
        on_delete=models.PROTECT,
    )
    bus = models.ForeignKey(
        "jejak.Bus",
        on_delete=models.PROTECT,
    )


class EngineStatus(IdentifierDetailAbstractModel):
    pass


class EngineStatusBusRange(RangeAbstractModel):
    engine_status = models.ForeignKey(
        "jejak.EngineStatus",
        on_delete=models.PROTECT,
    )
    bus = models.ForeignKey(
        "jejak.Bus",
        on_delete=models.PROTECT,
    )


class TripRev(IdentifierDetailAbstractModel):
    pass


class TripRevBusRange(RangeAbstractModel):
    trip_rev = models.ForeignKey(
        "jejak.TripRev",
        on_delete=models.PROTECT,
    )
    bus = models.ForeignKey(
        "jejak.Bus",
        on_delete=models.PROTECT,
    )


class Route(IdentifierDetailAbstractModel):
    pass


class RouteBusRange(RangeAbstractModel):
    route = models.ForeignKey(
        "jejak.Route",
        on_delete=models.PROTECT,
    )
    bus = models.ForeignKey(
        "jejak.Bus",
        on_delete=models.PROTECT,
    )


class BusStop(IdentifierDetailAbstractModel):
    pass


class BusStopBusRange(RangeAbstractModel):
    bus_stop = models.ForeignKey(
        "jejak.BusStop",
        on_delete=models.PROTECT,
    )
    bus = models.ForeignKey(
        "jejak.Bus",
        on_delete=models.PROTECT,
    )
