from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from strawberry.types import Info

from common.schema.scalars import UserScalar
from incident import models
from incident.schema.keyset import decode_keyset_cursor, encode_keyset_cursor
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
    id: strawberry.auto
    name: str


@strawberry_django.type(models.SocialMediaLink)
class SocialMediaLinkScalar:
    id: strawberry.auto
    url: str
    title: str
    description: str
    status: strawberry.auto
    created: datetime
    completed: bool
    completed_at: Optional[datetime]

    @strawberry.field
    @sync_to_async
    def completed_by(self) -> Optional[str]:
        if self.completed_by is None:
            return None
        return self.completed_by.display_name

    user: UserScalar
    categories: List[CalendarIncidentCategoryScalar]
    lines: List[Line]
    vehicles: List[Vehicle]
    stations: List[Station]


@strawberry.type
class SocialMediaLinkEdge:
    node: SocialMediaLinkScalar
    cursor: str


@strawberry.type
class SocialMediaLinkPageInfo:
    has_next_page: bool
    end_cursor: Optional[str]


@strawberry.type
class SocialMediaLinkConnection:
    edges: List[SocialMediaLinkEdge]
    page_info: SocialMediaLinkPageInfo


@strawberry_django.type(models.CalendarIncident)
class CalendarIncidentScalar:
    if TYPE_CHECKING:
        from common.schema.scalars import MediaScalar

    id: strawberry.auto
    created: datetime
    start_datetime: datetime
    end_datetime: Optional[datetime]

    severity: strawberry.auto
    status: strawberry.auto
    title: str
    brief: str
    details: str

    impact_factor: float
    version: strawberry.auto

    long_term: bool
    inaccurate: bool

    lines: List[Line]
    vehicles: List[Vehicle]
    stations: List[Station]
    categories: List[CalendarIncidentCategoryScalar]
    chronologies: List["CalendarIncidentChronologyScalar"]
    user: Optional[UserScalar] = strawberry_django.field(field_name="created_by")

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

    @strawberry_django.field
    async def links(
        self, info: Info, first: int = 10, after: Optional[str] = None
    ) -> SocialMediaLinkConnection:
        """Per-incident submitted links, newest first (``created DESC, id DESC``).

        Same ordering, keyset-cursor format and connection shape as the root
        ``publicSocialMediaLinks(incidentId, first, after)`` resolver (see
        incident.schema.keyset), so a cursor from this nested field can be handed
        to the root query for continuation pages.

        Page one (``after`` is None) is served by the ``incident_links``
        DataLoader: a feed of N cards batches every first page into one row
        query instead of N+1 (repo rule: resolvers that fan out to related rows
        must use a loader). Continuation pages query directly — each parent
        carries its own per-parent keyset cursor, so per-parent windows cannot
        be batched into one shared loader query.
        """
        if after is None:
            rows = await info.context.loaders["incident"]["incident_links"].load(
                (self.id, first)
            )
        else:
            content_type = await sync_to_async(ContentType.objects.get_for_model)(
                models.CalendarIncident
            )
            cursor_created, cursor_id = decode_keyset_cursor(after)
            rows = [
                link
                async for link in models.SocialMediaLink.objects.filter(
                    content_type=content_type, object_id=self.id
                )
                .order_by("-created", "-id")
                .filter(
                    Q(created__lt=cursor_created)
                    | Q(created=cursor_created, id__lt=cursor_id)
                )[: first + 1]
            ]

        has_next_page = len(rows) > first
        rows = rows[:first]
        edges = [
            SocialMediaLinkEdge(
                node=link, cursor=encode_keyset_cursor(link.created, link.id)
            )
            for link in rows
        ]

        return SocialMediaLinkConnection(
            edges=edges,
            page_info=SocialMediaLinkPageInfo(
                has_next_page=has_next_page,
                end_cursor=edges[-1].cursor if edges else None,
            ),
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


@strawberry.type
class CalendarIncidentHistoryEntryScalar:
    """One diffed history entry for a CalendarIncident (django-simple-history).

    ``timestamp`` is the history record's ``history_date`` (UTC).
    ``actor`` is the changing user's display identity — nickname, or the first 8
    chars of firebase_id when nickname is blank — and ``None`` when the change was
    made by the system or an anonymous actor (no ``history_user``).
    ``change_type`` maps simple-history ``history_type`` to a readable value:
    ``"created"`` (+), ``"updated"`` (~), ``"deleted"`` (-).
    ``changed_fields`` lists the model field names that differ from the
    immediately previous history record: ``["created"]`` for the oldest record,
    ``["deleted"]`` for a deletion, otherwise the field names reported by
    ``diff_against`` (e.g. ``["title"]``).
    """

    timestamp: datetime
    actor: Optional[str]
    change_type: str
    changed_fields: List[str]


@strawberry_django.type(models.CalendarIncidentChronology)
class CalendarIncidentChronologyScalar:
    id: strawberry.auto
    order: int
    status: strawberry.auto
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
