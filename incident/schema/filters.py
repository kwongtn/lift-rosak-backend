from datetime import date, timedelta
from typing import Optional

import strawberry
import strawberry_django
from django.contrib.gis.db.models import Q
from strawberry_django import DateFilterLookup

from incident import models
from operation.schema.filters import StationFilter, VehicleFilter


class IncidentAbstractFilter:
    id: strawberry.auto
    date: Optional[date]
    severity: strawberry.auto
    is_last: Optional[bool]


@strawberry_django.filters.filter(models.VehicleIncident)
class VehicleIncidentFilter(IncidentAbstractFilter):
    vehicle: Optional["VehicleFilter"]


@strawberry_django.filters.filter(models.StationIncident)
class StationIncidentFilter(IncidentAbstractFilter):
    station: Optional["StationFilter"]


@strawberry_django.filters.filter(models.CalendarIncident)
class CalendarIncidentFilter:
    id: Optional[strawberry.ID]
    severity: Optional[str]

    @strawberry_django.filter_field
    def date(self, value: DateFilterLookup["date"], prefix) -> Q:
        assert value.start != strawberry.UNSET and value.end != strawberry.UNSET
        assert abs(value.end - value.start) <= timedelta(days=60)

        if value.start == value.end:
            return Q(start_datetime__date__lte=value.end) & Q(
                Q(end_datetime__date__gte=value.start) | Q(end_datetime__isnull=True)
            )
        else:
            return Q(
                Q(start_datetime__date__lte=value.end)
                & Q(start_datetime__date__gte=value.start)
            ) & Q(
                Q(end_datetime__isnull=True)
                | Q(
                    Q(end_datetime__date__gte=value.start)
                    & Q(end_datetime__date__lte=value.end)
                )
            )
