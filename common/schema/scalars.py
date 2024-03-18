from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

import strawberry
import strawberry_django
from django.db.models import Count, F, Q
from strawberry.types import Info

from common import models
from common import models as common_models
from common.schema.orderings import MediaOrder
from common.schema.types import (
    FavouriteVehicleData,
    UserSpottingTrend,
    WithMostEntriesData,
)
from common.utils import get_date_key, get_default_start_time, get_trends
from generic.schema.enums import DateGroupings
from operation import models as operation_models
from rosak.permissions import IsAdmin
from spotting import models as spotting_models
from spotting.enums import SpottingEventType


@strawberry_django.type(models.Media, pagination=True)
class MediaScalar:
    id: strawberry.ID
    uploader: "UserScalar"
    file: strawberry_django.DjangoImageType
    width: int
    height: int
    url: Optional[str]
    discord_suffix: str


@strawberry.type
class MediasGroupByPeriodScalar:
    type: DateGroupings
    date_key: str
    year: int
    month: Optional[int]
    day: Optional[int]
    count: int
    medias: List["MediaScalar"]


@strawberry_django.type(models.Media, order=MediaOrder)
class MediaType(strawberry.relay.Node):
    id: strawberry.relay.NodeID[str]
    created: datetime
    uploader: "UserScalar"
    file: strawberry_django.DjangoFileType
    width: int
    height: int
    url: Optional[str]
    discord_suffix: str


@strawberry_django.type(models.User)
class UserScalar:
    if TYPE_CHECKING:
        from spotting.schema.scalars import EventScalar

    firebase_id: str = strawberry_django.field(permission_classes=[IsAdmin])
    nickname: str

    @strawberry_django.field
    def short_id(self) -> str:
        return self.firebase_id[:8]

    @strawberry_django.field
    def favourite_vehicles(
        self, count: Optional[int] = 1
    ) -> List[FavouriteVehicleData]:
        vehicle_count_dict = list(
            spotting_models.Event.objects.filter(reporter_id=self.id)
            .values("vehicle")
            .annotate(Count("vehicle"))
            .order_by("-vehicle__count")[0:count]
        )

        vehicles = operation_models.Vehicle.objects.filter(
            id__in=[elem["vehicle"] for elem in vehicle_count_dict]
        ).in_bulk()

        return [
            FavouriteVehicleData(
                vehicle=vehicles[elem["vehicle"]],
                count=elem["vehicle__count"],
            )
            for elem in vehicle_count_dict
        ]

    @strawberry_django.field
    def with_most_entries(self, type: DateGroupings) -> WithMostEntriesData:
        groupings = {"year": F("created__year")}

        if type in [DateGroupings.MONTH, DateGroupings.DAY]:
            groupings["month"] = F("created__month")

            if type == DateGroupings.DAY:
                groupings["day"] = F("created__day")

        max = (
            spotting_models.Event.objects.filter(reporter_id=self.id)
            .annotate(**groupings)
            .values(*groupings.keys())
            .annotate(count=Count("id"))
            .order_by("-count")[0]
        )

        return WithMostEntriesData(
            type=type,
            date_key=get_date_key(
                year=max["year"],
                month=max.get("month", None),
                day=max.get("day", None),
            ),
            year=max["year"],
            month=max.get("month", None),
            day=max.get("day", None),
            count=max["count"],
        )

    @strawberry_django.field
    async def spottings(
        self, info: Info
    ) -> List[Annotated["EventScalar", strawberry.lazy("spotting.schema.scalars")]]:
        return await info.context.loaders["common"]["spottings_from_user_loader"].load(
            self.id
        )

    @strawberry_django.field
    async def spottings_count(self, info: Info) -> int:
        return await spotting_models.Event.objects.filter(reporter_id=self.id).acount()

    @strawberry_django.field
    async def media_count(self) -> int:
        return await common_models.Media.objects.filter(uploader_id=self.id).acount()

    @strawberry_django.field
    def spotting_trends(
        self,
        start: Optional[date] = strawberry.UNSET,
        end: Optional[date] = strawberry.UNSET,
        date_group: Optional[DateGroupings] = DateGroupings.DAY,
        type_group: Optional[bool] = False,
        free_range: Optional[bool] = False,
    ) -> List["UserSpottingTrend"]:
        if start is strawberry.UNSET:
            start = get_default_start_time(type=date_group)

        if end is strawberry.UNSET:
            end = date.today()

        results = get_trends(
            groupby_field="spotting_date",
            count_model=spotting_models.Event,
            filters=Q(reporter_id=self.id),
            add_zero=True,
            additional_groupby={
                "type": [event_type.value for event_type in SpottingEventType],
            }
            if type_group
            else {},
            free_range=free_range,
        )

        return [
            UserSpottingTrend(
                date_key=value["date_key"],
                count=value["count"],
                event_type=value.get("type", None),
                year=value.get("spotting_date__year", None),
                month=value.get("spotting_date__month", None),
                day=value.get("spotting_date__day", None),
                day_of_week=value.get("day_of_week", None),
                week_of_month=value.get("week_of_month", None),
                week_of_year=value.get("week_of_year", None),
                is_last_day_of_month=value.get("is_last_day_of_month", None),
                is_last_week_of_month=value.get("is_last_week_of_month", None),
            )
            for value in results
        ]


@strawberry_django.type(models.UserVerificationCode)
class UserVerificationCodeScalar:
    user: "UserScalar"
    created: datetime
    code: int


@strawberry.type
class GenericMutationReturn:
    ok: bool
