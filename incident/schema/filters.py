from datetime import date, timedelta
from typing import Any, Optional

import strawberry
import strawberry_django
from django.contrib.gis.db.models import Q
from django.utils import timezone
from graphql import GraphQLError
from strawberry.types import Info
from strawberry_django.filters import process_filters

from incident import models
from operation.schema.filters import LineFilter, StationFilter, VehicleFilter


class IncidentAbstractFilter:
    id: strawberry.auto
    date: Optional[date]
    severity: strawberry.auto
    is_last: Optional[bool]


@strawberry_django.filter(models.VehicleIncident)
class VehicleIncidentFilter(IncidentAbstractFilter):
    vehicle: Optional["VehicleFilter"]


@strawberry_django.filter(models.StationIncident)
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


MAX_UPCOMING_DAYS = 60


def _tagged_with(field: str, value: Any, info: Info) -> Q:
    """Incidents with at least one `field` row matching the nested filter.

    A `pk IN (subquery)` rather than a join on the M2M: a join repeats an incident once
    per matching row, so two matching lines would return it twice."""
    queryset, q = process_filters(
        value, models.CalendarIncident.objects.all(), info, f"{field}__"
    )
    return Q(pk__in=queryset.filter(q).values("pk"))


@strawberry_django.filter(models.CalendarIncident)
class CalendarIncidentFilter:
    id: Optional[strawberry.ID]
    severity: Optional[str]

    @strawberry_django.filter_field
    def ongoing(self, value: bool, prefix) -> Q:
        """Incidents with no end date yet — independent of any `date` window, so a
        client can always fetch "what's currently broken" without knowing/guessing which
        date range it started in (see docs/components/incident.md's read-only status-page
        feature opportunity)."""
        return Q(end_datetime__isnull=True) if value else Q(end_datetime__isnull=False)

    @strawberry_django.filter_field
    def active_now(self, value: bool, prefix) -> Q:
        """Incidents in effect this instant: started, and not yet ended (or open-ended).
        `False` is the exact complement (not started yet, or already ended)."""
        now = timezone.now()
        if value:
            return Q(start_datetime__lte=now) & (
                Q(end_datetime__isnull=True) | Q(end_datetime__gte=now)
            )
        return Q(start_datetime__gt=now) | Q(end_datetime__lt=now)

    @strawberry_django.filter_field
    def upcoming_within_days(self, value: int, prefix) -> Q:
        """Incidents that have not started yet but start within `value` days: now <
        start <= now + value. Scheduled works with a known end time never match
        `ongoing`, so this is how a client asks for "planned works this week"."""
        if not 1 <= value <= MAX_UPCOMING_DAYS:
            raise GraphQLError(
                f"upcomingWithinDays must be between 1 and {MAX_UPCOMING_DAYS}"
            )
        now = timezone.now()
        return Q(
            start_datetime__gt=now, start_datetime__lte=now + timedelta(days=value)
        )

    @strawberry_django.filter_field
    def lines(self, info: Info, value: LineFilter, prefix) -> Q:
        return _tagged_with("lines", value, info)

    @strawberry_django.filter_field
    def stations(self, info: Info, value: StationFilter, prefix) -> Q:
        return _tagged_with("stations", value, info)

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

            root_q &= Q(start_datetime__date__lte=end) & (
                Q(end_datetime__date__gte=start) | Q(end_datetime__isnull=True)
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
