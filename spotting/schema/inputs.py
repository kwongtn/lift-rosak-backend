from datetime import date
from typing import List, Optional

import strawberry
import strawberry_django

from generic.schema.inputs import WebLocationInput
from spotting import models


@strawberry_django.partial(models.Event)
class EventInput:
    spotting_date: date
    vehicle: strawberry.ID
    notes: Optional[str] = strawberry.UNSET
    run_number: Optional[str] = strawberry.UNSET
    status: strawberry.auto
    type: strawberry.auto
    wheel_status: Optional[str] = strawberry.UNSET
    origin_station: Optional[strawberry.ID] = strawberry.UNSET
    destination_station: Optional[strawberry.ID] = strawberry.UNSET
    location: Optional["WebLocationInput"] = strawberry.UNSET
    is_anonymous: Optional[bool] = strawberry.UNSET


@strawberry.input
class MarkEventAsReadInput:
    event_ids: List[strawberry.ID]


@strawberry.input
class DeleteEventInput:
    id: strawberry.ID
