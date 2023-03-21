import strawberry
from django.contrib.gis.db.models import Subquery
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from strawberry_django_plus import gql

from operation import models


@gql.django.filters.filter(models.Vehicle)
class VehicleFilter:
    id: gql.ID
    status: gql.auto

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_status(self, queryset):
        return queryset.filter(status=self.status)


@gql.django.filters.filter(models.Line)
class LineFilter:
    id: gql.ID
    code: str
    display_name: str
    display_color: str

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_code(self, queryset):
        return queryset.filter(code__icontains=self.code)

    def filter_display_name(self, queryset):
        return queryset.filter(display_name__icontains=self.display_name)

    def filter_display_color(self, queryset):
        return queryset.filter(display_color__icontains=self.display_color)


@gql.django.filters.filter(models.VehicleType)
class VehicleTypeFilter:
    line_id: gql.ID

    def filter_line_id(self, queryset):
        return queryset.filter(vehicles__vehicle_lines__id=self.line_id).distinct("id")


@gql.django.filters.filter(models.Asset)
class AssetFilter:
    id: gql.ID
    officialid: str
    asset_type: gql.auto
    station_id: gql.ID

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_officialid(self, queryset):
        return queryset.filter(officialid=self.officialid)

    def filter_asset_type(self, queryset):
        return queryset.filter(asset_type=self.asset_type)

    def filter_station_id(self, queryset):
        return queryset.filter(station_id=self.station_id)


@gql.django.filters.filter(models.Station)
class StationFilter:
    id: gql.ID
    display_name: str
    internal_representation: str
    location: strawberry.scalars.JSON
    line_id: gql.ID

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_display_name(self, queryset):
        return queryset.filter(display_name__icontains=self.display_name)

    def filter_internal_representation(self, queryset):
        stationIds = models.StationLine.objects.filter(
            internal_representation__icontains=self.internal_representation
        ).values_list("station_id", flat=True)

        return queryset.filter(id__in=Subquery(stationIds))

    def filter_location(self, queryset):
        return queryset.filter(
            location__distance_lt=(
                Point(
                    self.location.get("x"),
                    self.location.get("y"),
                    self.location.get("z"),
                ),
                Distance(km=self.location.get("radius")),
            )
        )

    def filter_line_id(self, queryset):
        return queryset.filter(lines=self.line_id)


@gql.django.filters.filter(models.StationLine)
class StationLineFilter:
    id: gql.ID
    display_name: str
    station_id: gql.ID
    line_id: gql.ID
    internal_representation: str

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_display_name(self, queryset):
        return queryset.filter(display_name__icontains=self.display_name)

    def filter_station_id(self, queryset):
        return queryset.filter(station_id=self.station_id)

    def filter_line_id(self, queryset):
        return queryset.filter(line_id=self.line_id)

    def filter_internal_representation(self, queryset):
        return queryset.filter(
            internal_representation__icontains=self.internal_representation
        )
