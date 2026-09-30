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
from incident.enums import PassengerStatus
from incident.schema.keyset import decode_keyset_cursor, encode_keyset_cursor

# Module-level (not a re-export via ``incident.services``) on purpose: importing
# the one predicate every thread field needs must not drag the whole service
# package — and its own imports — into a scalar's import graph.
from incident.services.social_link_visibility import is_publicly_visible
from operation.schema.scalars import Line, PassengerStatusCount, Station, Vehicle


@strawberry.type
class VoteBreakdown:
    upvotes: int
    downvotes: int


@strawberry.type
class LineStatusHourBucket:
    hour_start: datetime
    hour_end: datetime
    count: int
    dominant_status: Optional[PassengerStatus]
    status_counts: List[PassengerStatusCount]


@strawberry_django.type(models.LineStatusReport)
class LineStatusReportScalar:
    id: strawberry.auto
    status: strawberry.auto
    delay_minutes: Optional[int]
    notes: str
    created: datetime
    user: UserScalar
    stations: List[Station]


@strawberry.type
class LineStatusReportEdge:
    node: LineStatusReportScalar
    cursor: str


@strawberry.type
class LineStatusReportPageInfo:
    has_next_page: bool
    end_cursor: Optional[str]


@strawberry.type
class LineStatusReportConnection:
    edges: List[LineStatusReportEdge]
    page_info: LineStatusReportPageInfo


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
    normalized_url: Optional[str]
    title: str
    description: str
    status: strawberry.auto
    created: datetime
    # "When did this happen" — the instant the card renders and every feed /
    # queue ordering is built on. Distinct from ``created`` above ("when did
    # someone report this?"), which stays the moderation provenance column and
    # is deliberately NOT what the UI shows. NOT NULL on the model (a nullable
    # column would sort NULLs last on a DESC keyset scan instead of first), so
    # this is a plain non-optional ``datetime`` — no null branch to forget.
    # Naive local wall time: ``USE_TZ = False``, so Strawberry serialises it with
    # no offset. Never make_aware/astimezone it.
    occurred_at: datetime
    completed: bool
    completed_at: Optional[datetime]
    # True for rows written by the official-post ingestion (polling or webhook);
    # False for every hand-submitted link, including legacy rows predating
    # ingestion. Exposed so the console/feed can badge a capture as official
    # rather than inferring it from a status.
    is_automated: bool

    # --- Thread grouping (see ``SocialMediaLink.thread``) ----------------------
    # ``thread_id`` is a plain model attribute (the FK's attname), so this is a
    # free field read — no query, no loader. Null exactly when this link IS a
    # thread root, which is also what makes it the client-side "render me as a
    # root with N links" signal.
    thread_id: Optional[strawberry.ID]

    @strawberry_django.field
    async def is_thread_root(self) -> bool:
        # Derived from the already-loaded ``thread_id`` attribute: a query here
        # would buy nothing (``thread is None`` IS the definition) and would turn
        # a 20-row feed into 20 extra round trips. Null ``thread_id`` covers
        # BOTH the root of a real thread and an ordinary unthreaded link — the
        # degenerate one-member thread — which is why this is true for a plain
        # link too.
        return self.thread_id is None

    @strawberry_django.field
    async def thread_size(self, info: Info) -> int:
        """How many links this thread has, counting the root as 1.

        This is the number the "N links" badge shows, so it counts only
        publicly-visible members: a hidden or unapproved-automated member is
        attached to the thread but not openable by a visitor, and counting it
        would advertise a link that 404s into moderation.

        A **member** also reports ``1``, and must: the loader is keyed by this
        row's own id, and nothing carries ``thread_id == member.id`` (a member
        points at the root, never the reverse), so a member's member-list is
        empty by the same model invariant that makes depth 1. So ``1`` means
        "no publicly-visible members hang off me", which is the true answer for
        a member *and* for an ordinary unthreaded link — the two are
        indistinguishable from this field. Do not read it as the group's size
        for any row that is not a root.

        That is the same trap as ``isThreadRoot`` (``thread_id is None`` is
        true for a plain link too), so a client must gate on
        ``threadSize > 1`` / ``threadLinks.length > 0`` and not on
        ``isThreadRoot``. ``1`` is the "not a group" sentinel for both.

        Derived from the SAME loader call as ``threadLinks`` (which caches per
        request) rather than from a separate count query. Both fields therefore
        read one filtered list, so the badge and the expanded thread are
        structurally incapable of disagreeing.
        """
        members = await info.context.loaders["incident"]["thread_members"].load(self.id)
        return 1 + sum(1 for member in members if is_publicly_visible(member))

    @strawberry_django.field
    async def thread_links(self, info: Info) -> List["SocialMediaLinkScalar"]:
        """The thread's members, oldest first — for the expanded thread list.

        Members only, never the root itself (the caller already renders it), and
        empty for an unthreaded link. Depth is exactly 1 by model invariant
        (``thread`` always points at a root), so there is no recursion here and
        no further hop to guard against a cycle.

        Also empty for a **member**: the loader is keyed by this row's id, and
        by the same invariant no row points at a member, so asking a member for
        its thread yields nothing — even though the member visibly belongs to one
        (``threadId`` names it, ``threadSize`` says 1). Query the ROOT for the
        member list; this is why a client must not reconstruct a thread from an
        arbitrary row it happens to be holding. ``[]`` therefore means "nothing
        hangs off me", not "I am in no thread" — see ``threadSize``.

        Visibility-filtered with the shared predicate: returning a hidden member
        would leak its URL/title through a nested field, which is exactly the
        moderation decision the feed-level ``.exclude()`` exists to honour. The
        filter is applied on EVERY surface, ``mine`` included — only the
        queryset-level gates in ``get_public_social_media_links`` are exempt
        there. See ``services/social_link_visibility.is_publicly_visible`` for
        why the two deliberately differ.
        """
        members = await info.context.loaders["incident"]["thread_members"].load(self.id)
        return [member for member in members if is_publicly_visible(member)]

    @strawberry_django.field
    async def vote_score(self, info: Info) -> int:
        ct_id = await _content_type_id(models.SocialMediaLink)
        return await info.context.loaders["incident"]["vote_scores"].load(
            (ct_id, self.id)
        )

    @strawberry_django.field
    async def vote_breakdown(self, info: Info) -> VoteBreakdown:
        ct_id = await _content_type_id(models.SocialMediaLink)
        raw = await info.context.loaders["incident"]["vote_breakdown"].load(
            (ct_id, self.id)
        )
        return VoteBreakdown(upvotes=raw["upvotes"], downvotes=raw["downvotes"])

    @strawberry_django.field
    async def user_vote(self, info: Info) -> int:
        user = info.context.user
        if not user:
            return 0
        ct_id = await _content_type_id(models.SocialMediaLink)
        return await info.context.loaders["incident"]["user_vote_value"].load(
            (user.id, ct_id, self.id)
        )

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
class FeedLinkPayload:
    ok: bool
    link: SocialMediaLinkScalar
    is_duplicate: bool
    duplicate_of_id: Optional[int]
    user_vote: int


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
    total_count: int


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
        """Per-incident submitted links, newest first (``occurred_at DESC, id DESC``).

        "Newest" is the EVENT instant, not the submission time: an incident whose
        newest report describes last Tuesday sorts that link first. Same ordering,
        keyset-cursor format and connection shape as the root
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
        content_type = await sync_to_async(ContentType.objects.get_for_model)(
            models.CalendarIncident
        )
        # Cursor-independent count: the whole incident feed, not just this page.
        total_count = await models.SocialMediaLink.objects.filter(
            content_type=content_type, object_id=self.id
        ).acount()

        if after is None:
            rows = await info.context.loaders["incident"]["incident_links"].load(
                (self.id, first)
            )
        else:
            # The cursor carries ``(occurred_at, id)``, matching the ordering
            # above — a cursor built on ``created`` would skip or duplicate rows
            # whenever the two columns disagree, which is the whole point of
            # having a separate event time.
            cursor_occurred_at, cursor_id = decode_keyset_cursor(after)
            rows = [
                link
                async for link in models.SocialMediaLink.objects.filter(
                    content_type=content_type, object_id=self.id
                )
                .order_by("-occurred_at", "-id")
                .filter(
                    Q(occurred_at__lt=cursor_occurred_at)
                    | Q(occurred_at=cursor_occurred_at, id__lt=cursor_id)
                )[: first + 1]
            ]

        has_next_page = len(rows) > first
        rows = rows[:first]
        edges = [
            SocialMediaLinkEdge(
                node=link, cursor=encode_keyset_cursor(link.occurred_at, link.id)
            )
            for link in rows
        ]

        return SocialMediaLinkConnection(
            edges=edges,
            page_info=SocialMediaLinkPageInfo(
                has_next_page=has_next_page,
                end_cursor=edges[-1].cursor if edges else None,
            ),
            total_count=total_count,
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
