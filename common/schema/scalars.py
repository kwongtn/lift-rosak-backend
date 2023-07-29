from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

import pendulum
import strawberry
import strawberry_django
from django.db.models import Count, F, Min
from strawberry.types import Info

from common import models
from common import models as common_models
from common.schema.orderings import MediaOrder
from common.schema.types import (
    FavouriteVehicleData,
    UserSpottingTrend,
    WithMostEntriesData,
)
from common.utils import (
    get_date_key,
    get_default_start_time,
    get_group_strs,
    get_result_comparison_tuple,
)
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

    @strawberry_django.field
    def width(self) -> int:
        return self.file.width

    @strawberry_django.field
    def height(self) -> int:
        return self.file.height


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

    @strawberry_django.field
    def width(self) -> int:
        return self.file.width

    @strawberry_django.field
    def height(self) -> int:
        return self.file.height


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
    ) -> List[UserSpottingTrend]:
        if start is strawberry.UNSET:
            start = get_default_start_time(type=date_group)

        if end is strawberry.UNSET:
            end = date.today()

        (group_strs, range_type) = get_group_strs(
            grouping=date_group, prefix="spotting_date__"
        )

        if type_group:
            group_strs.append("type")

        filter_params = {
            "reporter_id": self.id,
            "spotting_date__lte": end,
            "spotting_date__gte": start,
        }

        if free_range:
            filter_params.pop("spotting_date__lte", None)
            filter_params.pop("spotting_date__gte", None)

        qs = spotting_models.Event.objects.filter(**filter_params)

        results = list(
            qs.values(*group_strs)
            .annotate(count=Count("id"))
            .values(*group_strs, "count")
            .order_by(*[f"-{group_str}" for group_str in group_strs])
        )

        period = pendulum.period(
            qs.aggregate(min=Min("spotting_date"))["min"] if free_range else start,
            date.today() if free_range else end,
        )
        range = period.range(range_type)

        spotting_date__year = results[0].get("spotting_date__year", None)
        spotting_date__month = results[0].get("spotting_date__month", None)
        spotting_date__day = results[0].get("spotting_date__day", None)

        if not type_group:
            result_dates = get_result_comparison_tuple(
                results=results,
                prefix="spotting_date__",
            )

            for elem in range:
                year_val = elem.year if spotting_date__year is not None else None
                month_val = elem.month if spotting_date__month is not None else None
                day_val = elem.day if spotting_date__day is not None else None

                if (year_val, month_val, day_val) not in result_dates:
                    results.append(
                        {
                            "spotting_date__year": year_val,
                            "spotting_date__month": month_val,
                            "spotting_date__day": day_val,
                            "count": 0,
                        }
                    )

        else:
            result_types = get_result_comparison_tuple(
                results=results,
                additional_params=["type"],
                prefix="spotting_date__",
            )
            event_types = [event_type.value for event_type in SpottingEventType]

            for elem in range:
                year_val = elem.year if spotting_date__year is not None else None
                month_val = elem.month if spotting_date__month is not None else None
                day_val = elem.day if spotting_date__day is not None else None

                for event_type in event_types:
                    if (year_val, month_val, day_val, event_type) not in result_types:
                        results.append(
                            {
                                "spotting_date__year": year_val,
                                "spotting_date__month": month_val,
                                "spotting_date__day": day_val,
                                "type": event_type,
                                "count": 0,
                            }
                        )

        for result in results:
            result["date_key"] = get_date_key(
                year=result["spotting_date__year"],
                month=result.get("spotting_date__month", None),
                day=result.get("spotting_date__day", None),
            )

        results = sorted(results, key=lambda d: f'{d["date_key"]}')

        return [
            UserSpottingTrend(
                date_key=value["date_key"],
                count=value["count"],
                event_type=value.get("type", None),
                year=value.get("spotting_date__year", None),
                month=value.get("spotting_date__month", None),
                day=value.get("spotting_date__day", None),
            )
            for value in results
        ]


@strawberry.type
class GenericMutationReturn:
    ok: bool
