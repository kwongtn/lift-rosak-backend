from datetime import date
from typing import TYPE_CHECKING, Annotated, List, Optional

import strawberry
import strawberry_django
from django.db.models import Q
from strawberry.types import Info

from common.utils import get_default_start_time, get_trends
from generic.schema.enums import DateGroupings
from generic.schema.scalars import GeoPoint
from operation import models
from operation import models as operation_models
from operation.enums import VehicleStatus
from operation.schema.types import LineVehicleSpottingTrend, VehicleSpottingTrend
from spotting import models as spotting_models
from spotting.enums import SpottingEventType


@strawberry_django.type(models.Station)
class Station:
    id: strawberry.ID
    display_name: str
    location: Optional["GeoPoint"]
    lines: List["Line"]
    assets: List["Asset"]


@strawberry_django.type(models.StationLine)
class StationLine:
    id: strawberry.ID
    display_name: str
    internal_representation: Optional[str]
    stations: List["Station"]
    lines: List["Line"]


@strawberry_django.type(models.Line)
class Line:
    id: strawberry.ID
    code: str
    display_name: str
    display_color: str
    status: strawberry.auto
    stations: List["Station"]
    station_lines: List["StationLine"]
    # line_vehicles: List["Vehicle"]
    status: strawberry.auto

    @strawberry_django.field
    async def vehicle_types(self, info: Info) -> List["VehicleType"]:
        return await info.context.loaders["operation"][
            "vehicle_type_from_line_loader"
        ].load(self.id)

    @strawberry_django.field
    async def vehicles(self, info: Info) -> List["Vehicle"]:
        return await info.context.loaders["operation"]["vehicle_from_line_loader"].load(
            self.id
        )

    @strawberry_django.field
    def vehicle_spotting_trends(
        self,
        start: Optional[date] = strawberry.UNSET,
        end: Optional[date] = strawberry.UNSET,
        date_group: Optional[DateGroupings] = DateGroupings.DAY,
        type_group: Optional[bool] = False,
        free_range: Optional[bool] = False,
        add_zero: Optional[bool] = True,
    ) -> List["LineVehicleSpottingTrend"]:
        if start is strawberry.UNSET:
            start = get_default_start_time(type=date_group)

        if end is strawberry.UNSET:
            end = date.today()

        vehicles = operation_models.Vehicle.objects.filter(lines=self.id).in_bulk()

        results = get_trends(
            start=start,
            end=end,
            date_group=date_group,
            groupby_field="spotting_date",
            count_model=spotting_models.Event,
            filters=Q(vehicle__lines=self.id),
            add_zero=add_zero,
            additional_groupby={
                "type": [event_type.value for event_type in SpottingEventType],
                "vehicle_id": [k for k in vehicles.keys()],
            }
            if type_group
            else {
                "vehicle_id": [k for k in vehicles.keys()],
            },
            free_range=free_range,
        )

        return [
            LineVehicleSpottingTrend(
                date_key=value["date_key"],
                count=value["count"],
                vehicle=vehicles[value["vehicle_id"]],
                event_type=value.get("type", None),
                year=value.get("spotting_date__year", None),
                month=value.get("spotting_date__month", None),
                week=value.get("spotting_date__week", None),
                day=value.get("spotting_date__day", None),
            )
            for value in results
        ]


@strawberry_django.type(models.Asset)
class Asset:
    id: strawberry.auto
    asset_type: strawberry.auto
    officialid: str
    short_description: str
    long_description: str
    stations: List["Station"]


