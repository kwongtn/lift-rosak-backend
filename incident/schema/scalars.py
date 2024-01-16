from datetime import date, datetime
from typing import List, Optional

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from strawberry.types import Info

from common.schema.scalars import MediaScalar
from incident import models
from operation.schema.scalars import Line, Station, Vehicle


@strawberry.type
class IncidentAbstractScalar:
    id: strawberry.ID
    date: date
    severity: strawberry.auto
    order: strawberry.auto
    # location
    title: str
    brief: Optional[str]
    is_last: bool


@strawberry_django.type(models.VehicleIncident)
class VehicleIncident(IncidentAbstractScalar):
    vehicle: Vehicle
    # medias: List["Media"]


@strawberry_django.type(models.StationIncident)
class StationIncident(IncidentAbstractScalar):
    station: Station
    # medias: List["Media"]


@strawberry.type
class CalendarIncidentGroupByDateSeverityScalar:
    severity: str
    date: date
    count: int
    is_long_term: Optional[bool]


@strawberry_django.type(models.CalendarIncidentCategory)
class CalendarIncidentCategoryScalar:
    name: str


@strawberry_django.type(models.CalendarIncident)
class CalendarIncidentScalar:
    id: strawberry.auto
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
    chronologies: List["CalendarIncidentChronologyScalar"]

    @strawberry_django.field
    async def medias(self, info: Info) -> List["MediaScalar"]:
        return await info.context.loaders["incident"][
            "medias_from_calendar_incident_loader"
        ].load(self.id)

    @strawberry.field
    @sync_to_async
    def has_details(self) -> bool:
        return self.details not in [None, ""]

    @strawberry.field
    @sync_to_async
    def last_updated(self) -> datetime:
        db_obj = models.CalendarIncident.objects.get(id=self.id)
        return max(
            db_obj.modified,
            db_obj.chronologies.order_by("-modified")[0].modified
            if db_obj.chronologies.count() > 0
            else datetime.min,
        )


@strawberry_django.type(models.CalendarIncidentChronology)
class CalendarIncidentChronologyScalar:
    id: strawberry.auto
    order: int
    calendar_incident: "CalendarIncidentScalar"
    indicator: str
    datetime: datetime
    content: str
    source_url: Optional[str]
