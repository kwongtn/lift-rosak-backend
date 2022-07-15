from typing import List

import strawberry
import strawberry.django
from strawberry import auto

from generic.schema.scalars import GeoPoint
from operation import models
from operation.schema.enums import VehicleStatus


@strawberry.django.type(models.Station)
class Station:
    id: auto
    display_name: str
    location: "GeoPoint"
    lines: List["Line"]
    assets: List["Asset"]


@strawberry.django.type(models.StationLine)
class StationLine:
    id: auto
    display_name: str
    internal_representation: str
    stations: List["Station"]
    lines: List["Line"]


@strawberry.django.type(models.Line)
class Line:
    id: auto
    code: str
    display_name: str
    display_color: str
    stations: List["Station"]

    @strawberry.field
    def station_lines(self) -> List["StationLine"]:
        return models.StationLine.objects.filter(
            line_id=self.id,
        )

    @strawberry.field
    def vehicles(self) -> List["Vehicle"]:
        return models.Vehicle.objects.filter(
            line_id=self.id,
        )

    @strawberry.field
    def vehicle_types(self) -> List["VehicleType"]:
        return models.VehicleType.objects.filter(
            vehicle__line_id=self.id,
        )


@strawberry.django.type(models.Asset)
class Asset:
    id: auto
    asset_type: auto
    officialid: str
    short_description: str
    long_description: str
    stations: List["Station"]


@strawberry.django.type(models.VehicleType)
class VehicleType:
    id: auto
    internal_name: str
    display_name: str

    @strawberry.field
    def vehicles(self) -> List["Vehicle"]:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
        )


@strawberry.django.type(models.Vehicle)
class Vehicle:
    id: auto
    identification_no: str
    vehicle_type: "VehicleType"
    status: "VehicleStatus"
    line: "Line"
    notes: str
