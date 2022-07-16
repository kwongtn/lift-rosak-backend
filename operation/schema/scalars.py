from typing import TYPE_CHECKING, List

import strawberry
import strawberry.django
from strawberry import auto

from generic.schema.scalars import GeoPoint
from operation import models
from operation.schema.enums import VehicleStatus
from spotting import models as spotting_models


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
        ).distinct()


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

    if TYPE_CHECKING:
        from spotting.schema.scalars import Event

    @strawberry.field
    def last_spottings(
        self, count: int = 1
    ) -> List[strawberry.LazyType["Event", "spotting.schema.scalars"]]:  # noqa
        return spotting_models.Event.objects.filter(vehicle_id=self.id,).order_by(
            "-spotting_date"
        )[:count]
