from datetime import date
from typing import List

import strawberry
import strawberry_django
from strawberry.types.maybe import Maybe

from generic.schema.inputs import WebLocationInput
from spotting import models


@strawberry_django.partial(models.Event)
class EventInput:
    spotting_date: date
    vehicle: strawberry.ID
    notes: Maybe[str | None] = strawberry.UNSET
    run_number: Maybe[str | None] = strawberry.UNSET
    status: strawberry.auto
    type: strawberry.auto
    wheel_status: Maybe[str | None] = strawberry.UNSET
    origin_station: Maybe[strawberry.ID | None] = strawberry.UNSET
    destination_station: Maybe[strawberry.ID | None] = strawberry.UNSET
    location: Maybe[WebLocationInput | None] = strawberry.UNSET
    is_anonymous: Maybe[bool | None] = strawberry.UNSET


@strawberry.input
class MarkEventAsReadInput:
    event_ids: List[strawberry.ID]


@strawberry.input
class DeleteEventInput:
    id: strawberry.ID