@strawberry_django.type(models.VehicleType)
class VehicleType:
    id: strawberry.auto
    internal_name: str
    display_name: str
    info: str

    @strawberry_django.field
    async def vehicles(self, info: Info) -> List["Vehicle"]:
        return await info.context.loaders["operation"][
            "vehicle_from_vehicle_type_loader"
        ].load(self.id)

    @strawberry.field
    async def vehicle_status_in_service_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.IN_SERVICE))

    @strawberry.field
    async def vehicle_status_not_spotted_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.NOT_SPOTTED))

    @strawberry.field
    async def vehicle_status_out_of_service_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.OUT_OF_SERVICE))

    @strawberry.field
    async def vehicle_status_decommissioned_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.DECOMMISSIONED))

    @strawberry.field
    async def vehicle_status_married_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.MARRIED))

    @strawberry.field
    async def vehicle_status_testing_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.TESTING))

    @strawberry.field
    async def vehicle_status_unknown_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_status_count_from_vehicle_type_loader"
        ].load((self.id, VehicleStatus.UNKNOWN))

    @strawberry.field
    async def vehicle_total_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "vehicle_count_from_vehicle_type_loader"
        ].load(self.id)


@strawberry_django.type(models.Vehicle)
class Vehicle:
    if TYPE_CHECKING:
        from incident.schema.scalars import VehicleIncident
        from spotting.schema.scalars import EventScalar

    id: strawberry.auto
    identification_no: str
    status: strawberry.auto
    lines: List["Line"]
    notes: str
    nickname: Optional[str]
    in_service_since: Optional[date]
    vehicle_type: "VehicleType" = strawberry_django.field(
        select_related=["vehicle_type"]
    )
    wheel_status: strawberry.auto

    @strawberry_django.field
    async def last_spotting_date(self, info: Info) -> Optional[date]:
        return await info.context.loaders["operation"][
            "last_spotting_date_from_vehicle_loader"
        ].load(self.id)

    @strawberry.field
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

    @strawberry_django.field
    async def incidents(
        self, info: Info
    ) -> List[Annotated["VehicleIncident", strawberry.lazy("incident.schema.scalars")]]:
        return await info.context.loaders["operation"][
            "incident_from_vehicle_loader"
        ].load(self.id)

    @strawberry_django.field
    async def spottings(
        self, info: Info
    ) -> List[Annotated["EventScalar", strawberry.lazy("spotting.schema.scalars")]]:
        return await info.context.loaders["operation"][
            "spottings_from_vehicle_loader"
        ].load(self.id)

    @strawberry.field
    async def incident_count(self, info: Info) -> int:
        return await info.context.loaders["operation"][
            "incident_count_from_vehicle_loader"
        ].load(self.id)

    @strawberry.field
    async def can_expand(self, info: Info) -> bool:
        return (
            await info.context.loaders["operation"][
                "incident_count_from_vehicle_loader"
            ].load(self.id)
        ) > 0 or (
            await info.context.loaders["operation"][
                "spotting_count_from_vehicle_loader"
            ].load((self.id, Q(vehicle_id=self.id)))
        ) > 0

    @strawberry_django.field
    def spotting_trends(
        self,
        start: Optional[date] = strawberry.UNSET,
        end: Optional[date] = strawberry.UNSET,
        date_group: Optional[DateGroupings] = DateGroupings.DAY,
        type_group: Optional[bool] = False,
        free_range: Optional[bool] = False,
        add_zero: Optional[bool] = True,
    ) -> List["VehicleSpottingTrend"]:
        if start is strawberry.UNSET:
            start = get_default_start_time(type=date_group)

        if end is strawberry.UNSET:
            end = date.today()
            end.isocalendar()

        results = get_trends(
            start=start,
            end=end,
            date_group=date_group,
            groupby_field="spotting_date",
            count_model=spotting_models.Event,
            filters=Q(vehicle_id=self.id),
            add_zero=add_zero,
            additional_groupby={
                "type": [event_type.value for event_type in SpottingEventType],
            }
            if type_group
            else {},
            free_range=free_range,
        )

        return [
            VehicleSpottingTrend(
                date_key=value["date_key"],
                count=value["count"],
                event_type=value.get("type", None),
                year=value.get("spotting_date__year", None),
                month=value.get("spotting_date__month", None),
                week=value.get("spotting_date__week", None),
                day=value.get("spotting_date__day", None),
            )
            for value in results
        ]
