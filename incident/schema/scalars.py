from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from strawberry.types import Info

from incident import models
from operation.schema.scalars import Line, Station, Vehicle


@strawberry.type
class VoteBreakdown:
    upvotes: int
    downvotes: int


async def _content_type_id(model) -> int:
    content_type = await sync_to_async(ContentType.objects.get_for_model)(model)
    return content_type.id


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


@strawberry.type
class ExtractedIncidentDataScalar:
    request_id: str
    data: strawberry.scalars.JSON


@strawberry_django.type(models.CalendarIncidentCategory)
class CalendarIncidentCategoryScalar:
    name: str


@strawberry_django.type(models.CalendarIncident)
class CalendarIncidentScalar:
    if TYPE_CHECKING:
        from common.schema.scalars import MediaScalar

    id: strawberry.auto
    start_datetime: datetime
    end_datetime: Optional[datetime]

    severity: strawberry.auto
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
    async def medias(
        self, info: Info
    ) -> List[Annotated["MediaScalar", strawberry.lazy("common.schema.scalars")]]:
        return await info.context.loaders["incident"][
            "medias_from_calendar_incident_loader"
        ].load(self.id)

    @strawberry_django.field
    async def vote_score(self, info: Info) -> int:
        ct_id = await _content_type_id(models.CalendarIncident)
        return await info.context.loaders["incident"]["vote_scores"].load(
            (ct_id, self.id)
        )

    @strawberry_django.field
    async def vote_breakdown(self, info: Info) -> VoteBreakdown:
        ct_id = await _content_type_id(models.CalendarIncident)
        raw = await info.context.loaders["incident"]["vote_breakdown"].load(
            (ct_id, self.id)
        )
        return VoteBreakdown(upvotes=raw["upvotes"], downvotes=raw["downvotes"])

    @strawberry_django.field
    async def user_vote(self, info: Info) -> int:
        user = info.context.user
        if not user:
            return 0
        ct_id = await _content_type_id(models.CalendarIncident)
        return await info.context.loaders["incident"]["user_vote_value"].load(
            (user.id, ct_id, self.id)
        )

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

    @strawberry_django.field
    async def vote_score(self, info: Info) -> int:
        ct_id = await _content_type_id(models.CalendarIncidentChronology)
        return await info.context.loaders["incident"]["vote_scores"].load(
            (ct_id, self.id)
        )

    @strawberry_django.field
    async def vote_breakdown(self, info: Info) -> VoteBreakdown:
        ct_id = await _content_type_id(models.CalendarIncidentChronology)
        raw = await info.context.loaders["incident"]["vote_breakdown"].load(
            (ct_id, self.id)
        )
        return VoteBreakdown(upvotes=raw["upvotes"], downvotes=raw["downvotes"])

    @strawberry_django.field
    async def user_vote(self, info: Info) -> int:
        user = info.context.user
        if not user:
            return 0
        ct_id = await _content_type_id(models.CalendarIncidentChronology)
        return await info.context.loaders["incident"]["user_vote_value"].load(
            (user.id, ct_id, self.id)
        )
