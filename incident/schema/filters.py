from datetime import date, timedelta

import strawberry
import strawberry_django
from django.db.models import Q

from incident import models


class IncidentAbstractFilter:
    id: strawberry.ID
    date: date
    severity: strawberry.auto
    is_last: bool

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_date(self, queryset):
        return queryset.filter(date=self.date)

    def filter_severity(self, queryset):
        return queryset.filter(severity=self.severity)

    def filter_is_last(self, queryset):
        return queryset.filter(is_last=self.is_last)


@strawberry_django.filters.filter(models.VehicleIncident)
class VehicleIncidentFilter(IncidentAbstractFilter):
    vehicle_id: strawberry.ID

    def filter_vehicle_id(self, queryset):
        return queryset.filter(vehicle_id=self.vehicle_id)


@strawberry_django.filters.filter(models.StationIncident)
class StationIncidentFilter(IncidentAbstractFilter):
    station_id: strawberry.ID

    def filter_station_id(self, queryset):
        return queryset.filter(station_id=self.station_id)


@strawberry_django.filters.filter(models.CalendarIncident)
class CalendarIncidentFilter:
    id: strawberry.ID
    severity: str
    date: date

    start_date: date
    end_date: date

    def filter_date(self, queryset):
        return queryset.filter(
            Q(start_datetime__date__lte=self.date)
            & Q(Q(end_datetime__date__gte=self.date) | Q(end_datetime__isnull=True))
        )

    def filter_start_date(self, queryset):
        assert self.start_date != strawberry.UNSET and self.end_date != strawberry.UNSET
        assert abs(self.end_date - self.start_date) <= timedelta(days=60)

        return queryset.filter(
            Q(
                Q(start_datetime__date__lte=self.end_date)
                & Q(start_datetime__date__gte=self.start_date)
            )
            & Q(
                Q(end_datetime__isnull=True)
                | Q(
                    Q(end_datetime__date__gte=self.start_date)
                    & Q(end_datetime__date__lte=self.end_date)
                )
            )
        )

    def filter_end_date(self, queryset):
        assert self.start_date != strawberry.UNSET and self.end_date != strawberry.UNSET
        assert abs(self.end_date - self.start_date) <= timedelta(days=60)

        return queryset
