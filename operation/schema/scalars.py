from datetime import date
from typing import TYPE_CHECKING, List, Optional

from django.db.models import Q
from strawberry_django_plus import gql

from generic.schema.scalars import GeoPoint
from operation import models
from operation.enums import VehicleStatus
from spotting import models as spotting_models


@gql.django.type(models.Station)
class Station:
    id: gql.ID
    display_name: str
    location: Optional["GeoPoint"]
    lines: List["Line"]
    assets: List["Asset"]


@gql.django.type(models.StationLine)
class StationLine:
    id: gql.ID
    display_name: str
    internal_representation: str
    stations: List["Station"]
    lines: List["Line"]


@gql.django.type(models.Line)
class Line:
    id: gql.ID
    code: str
    display_name: str
    display_color: str
    stations: List["Station"]
    station_lines: List["StationLine"]

    @gql.field
    def station_lines(self) -> List["StationLine"]:
        return models.StationLine.objects.filter(
            line_id=self.id,
        )

    @gql.field
    def vehicles(self) -> List["Vehicle"]:
        return models.Vehicle.objects.filter(
            line_id=self.id,
        )

    @gql.field
    def vehicle_types(self) -> List["VehicleType"]:
        return models.VehicleType.objects.filter(
            vehicle__line_id=self.id,
        ).distinct()


@gql.django.type(models.Asset)
class Asset:
    id: gql.auto
    asset_type: gql.auto
    officialid: str
    short_description: str
    long_description: str
    stations: List["Station"]


@gql.django.type(models.VehicleType)
class VehicleType:
    id: gql.auto
    internal_name: str
    display_name: str

    @gql.field
    def vehicles(self) -> List["Vehicle"]:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
        ).distinct()

    @gql.field
    def vehicle_status_in_service_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.IN_SERVICE,
        ).count()

    @gql.field
    def vehicle_status_not_spotted_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.NOT_SPOTTED,
        ).count()

    @gql.field
    def vehicle_status_decommissioned_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.DECOMMISSIONED,
        ).count()

    @gql.field
    def vehicle_status_testing_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.TESTING,
        ).count()

    @gql.field
    def vehicle_status_unknown_count(self) -> int:
        return models.Vehicle.objects.filter(
            vehicle_type_id=self.id,
            status=VehicleStatus.UNKNOWN,
        ).count()

    @gql.field
    def vehicle_total_count(self) -> int:
        return models.Vehicle.objects.filter(vehicle_type_id=self.id).count()


@gql.django.type(models.Vehicle)
class Vehicle:
    id: gql.auto
    identification_no: str
    vehicle_type: "VehicleType"
    status: gql.auto
    line: "Line"
    notes: str
    in_service_since: Optional[date]

    if TYPE_CHECKING:
        from spotting.schema.scalars import Event

    @gql.django.field
    def last_spottings(
        self, count: int = 1
    ) -> List[gql.LazyType["Event", "spotting.schema.scalars"]]:  # noqa
        return spotting_models.Event.objects.filter(vehicle_id=self.id,).order_by(
            "-spotting_date"
        )[:count]

    @gql.field
    def spottingCount(
        self, after: Optional[date] = None, before: Optional[date] = None
    ) -> int:
        filter = Q(vehicle_id=self.id)

        if after is not None:
            filter &= Q(spotting_date__gte=after)

        if before is not None:
            filter &= Q(spotting_date__lte=before)

        return spotting_models.Event.objects.filter(filter).count()
