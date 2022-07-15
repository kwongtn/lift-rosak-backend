from datetime import date

import strawberry
import strawberry_django

from generic.schema.scalars import GeoPoint
from spotting import models


@strawberry_django.input(models.Event, partial=True)
class EventInput:
    spotting_date: date
    reporter: strawberry.ID
    vehicle: strawberry.ID
    notes: str
    status: strawberry.auto
    type: strawberry.auto
    origin_station: strawberry.ID
    destination_station: strawberry.ID
    location: "GeoPoint"
