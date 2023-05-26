from datetime import date, datetime
from typing import List, Optional

from strawberry_django_plus import gql

from common.schema.scalars import Media
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
    is_long_term: Optional[bool]


@gql.django.type(models.CalendarIncidentCategory)
class CalendarIncidentCategoryScalar:
    name: str


@gql.django.type(models.CalendarIncident)
class CalendarIncidentScalar:
    id: gql.auto
    start_datetime: datetime
    end_datetime: Optional[datetime]

    severity: str
    title: str
    brief: str
    details: str

    impact_factor: float

    long_term: bool
    inaccurate: bool

    lines: List[Line]
    vehicles: List[Vehicle]
    stations: List[Station]
    categories: List[CalendarIncidentCategoryScalar]
    medias: List["Media"]
    chronologies: List["CalendarIncidentChronologyScalar"]

    # medias: List["Media"]
    # TODO: Dataloaders

    @gql.field
    def has_details(self) -> bool:
        return self.details not in [None, ""]

    @gql.field
    def last_updated(self) -> datetime:
        db_obj = models.CalendarIncident.objects.get(id=self.id)
        return max(
            db_obj.modified,
            db_obj.chronologies.order_by("-modified")[0].modified,
        )


@gql.django.type(models.CalendarIncidentChronology)
class CalendarIncidentChronologyScalar:
    id: gql.auto
    order: int
    calendar_incident: "CalendarIncidentScalar"
    indicator: str
    datetime: datetime
    content: str
    source_url: Optional[str]
