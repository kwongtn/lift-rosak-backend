from django.db import models

from .abstracts import RangeAbstractModel


class BusView(models.Model):
    bus = models.CharField(max_length=64)
    bus_id = models.BigIntegerField()

    class Meta:
        abstract = True


class ProviderView(models.Model):
    provider = models.CharField(max_length=64)
    provider_id = models.BigIntegerField()

    class Meta:
        abstract = True


class AccessibilityBusRangeView(RangeAbstractModel, BusView):
    accessibility_id = models.BigIntegerField()
    is_oku_friendly = models.BooleanField()

    class Meta:
        db_table = "view_accessibilitybusrange"
        managed = False


class EngineStatusBusRangeView(RangeAbstractModel, BusView):
    engine_status = models.CharField(max_length=64)
    engine_status_id = models.BigIntegerField()

    class Meta:
        db_table = "view_enginestatusbusrange"
        managed = False


class TripRevBusRangeView(RangeAbstractModel, BusView):
    trip_rev = models.CharField(max_length=64)
    trip_rev_id = models.BigIntegerField()

    class Meta:
        db_table = "view_triprevbusrange"
        managed = False


class BusRouteRangeView(RangeAbstractModel, BusView):
    route = models.CharField(max_length=64)
    route_id = models.BigIntegerField()

    class Meta:
        db_table = "view_busrouterange"
        managed = False


class BusStopBusRangeView(RangeAbstractModel, BusView):
    bus_stop = models.CharField(max_length=64)
    bus_stop_id = models.BigIntegerField()

    class Meta:
        db_table = "view_busstopbusrange"
        managed = False


class CaptainProviderRangeView(RangeAbstractModel, ProviderView):
    captain = models.CharField(max_length=64)
    captain_id = models.BigIntegerField()

    class Meta:
        db_table = "view_captainproviderrange"
        managed = False


class CaptainBusRangeView(RangeAbstractModel, BusView):
    captain = models.CharField(max_length=64)
    captain_id = models.BigIntegerField()

    class Meta:
        db_table = "view_captainbusrange"
        managed = False


class BusProviderRangeView(RangeAbstractModel, BusView, ProviderView):
    class Meta:
        db_table = "view_busproviderrange"
        managed = False
