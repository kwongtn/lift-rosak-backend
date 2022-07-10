from datetime import date

import strawberry
import strawberry.django
from strawberry import auto

from common.schema.scalars import User
from generic.schema.scalars import GeoPoint
from operation.schema.enums import VehicleStatus
from operation.schema.scalars import Station, Vehicle
from spotting import models
from spotting.schema.enums import SpottingEventType


@strawberry.django.type(models.Event)
class Event:
    id: auto
    spotting_date: date
    reporter: "User"
    vehicle: "Vehicle"
    notes: str
    status: "VehicleStatus"
    type: "SpottingEventType"
    origin_station: "Station"
    destination_station: "Station"
    location: "GeoPoint"
