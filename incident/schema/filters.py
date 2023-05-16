from datetime import date, timedelta

from django.db.models import Q
from strawberry_django_plus import gql

from incident import models


class IncidentAbstractFilter:
    id: gql.ID
    date: date
    severity: gql.auto
    is_last: bool

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_date(self, queryset):
        return queryset.filter(date=self.date)

    def filter_severity(self, queryset):
        return queryset.filter(severity=self.severity)

    def filter_is_last(self, queryset):
        return queryset.filter(is_last=self.is_last)


@gql.django.filters.filter(models.VehicleIncident)
class VehicleIncidentFilter(IncidentAbstractFilter):
    vehicle_id: gql.ID

    def filter_vehicle_id(self, queryset):
        return queryset.filter(vehicle_id=self.vehicle_id)


@gql.django.filters.filter(models.StationIncident)
class StationIncidentFilter(IncidentAbstractFilter):
    station_id: gql.ID

    def filter_station_id(self, queryset):
        return queryset.filter(station_id=self.station_id)


@gql.django.filters.filter(models.CalendarIncident)
class CalendarIncidentFilter:
    id: gql.ID
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
        assert self.start_date != gql.UNSET and self.end_date != gql.UNSET
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
        assert self.start_date != gql.UNSET and self.end_date != gql.UNSET
        assert abs(self.end_date - self.start_date) <= timedelta(days=60)

        return queryset
