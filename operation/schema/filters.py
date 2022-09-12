import strawberry
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
    first_only: bool

    def filter_first_only(self, queryset):
        if self.first_only:
            return queryset[:1]
        else:
            return queryset

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
        return queryset.filter(internal_representation=self.internal_representation)

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
