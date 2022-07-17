from datetime import date
from typing import TYPE_CHECKING, List, Optional

import strawberry
import strawberry.django
from asgiref.sync import sync_to_async
from django.db.models import Q
from strawberry import auto

from generic.schema.scalars import GeoPoint
from operation import models
from operation.enums import VehicleStatus
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
        ).distinct()

    @strawberry.field
    @sync_to_async
    def vehicle_status_in_service_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.IN_SERVICE,
        ).count()

    @strawberry.field
    @sync_to_async
    def vehicle_status_not_spotted_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.NOT_SPOTTED,
        ).count()

    @strawberry.field
    @sync_to_async
    def vehicle_status_decommissioned_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.DECOMMISSIONED,
        ).count()

    @strawberry.field
    @sync_to_async
    def vehicle_status_testing_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.TESTING,
        ).count()

    @strawberry.field
    @sync_to_async
    def vehicle_status_unknown_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.UNKNOWN,
        ).count()

    @strawberry.field
    @sync_to_async
    def vehicle_total_count(self) -> int:
        return models.Vehicle.objects.filter(vehicle_type_id=self.id).count()


@strawberry.django.type(models.Vehicle)
class Vehicle:
    id: auto
    identification_no: str
    vehicle_type: "VehicleType"
    status: strawberry.auto
    line: "Line"
    notes: str
    in_service_since: date

    if TYPE_CHECKING:
        from spotting.schema.scalars import Event

    @strawberry.field
    def last_spottings(
        self, count: int = 1
    ) -> List[strawberry.LazyType["Event", "spotting.schema.scalars"]]:  # noqa
        return spotting_models.Event.objects.filter(vehicle_id=self.id,).order_by(
            "-spotting_date"
        )[:count]

    @strawberry.field
    @sync_to_async
    def spottingCount(
        self, after: Optional[date] = None, before: Optional[date] = None
    ) -> int:
        filter = Q(vehicle_id=self.id)

        if after is not None:
            filter &= Q(spotting_date__gte=after)

        if before is not None:
            filter &= Q(spotting_date__lte=before)

        return spotting_models.Event.objects.filter(filter).count()
