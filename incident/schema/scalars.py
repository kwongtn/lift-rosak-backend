from datetime import date, datetime
from typing import List, Optional

from strawberry_django_plus import gql

from incident import models
from operation.schema.scalars import Line, Station, Vehicle


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


@gql.type
class CalendarIncidentGroupByDateSeverityScalar:
    severity: str
    date: date
    count: int


@gql.django.type(models.CalendarIncidentCategory)
class CalendarIncidentCategoryScalar:
    name: str


@gql.django.type(models.CalendarIncident)
class CalendarIncidentScalar(IncidentAbstractScalar):
    id: gql.auto
    start_datetime: datetime
    end_datetime: Optional[datetime]

    severity: str
    title: str
    brief: str
    details: str

    impact_factor: float

    lines: List[Line]
    vehicles: List[Vehicle]
    stations: List[Station]
    categories: List[CalendarIncidentCategoryScalar]

    # medias: List["Media"]
    # TODO: Dataloaders
