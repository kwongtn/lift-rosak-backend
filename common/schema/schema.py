from typing import List

import strawberry
import strawberry_django
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Count, F
from strawberry.types import Info
from strawberry_django.relay import ListConnectionWithTotalCount

from common.models import Media, User, UserVerificationCode
from common.schema.inputs import UserInput
from common.schema.scalars import MediasGroupByPeriodScalar, MediaType, UserScalar
from common.utils import get_date_key
from generic.schema.enums import DateGroupings
from rosak.permissions import IsLoggedIn


@strawberry.type
class CommonScalars:
    medias: ListConnectionWithTotalCount[MediaType] = strawberry_django.connection()

    @strawberry.field(permission_classes=[IsLoggedIn])
    async def user(self, info: Info) -> UserScalar:
        if not info.context.user:
            return None

        from common.models import User

        return await User.objects.aget(id=info.context.user.id)

    @strawberry.field
    async def medias_group_by_period(
        self, info: Info, type: DateGroupings
    ) -> List[MediasGroupByPeriodScalar]:
        groupings = {"year": F("created__year")}

        if type in [DateGroupings.MONTH, DateGroupings.DAY]:
            groupings["month"] = F("created__month")

            if type == DateGroupings.DAY:
                groupings["day"] = F("created__day")

        annotations = (
            Media.objects.annotate(**groupings)
            .values(*groupings.keys())
            .annotate(
                count=Count("id"), medias=ArrayAgg(F("id"), distinct=True, default=[])
            )
        )

        return [
            MediasGroupByPeriodScalar(
                type=type,
                date_key=get_date_key(
                    year=elem["year"],
                    month=elem.get("month", None),
                    day=elem.get("day", None),
                ),
                year=elem["year"],
                month=elem.get("month", None),
                day=elem.get("day", None),
                count=elem["count"],
                medias=[
                    await info.context.loaders["common"]["media_from_id_loader"].load(
                        key
                    )
                    for key in elem["medias"]
                ],
            )
            async for elem in annotations
        ]


@strawberry.type
class CommonMutations:
    #     create_medias: List[Media] = strawberry_django.mutations.create(MediaInput)
    #     delete_medias: List[Media] = strawberry_django.mutations.delete()

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def update_user(self, input: UserInput, info: Info) -> UserScalar:
        user: User = info.context.user
        user.nickname = input.nickname
        await user.asave()

        return user

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def request_verification_code(self, info: Info) -> int:
        user: User = info.context.user

        code_obj: UserVerificationCode = await UserVerificationCode.objects.acreate(
            user_id=user.id
        )
        return code_obj.code
