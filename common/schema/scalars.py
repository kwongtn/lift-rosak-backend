from datetime import date, timedelta
from typing import TYPE_CHECKING, Annotated, List, Optional

import pendulum
from django.db.models import Count
from strawberry.types import Info
from strawberry_django_plus import gql

from common import models
from common.schema.types import UserSpottingTrend
from common.utils import date_splitter
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
    def spotting_trends(
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
        range_type = "days"
        if group == DateGroupings.YEAR:
            group_strs = ["spotting_date__year"]
            range_type = "years"
        elif group == DateGroupings.MONTH:
            group_strs = ["spotting_date__year", "spotting_date__month"]
            range_type = "months"
        elif group == DateGroupings.DAY:
            group_strs = [
                "spotting_date__year",
                "spotting_date__month",
                "spotting_date__day",
            ]

        results = list(
            spotting_models.Event.objects.filter(
                reporter_id=self.id,
                spotting_date__lte=end,
                spotting_date__gte=start,
            )
            .values(*group_strs)
            .annotate(count=Count("id"))
            .values(*group_strs, "count")
            .order_by(*[f"-{group_str}" for group_str in group_strs])
        )

        period = pendulum.period(start, end)
        range = period.range(range_type)

        if group in [DateGroupings.DAY, gql.UNSET]:
            result_days = [
                date_splitter(result["spotting_date"], range_type) for result in results
            ]
            for elem in range:
                if date_splitter(elem, range_type) not in result_days:
                    results.append(
                        {
                            "spotting_date": date(elem.year, elem.month, elem.day),
                            "count": 0,
                        }
                    )
            results = sorted(results, key=lambda d: d["spotting_date"])

        elif group == DateGroupings.MONTH:
            result_months = [
                [result["spotting_date__year"], result["spotting_date__month"]]
                for result in results
            ]
            for elem in range:
                if [elem.year, elem.month] not in result_months:
                    results.append(
                        {
                            "spotting_date__year": elem.year,
                            "spotting_date__month": elem.month,
                            "count": 0,
                        }
                    )

            results = sorted(
                results,
                key=lambda d: f'{d["spotting_date__year"]}{d["spotting_date__month"]:02}',
            )

        elif group == DateGroupings.YEAR:
            result_years = [result["spotting_date__year"] for result in results]
            for elem in range:
                if elem.year not in result_years:
                    results.append({"spotting_date__year": elem.year, "count": 0})

            results = sorted(results, key=lambda d: d["spotting_date__year"])

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
            for value in results
        ]


@gql.type
class GenericMutationReturn:
    ok: bool
