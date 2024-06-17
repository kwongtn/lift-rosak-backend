from typing import Optional

import strawberry
import strawberry_django
from django.contrib.gis.db.models import Q
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from strawberry_django import FilterLookup

from operation import models


@strawberry_django.filters.filter(models.Vehicle)
class VehicleFilter:
    id: strawberry.auto
    status: strawberry.auto


@strawberry_django.filters.filter(models.Line)
class LineFilter:
    id: strawberry.auto
    code: Optional[str]
    display_name: Optional[FilterLookup[str]]
    display_color: Optional[FilterLookup[str]]


@strawberry_django.filters.filter(models.VehicleType)
class VehicleTypeFilter:
    @strawberry_django.filter_field
    def line_id(self, value: strawberry.ID, prefix) -> Q:
        return Q(vehicles__vehicle_lines__id=value)


@strawberry_django.filters.filter(models.Asset)
class AssetFilter:
    id: strawberry.auto
    asset_type: strawberry.auto
    officialid: Optional[FilterLookup[str]]

    station: Optional["StationFilter"]


@strawberry_django.filters.filter(models.Station)
class StationFilter:
    id: strawberry.auto
    display_name: Optional[FilterLookup[str]]

    line: Optional["LineFilter"]
    station_line: Optional["StationLineFilter"]

    @strawberry_django.filter_field
    def location(self, value: strawberry.scalars.JSON, prefix) -> Q:
        return Q(
            location__distance_lt=(
                Point(
                    value.get("x"),
                    value.get("y"),
                    value.get("z"),
                ),
                Distance(km=value.get("radius")),
            )
        )


@strawberry_django.filters.filter(models.StationLine)
class StationLineFilter:
    id: strawberry.auto
    display_name: Optional[FilterLookup[str]]
    internal_representation: Optional[FilterLookup[str]]

    station: Optional["StationFilter"]
    line: Optional["LineFilter"]
