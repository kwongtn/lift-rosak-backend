from datetime import date, timedelta
from typing import TYPE_CHECKING, Annotated, List, Optional

from django.db.models import Count
from strawberry.types import Info
from strawberry_django_plus import gql

from common import models
from common.schema.types import UserSpottingTrend
from generic.schema.enums import DateGroupings
from spotting import models as spotting_models


@gql.django.type(models.Media)
class Media:
    id: str
    uploader: "UserScalar"


@gql.django.type(models.User)
class UserScalar:
    if TYPE_CHECKING:
        from spotting.schema.scalars import EventScalar

    firebase_id: str

    @gql.django.field
    async def spottings(
        self, info: Info, count: int = 1
    ) -> List[Annotated["EventScalar", gql.lazy("spotting.schema.scalars")]]:
        return await info.context.loaders["common"]["spottings_from_user_loader"].load(
            self.id
        )

    @gql.django.field
    async def spottings_count(self, info: Info) -> int:
        return spotting_models.Event.objects.filter(reporter_id=self.id).acount()

    @gql.django.field
    async def spotting_trends(
        self,
        info: Info,
        start: Optional[date] = gql.UNSET,
        end: Optional[date] = gql.UNSET,
        group: Optional[DateGroupings] = gql.UNSET,
    ) -> List[UserSpottingTrend]:
        if start is gql.UNSET:
            start = date.today() - timedelta(days=30)
        if end is gql.UNSET:
            end = date.today()

        group_strs = ["spotting_date"]
        if group == DateGroupings.YEAR:
            group_strs = ["spotting_date__year"]
        elif group == DateGroupings.MONTH:
            group_strs = ["spotting_date__year", "spotting_date__month"]
        elif group == DateGroupings.DAY:
            group_strs = [
                "spotting_date__year",
                "spotting_date__month",
                "spotting_date__day",
            ]

        return [
            UserSpottingTrend(
                spotting_date=value.get("spotting_date", None),
                count=value["count"],
                # Year
                year=value["spotting_date"].year
                if value.get("spotting_date", None) is not None
                else value.get("spotting_date__year", None),
                # Month
                month=value["spotting_date"].month
                if value.get("spotting_date", None) is not None
                else value.get("spotting_date__month", None),
                # Day
                day=value["spotting_date"].day
                if value.get("spotting_date", None) is not None
                else value.get("spotting_date__day", None),
            )
            async for value in spotting_models.Event.objects.filter(
                reporter_id=self.id,
                spotting_date__lte=end,
                spotting_date__gte=start,
            )
            .values(*group_strs)
            .annotate(count=Count("id"))
            .values(*group_strs, "count")
            .order_by(*[f"-{group_str}" for group_str in group_strs])
        ]


@gql.type
class GenericMutationReturn:
    ok: bool
