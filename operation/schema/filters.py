import strawberry
import strawberry_django
from django.contrib.gis.db.models import Subquery
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance

from operation import models


@strawberry_django.filters.filter(models.Vehicle)
class VehicleFilter:
    id: strawberry.ID
    status: strawberry.auto

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_status(self, queryset):
        return queryset.filter(status=self.status)


@strawberry_django.filters.filter(models.Line)
class LineFilter:
    id: strawberry.ID
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


@strawberry_django.filters.filter(models.VehicleType)
class VehicleTypeFilter:
    line_id: strawberry.ID

    def filter_line_id(self, queryset):
        return queryset.filter(vehicles__vehicle_lines__id=self.line_id).distinct("id")


@strawberry_django.filters.filter(models.Asset)
class AssetFilter:
    id: strawberry.ID
    officialid: str
    asset_type: strawberry.auto
    station_id: strawberry.ID

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_officialid(self, queryset):
        return queryset.filter(officialid=self.officialid)

    def filter_asset_type(self, queryset):
        return queryset.filter(asset_type=self.asset_type)

    def filter_station_id(self, queryset):
        return queryset.filter(station_id=self.station_id)


@strawberry_django.filters.filter(models.Station)
class StationFilter:
    id: strawberry.ID
    display_name: str
    internal_representation: str
    location: strawberry.scalars.JSON
    line_id: strawberry.ID

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


@strawberry_django.filters.filter(models.StationLine)
class StationLineFilter:
    id: strawberry.ID
    display_name: str
    station_id: strawberry.ID
    line_id: strawberry.ID
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
