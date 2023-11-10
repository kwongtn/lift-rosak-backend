from datetime import date
from typing import List, Optional

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from strawberry.types import Info

from common.schema.scalars import MediaScalar, UserScalar
from operation.schema.scalars import Station, Vehicle
from rosak.permissions import IsLoggedIn
from spotting import models


@strawberry_django.type(models.LocationEvent)
class LocationEvent:
    id: strawberry.auto
    accuracy: Optional[float]
    altitude_accuracy: Optional[float]
    heading: Optional[float]
    speed: Optional[float]
    # latitude: Optional[float]
    # longitude: Optional[float]
    location: strawberry.auto
    altitude: Optional[float]


@strawberry_django.type(models.Event, pagination=True)
class EventScalar:
    id: strawberry.auto
    created: date
    spotting_date: date
    vehicle: "Vehicle"
    notes: str
    status: strawberry.auto
    type: strawberry.auto
    wheel_status: strawberry.auto
    run_number: Optional[str]
    origin_station: Optional["Station"]
    destination_station: Optional["Station"]

    @strawberry.field
    async def reporter(self, info: Info) -> Optional["UserScalar"]:
        return await info.context.loaders["spotting"][
            "reporter_from_event_loader"
        ].load(self.id)

    @strawberry.field(permission_classes=[IsLoggedIn])
    async def is_read(self, info: Info) -> bool:
        return await info.context.loaders["spotting"]["is_read_from_event_loader"].load(
            (self.id, info.context.user.id)
        )

    @strawberry.field
    async def location(self, info: Info) -> Optional["LocationEvent"]:
        return await info.context.loaders["spotting"][
            "location_event_from_event_loader"
        ].load(self.id)

    @strawberry.field
    async def media_count(self, info: Info) -> int:
        return await info.context.loaders["spotting"][
            "media_count_from_event_loader"
        ].load(self.id)

    @strawberry.field
    async def medias(self, info: Info) -> List["MediaScalar"]:
        return await info.context.loaders["spotting"]["media_from_event_loader"].load(
            self.id
        )

    @strawberry.field
    @sync_to_async
    def is_mine(self, info: Info) -> bool:
        user = info.context.user
        if user is None:
            return False
        else:
            return self.reporter.id == user.id


# @strawberry_django.type(models.Event)
# class EventRelay(relay.Node, EventScalar):
#     pass
