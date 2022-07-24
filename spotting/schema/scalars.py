from datetime import date

from strawberry_django_plus import gql

from common.schema.scalars import User
from generic.schema.scalars import GeoPoint
from operation.schema.scalars import Station, Vehicle
from spotting import models


@gql.django.type(models.Event)
class Event:
    id: gql.auto
    spotting_date: date
    reporter: "User"
    vehicle: "Vehicle"
    notes: str
    status: gql.auto
    type: gql.auto
    origin_station: "Station"
    destination_station: "Station"
    location: "GeoPoint"
