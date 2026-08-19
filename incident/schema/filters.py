from datetime import date, timedelta
from typing import Optional

import strawberry
import strawberry_django
from django.contrib.gis.db.models import Q
from graphql import GraphQLError

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


@strawberry.input
class DateRangeInput:
    start: strawberry.Maybe[date] = None
    end: strawberry.Maybe[date] = None


@strawberry.input
class IntExactInput:
    exact: strawberry.Maybe[int] = None


@strawberry.input
class CalendarIncidentDateFilter:
    range: strawberry.Maybe[DateRangeInput] = None
    exact: strawberry.Maybe[date] = None
    month: strawberry.Maybe[IntExactInput] = None
    year: strawberry.Maybe[IntExactInput] = None


@strawberry_django.filters.filter(models.CalendarIncident)
class CalendarIncidentFilter:
    id: Optional[strawberry.ID]
    severity: Optional[str]

    @strawberry_django.filter_field
    def date(self, value: CalendarIncidentDateFilter, prefix) -> Q:
        root_q = Q()

        if value.range is not None:
            range_val = value.range.value
            if range_val.start is None or range_val.end is None:
                raise GraphQLError("date range requires both start and end")
            start = range_val.start.value
            end = range_val.end.value
            if abs(end - start) > timedelta(days=60):
                raise GraphQLError("date range cannot exceed 60 days")

            if start == end:
                root_q &= Q(start_datetime__date__lte=end) & Q(
                    Q(end_datetime__date__gte=start) | Q(end_datetime__isnull=True)
                )
            else:
                root_q &= Q(
                    Q(start_datetime__date__lte=end)
                    & Q(start_datetime__date__gte=start)
                ) & Q(
                    Q(end_datetime__isnull=True)
                    | Q(
                        Q(end_datetime__date__gte=start)
                        & Q(end_datetime__date__lte=end)
                    )
                )

        if value.exact is not None:
            exact = value.exact.value
            root_q &= Q(start_datetime__date__lte=exact) & Q(
                Q(end_datetime__isnull=True) | Q(end_datetime__date__gte=exact)
            )

        if value.month is not None:
            month_val = value.month.value
            if month_val.exact is not None:
                month_exact = month_val.exact.value
                root_q &= Q(start_datetime__month__lte=month_exact + 1) & Q(
                    Q(end_datetime__isnull=True)
                    | Q(end_datetime__month__gte=month_exact + 1)
                )

        if value.year is not None:
            year_val = value.year.value
            if year_val.exact is not None:
                year_exact = year_val.exact.value
                root_q &= Q(start_datetime__year__lte=year_exact) & Q(
                    Q(end_datetime__isnull=True) | Q(end_datetime__year__gte=year_exact)
                )

        return root_q
