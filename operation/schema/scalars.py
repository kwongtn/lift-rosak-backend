from datetime import date
from typing import TYPE_CHECKING, Annotated, List, Optional

from django.db.models import Q
from strawberry.types import Info
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
    internal_representation: Optional[str]
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
    # line_vehicles: List["Vehicle"]

    @gql.django.field
    async def vehicle_types(self, info: Info) -> List["VehicleType"]:
        return await info.context.loaders["operation"][
            "vehicle_type_from_line_loader"
        ].load(self.id)


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
    info: str

    @gql.django.field
    async def vehicles(self, info: Info) -> List["Vehicle"]:
        return await info.context.loaders["operation"][
            "vehicle_from_vehicle_type_loader"
        ].load(self.id)

    @gql.field
    async def vehicle_status_in_service_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.IN_SERVICE))

    @gql.field
    async def vehicle_status_not_spotted_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.NOT_SPOTTED))

    @gql.field
    async def vehicle_status_decommissioned_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.DECOMMISSIONED))

    @gql.field
    async def vehicle_status_married_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.MARRIED))

    @gql.field
    async def vehicle_status_testing_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.TESTING))

    @gql.field
    async def vehicle_status_unknown_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.UNKNOWN))

    @gql.field
    async def vehicle_total_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_count_from_vehicle_type_loader"
        ].load(self.id)

    @gql.field
    def info(self, info: Info):
        return str(info)


@gql.django.type(models.Vehicle)
class Vehicle:
    if TYPE_CHECKING:
        from incident.schema.scalars import VehicleIncident
        from spotting.schema.scalars import EventScalar

    id: gql.auto
    identification_no: str
    status: gql.auto
    lines: List["Line"]
    notes: str
    nickname: Optional[str]
    in_service_since: Optional[date]
    vehicle_type: "VehicleType" = gql.django.field(select_related=["vehicle_type"])

    @gql.django.field
    async def last_spotting_date(self, info: Info) -> Optional[date]:
        return await info.context.loaders["operation"][
            "last_spotting_date_from_vehicle_loader"
        ].load(self.id)

    @gql.django.field
    def last_spottings(
        self, count: int = 1
    ) -> List[Annotated["EventScalar", gql.lazy("spotting.schema.scalars")]]:
        return spotting_models.Event.objects.filter(vehicle_id=self.id,).order_by(
            "-spotting_date"
        )[:count]

    @gql.field
    async def spottingCount(
        self, info: Info, after: Optional[date] = None, before: Optional[date] = None
    ) -> int:

        filter = Q(vehicle_id=self.id)

        if after is not None:
            filter &= Q(spotting_date__gte=after)

        if before is not None:
            filter &= Q(spotting_date__lte=before)

        return await info.context.loaders["operation"][
            "spotting_count_from_vehicle_loader"
        ].load((self.id, filter))

    @gql.django.field
    async def incidents(
        self, info: Info
    ) -> List[Annotated["VehicleIncident", gql.lazy("incident.schema.scalars")]]:
        return await info.context.loaders["operation"][
            "incident_from_vehicle_loader"
        ].load(self.id)

    @gql.field
    async def incident_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "incident_count_from_vehicle_loader"
        ].load(self.id)
