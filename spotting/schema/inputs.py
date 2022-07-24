from datetime import date
from typing import Optional

from strawberry_django_plus import gql

from generic.schema.scalars import GeoPoint
from spotting import models


@gql.django.partial(models.Event)
class EventInput:
    spotting_date: date
    auth_key: str
    vehicle: gql.ID
    notes: Optional[str]
    status: gql.auto
    type: gql.auto
    origin_station: Optional[gql.ID]
    destination_station: Optional[gql.ID]
    location: Optional["GeoPoint"]
