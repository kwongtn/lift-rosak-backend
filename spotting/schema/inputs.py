from datetime import date

import strawberry_django

from generic.schema.scalars import GeoPoint
from operation.schema.enums import VehicleStatus
from spotting import models
from spotting.schema.enums import SpottingEventType


@strawberry_django.input(models.Event, partial=True)
class EventInput:
    spotting_date: date
    reporter: str
    vehicle: int
    notes: str
    status: "VehicleStatus"
    type: "SpottingEventType"
    origin_station: int
    destination_station: int
    location: "GeoPoint"
