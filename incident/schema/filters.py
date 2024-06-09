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
        root_q = Q()

        if value.range != strawberry.UNSET:
            assert (
                value.range.start != strawberry.UNSET
                and value.range.end != strawberry.UNSET
            )
            assert abs(value.range.end - value.range.start) <= timedelta(days=60)

            if value.range.start == value.range.end:
                root_q &= Q(start_datetime__date__lte=value.range.end) & Q(
                    Q(end_datetime__date__gte=value.range.start)
                    | Q(end_datetime__isnull=True)
                )
            else:
                root_q &= Q(
                    Q(start_datetime__date__lte=value.range.end)
                    & Q(start_datetime__date__gte=value.range.start)
                ) & Q(
                    Q(end_datetime__isnull=True)
                    | Q(
                        Q(end_datetime__date__gte=value.range.start)
                        & Q(end_datetime__date__lte=value.range.end)
                    )
                )

        if value.exact != strawberry.UNSET:
            root_q &= Q(start_datetime__date__lte=value.exact) & Q(
                Q(end_datetime__isnull=True) | Q(end_datetime__date__gte=value.exact)
            )

        # TODO: Optimize code to be more less repetitive
        if value.month != strawberry.UNSET:
            if value.month.exact != strawberry.UNSET:
                root_q &= Q(start_datetime__month__lte=value.month.exact + 1) & Q(
                    Q(end_datetime__isnull=True)
                    | Q(end_datetime__month__gte=value.month.exact + 1)
                )

        if value.year != strawberry.UNSET:
            if value.year.exact != strawberry.UNSET:
                root_q &= Q(start_datetime__year__lte=value.year.exact) & Q(
                    Q(end_datetime__isnull=True)
                    | Q(end_datetime__year__gte=value.year.exact)
                )

        return root_q
