from datetime import date
from typing import Optional

from strawberry.types import Info
from strawberry_django_plus import gql

from common.schema.scalars import User
from generic.schema.scalars import WebLocationParent
from operation.schema.scalars import Station, Vehicle
from spotting import models


@gql.django.type(models.LocationEvent)
class LocationEvent(WebLocationParent):
    pass


@gql.django.type(models.Event, pagination=True)
class Event:
    id: gql.auto
    created: date
    spotting_date: date
    reporter: "User"
    vehicle: "Vehicle"
    notes: str
    status: gql.auto
    type: gql.auto
    origin_station: Optional["Station"]
    destination_station: Optional["Station"]

    @gql.field
    async def is_read(self, info: Info) -> bool:
        return await info.context.loaders["spotting"]["is_read_from_event_loader"].load(
            (self.id, info.context.user.id)
        )

    @gql.field
    async def location(self, info: Info) -> Optional["LocationEvent"]:
        return await info.context.loaders["spotting"][
            "location_event_from_event_loader"
        ].load(self.id)
