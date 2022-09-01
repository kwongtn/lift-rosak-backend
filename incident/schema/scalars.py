from datetime import date
from typing import Optional

from strawberry_django_plus import gql

from incident import models
from operation.schema.scalars import Station, Vehicle


class IncidentAbstractScalar:
    id: gql.ID
    date: date
    severity: gql.auto
    order: gql.auto
    # location
    title: str
    brief: Optional[str]
    is_last: bool


@gql.django.type(models.VehicleIncident)
class VehicleIncident(IncidentAbstractScalar):
    vehicle: Vehicle
    # medias: List["Media"]


@gql.django.type(models.StationIncident)
class StationIncident(IncidentAbstractScalar):
    station: Station
    # medias: List["Media"]
