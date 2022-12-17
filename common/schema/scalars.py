from datetime import date, timedelta
from typing import TYPE_CHECKING, Annotated, List, Optional

import pendulum
from django.db.models import Count
from strawberry.types import Info
from strawberry_django_plus import gql

from common import models
from common.schema.types import UserSpottingTrend
from common.utils import get_date_key
from generic.schema.enums import DateGroupings
from spotting import models as spotting_models
from spotting.enums import SpottingEventType


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
        date_group: Optional[DateGroupings] = gql.UNSET,
        type_group: Optional[bool] = False,
    ) -> List[UserSpottingTrend]:
        if start is gql.UNSET:
            start = date.today() - timedelta(days=30)
        if end is gql.UNSET:
            end = date.today()

        if date_group == DateGroupings.YEAR:
            group_strs = ["spotting_date__year"]
            range_type = "years"
        elif date_group == DateGroupings.MONTH:
            group_strs = ["spotting_date__year", "spotting_date__month"]
            range_type = "months"
        else:
            group_strs = [
                "spotting_date__year",
                "spotting_date__month",
                "spotting_date__day",
            ]
            range_type = "days"

        if type_group:
            group_strs.append("type")

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

        spotting_date__year = results[0].get("spotting_date__year", None)
        spotting_date__month = results[0].get("spotting_date__month", None)
        spotting_date__day = results[0].get("spotting_date__day", None)

        if not type_group:
            result_dates = [
                (
                    result.get("spotting_date__year", None),
                    result.get("spotting_date__month", None),
                    result.get("spotting_date__day", None),
                )
                for result in results
            ]

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
            result_types = [
                (
                    result.get("spotting_date__year", None),
                    result.get("spotting_date__month", None),
                    result.get("spotting_date__day", None),
                    result["type"],
                )
                for result in results
            ]
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


@gql.type
class GenericMutationReturn:
    ok: bool
