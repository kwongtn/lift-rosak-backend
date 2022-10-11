from datetime import date
from typing import List, Optional

from strawberry_django_plus import gql

from generic.schema.scalars import GeoPoint
from spotting import models


@gql.django.partial(models.Event)
class EventInput:
    spotting_date: date
    vehicle: gql.ID
    notes: Optional[str]
    status: gql.auto
    type: gql.auto
    origin_station: Optional[gql.ID]
    destination_station: Optional[gql.ID]
    location: Optional["GeoPoint"]
    is_anonymous: Optional[bool]


@gql.input
class MarkEventAsReadInput:
    event_ids: List[gql.ID]
