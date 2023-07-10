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
    notes: Optional[str]
    run_number: Optional[str]
    status: strawberry.auto
    type: strawberry.auto
    origin_station: Optional[strawberry.ID]
    destination_station: Optional[strawberry.ID]
    location: Optional["WebLocationInput"]
    is_anonymous: Optional[bool]


@strawberry.input
class MarkEventAsReadInput:
    event_ids: List[strawberry.ID]


@strawberry.input
class DeleteEventInput:
    id: strawberry.ID
