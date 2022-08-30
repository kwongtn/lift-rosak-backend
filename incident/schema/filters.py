from datetime import date

from strawberry_django_plus import gql

from incident import models


class IncidentAbstractFilter:
    id: gql.ID
    date: date
    severity: gql.auto

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_date(self, queryset):
        return queryset.filter(date=self.date)

    def filter_severity(self, queryset):
        return queryset.filter(severity=self.severity)


@gql.django.filters.filter(models.VehicleIncident)
class VehicleIncidentFilter(IncidentAbstractFilter):
    vehicle_id = gql.ID

    def filter_vehicle_id(self, queryset):
        return queryset.filter(vehicle_id=self.vehicle_id)


@gql.django.filters.filter(models.StationIncident)
class StationIncidentFilter(IncidentAbstractFilter):
    station_id = gql.ID

    def filter_station_id(self, queryset):
        return queryset.filter(station_id=self.station_id)
