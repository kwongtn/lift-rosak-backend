from datetime import date
from typing import List, Optional

from strawberry.types import Info
from strawberry_django_plus import gql
from strawberry_django_plus.gql import relay

from common.schema.scalars import MediaScalar, UserScalar
from generic.schema.scalars import WebLocationParent
from operation.schema.scalars import Station, Vehicle
from rosak.permissions import IsLoggedIn
from spotting import models


@gql.django.type(models.LocationEvent)
class LocationEvent(WebLocationParent):
    pass


@gql.django.type(models.Event, pagination=True)
class EventScalar:
    id: gql.auto
    created: date
    spotting_date: date
    vehicle: "Vehicle"
    notes: str
    status: gql.auto
    type: gql.auto
    run_number: Optional[str]
    origin_station: Optional["Station"]
    destination_station: Optional["Station"]

    @gql.field
    async def reporter(self, info: Info) -> Optional["UserScalar"]:
        return await info.context.loaders["spotting"][
            "reporter_from_event_loader"
        ].load(self.id)

    @gql.field(permission_classes=[IsLoggedIn])
    async def is_read(self, info: Info) -> bool:
        return await info.context.loaders["spotting"]["is_read_from_event_loader"].load(
            (self.id, info.context.user.id)
        )

    @gql.field
    async def location(self, info: Info) -> Optional["LocationEvent"]:
        return await info.context.loaders["spotting"][
            "location_event_from_event_loader"
        ].load(self.id)

    @gql.field
    async def media_count(self, info: Info) -> int:
        return await info.context.loaders["spotting"][
            "media_count_from_event_loader"
        ].load(self.id)

    @gql.field
    async def medias(self, info: Info) -> List["MediaScalar"]:
        return await info.context.loaders["spotting"]["media_from_event_loader"].load(
            self.id
        )


@gql.django.type(models.Event)
class EventRelay(relay.Node, EventScalar):
    pass
