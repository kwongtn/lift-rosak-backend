from typing import TYPE_CHECKING, Annotated, List

from strawberry.types import Info
from strawberry_django_plus import gql

from common import models


@gql.django.type(models.Media)
class Media:
    id: str
    uploader: "UserScalar"


@gql.django.type(models.User)
class UserScalar:
    if TYPE_CHECKING:
        from spotting.schema.scalars import EventScalar

    id: gql.auto
    firebase_id: str

    @gql.django.field
    async def spottings(
        self, info: Info, count: int = 1
    ) -> List[Annotated["EventScalar", gql.lazy("spotting.schema.scalars")]]:
        return await info.context.loaders["common"]["spottings_from_user_loader"].load(
            self.id
        )


@gql.type
class GenericMutationReturn:
    ok: bool
