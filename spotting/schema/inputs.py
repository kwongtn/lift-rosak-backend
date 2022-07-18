from datetime import date
from typing import Optional

import strawberry
import strawberry_django

from generic.schema.scalars import GeoPoint
from spotting import models


@strawberry_django.input(models.Event, partial=True)
class EventInput:
    spotting_date: date
    reporter: strawberry.ID
    vehicle: strawberry.ID
    notes: Optional[str]
    status: strawberry.auto
    type: strawberry.auto
    origin_station: Optional[strawberry.ID]
    destination_station: Optional[strawberry.ID]
    location: Optional["GeoPoint"]
