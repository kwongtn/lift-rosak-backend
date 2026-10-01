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
# the one predicate every hierarchy field needs must not drag the whole service
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


def _publicly_visible_subtree(
    rows: List[models.SocialMediaLink],
) -> List[models.SocialMediaLink]:
    """Drop the non-public rows from a flat subtree, keeping the rest in order.

    Two rules, in this order, and the second is the one that is easy to miss:

    1. ``is_publicly_visible`` — the shared moderation predicate, imported by
       name at the top of this module. Not re-implemented here and not pushed
       into a queryset: two copies of a moderation rule is how a public feed
       leaks a hidden row's URL through a nested field.
    2. **A descendant of a row that rule removed is removed too.** A HIDDEN
       middle node stays in the tree, so its visible children are in
       ``rows`` — but no client can reach them through ``sublinks``, because the
       node they hang off is not in the list the client walks. Counting them
       (``sublinkCount``) while the nesting cannot show them is precisely the
       badge/list disagreement this design exists to make impossible, and it
       would appear the first time an admin hid a node with children. So the
       suppressed set accumulates: hidden rows AND rows orphaned by a hidden
       ancestor, in one pass.

    The pass works because the loader returns the subtree depth-first: a row's
    parent has already been judged by the time the row itself is reached, so
    ``suppressed`` is a complete answer for every row and no set of ancestors is
    needed. That is a real dependency on the loader's ordering, not a stylistic
    choice — it is why ``batch_load_sublink_subtrees`` sorts the way it does.
    """
    kept: List[models.SocialMediaLink] = []
    suppressed = set()
    for row in rows:
        if row.parent_id in suppressed or not is_publicly_visible(row):
            suppressed.add(row.pk)
            continue
        kept.append(row)
    return kept


async def _visible_subtree(info: Info, link_id: int) -> List[models.SocialMediaLink]:
    """This link's publicly-visible descendants, one loader call for both fields.

    ``sublinkCount`` and ``sublinks`` are two views of ONE fetched list, which is
    the whole point: the loader caches per request (``rosak/context.py``
    deep-copies the loader dict), so asking for both costs the same single
    query, and the badge cannot drift from the list it labels because there is
    no second count anywhere in the schema to drift from.

    The moderation filter lives here, once, rather than in each field: it is the
    loader that returns raw rows (see its docstring), and this is the single
    point where they become public GraphQL data.
    """
    rows = await info.context.loaders["incident"]["sublink_subtrees"].load(link_id)
    return _publicly_visible_subtree(rows)


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

    # --- Link hierarchy (see ``SocialMediaLink.parent``) ------------------------
    # ``parent_id`` is the parent link's id, read straight off the row (the FK's
    # attname), so it costs no query and no loader. ``None`` for a root — which
    # is what makes it the client's "walk up to the root from here" handle, and
    # the reason a client must not read it as "this link is in a thread".
    parent_id: Optional[strawberry.ID]

    # This link's SIBLING SEQUENCE: its rank among the children of ITS OWN
    # parent, ascending. Read straight off the row, so it costs no loader and no
    # query — which is the whole reason it is a plain attribute and not a
    # resolver. Exposed because ``reorderSocialMediaLinks`` writes it and,
    # until now, NOTHING COULD READ IT BACK: a client could set an order and
    # never see it confirmed, and the console's sequence column had to be faked
    # from ``occurredAt`` — a different ordering, which would have made reorder
    # meaningless.
    #
    # ⚠️ **IT IS A SIBLING ORDER, NOT A GLOBAL ONE, and the two are not the same
    # list.** ``position`` is scoped to ONE parent, so it is only comparable
    # between two links with the same ``parentId``. It is also the ONLY ordering
    # in this schema that is not ``occurredAt DESC, id DESC``: the feed, the
    # console queue and an incident's ``links`` all order on the event instant,
    # and only ``sublinks`` follows ``position``. Sorting a mixed list of links
    # by it interleaves unrelated conversations.
    #
    # ⚠️ **TWO ROOTS CAN SHARE A VALUE, LEGITIMATELY.** A root's parent is
    # ``None``, so all roots are one sibling set with its own numbering, and
    # ``position`` 10 under root A has nothing to do with ``position`` 10 under
    # root B. So it is never a global tie-break, never a sort key across parents,
    # and never a stable identity — ``id`` is the only thing that identifies a
    # link, and ``(position, id)`` is the order inside one sibling set.
    #
    # ⚠️ **THE NUMBERING IS GAP-SPACED: 10, 20, 30, … — NOT 1, 2, 3.** That is
    # what lets a sibling be inserted between two others without renumbering
    # them, and it means the value is NOT an index: ``position`` 40 does not mean
    # "the fourth", and a client that renders an ordinal from it will be wrong.
    # Nothing constrains it to be unique either — the service renumbers a whole
    # sibling set on every write, a hand-edited row can carry a duplicate, and
    # ``0`` is the column's own default, so it is the value a row written outside
    # ``save()`` carries. Treat it as a number to sort on, never as an index and
    # never as "unset".
    #
    # It is what ``reorderSocialMediaLinks(parentId, linkIds)`` writes: that
    # mutation takes a PERMUTATION of one existing sibling set and renumbers it
    # ``10, 20, 30, …``, so a client reads ``position`` to render the current
    # order and sends the desired one back. Read it, never set it — there is no
    # input for it anywhere in the schema, on purpose: the mutation is the only
    # writer, so a hand-numbered value cannot enter the store through the API.
    position: int

    @strawberry_django.field
    async def is_thread_root(self) -> bool:
        """Whether this link is the TOP of its hierarchy (``parentId`` is null).

        ⚠️ **A root marker, NOT a "has sublinks" marker — and it is true for an
        ordinary ungrouped link too.** ``parentId is None`` describes a link that
        nothing points at, which is exactly as true of a lone link on the feed
        (a "thread" of one) as of the root of a real conversation. So it cannot
        decide whether to draw the "N links" chip or the expand chevron: the only
        correct affordance test is ``sublinkCount > 0`` (``sublinks.length > 0``),
        which is false for a lone link and true for a root that has children.

        Derived from the already-loaded ``parent_id`` attribute: a query here
        would buy nothing (that attribute IS the definition) and would turn a
        20-row feed into 20 extra round trips.
        """
        return self.parent_id is None

    @strawberry_django.field
    async def sublink_count(self, info: Info) -> int:
        """How many publicly-visible links hang BELOW this one, at any depth.

        This is the number the "N links" chip shows, so it counts only
        publicly-visible descendants: a HIDDEN — or unapproved automated — one
        is attached to the tree but not openable by a visitor, and counting it
        would advertise a link that leads nowhere. It is the same rule the feed's
        own queryset-level ``.exclude()`` pair applies, in per-row form
        (``services/social_link_visibility.is_publicly_visible``).

        ⚠️ **It is THIS node's own descendant count, not the size of its tree.**
        A link with sublinks of its own reports those (at every depth below it);
        a childless link reports ``0``. A client that wants the whole
        conversation must walk ``parentId`` up to the root and read the root's
        count. This is the opposite of the depth-1 design it replaces, where a
        member's ``threadSize`` necessarily reported the thread's size because a
        member could not have children of its own — a shape that made
        "recursively ask every node" return the thread size N times, once per
        level. Here it cannot: each node answers for itself, and summing the
        level-by-level counts is how a client would get a number that is wrong by
        the depth it just double-counted.

        ``0`` for a childless link, so ``sublinkCount > 0`` is the only correct
        "draw the affordance" test — ``isThreadRoot`` cannot be used, because it
        is true for every ungrouped link too (see there).

        Derived from the SAME loader call as ``sublinks``, which caches per
        request, rather than from a count query of its own: one query instead of
        two, and the chip is structurally incapable of disagreeing with the list
        it labels. That property is why a descendant whose own parent is not
        publicly visible is excluded from BOTH — counting a link the client
        cannot reach through the nesting would break the agreement the moment
        somebody hid a middle node.
        """
        return len(await _visible_subtree(info, self.id))

    @strawberry_django.field
    async def sublinks(self, info: Info) -> List["SocialMediaLinkScalar"]:
        """This link's DIRECT children, in ``position`` order — the nested list.

        Ordered by ``position``, the sibling sequence ``reorderSocialMediaLinks``
        writes; not by ``occurred_at`` (that is the FEED's ordering — a group is a
        conversation, not a timeline, and its members are not necessarily
        contiguous in time) and not by ``id``.

        ``[]`` for a childless link. That is not an error state, it is the
        overwhelmingly common one, and it is why the chip test is on the count
        rather than on ``isThreadRoot``.

        **Recursive**: every element is a ``SocialMediaLinkScalar`` carrying the
        same ``sublinks`` / ``sublinkCount`` / ``parentId`` fields, so a client
        walks the nesting by asking each child for its own children. What the
        read side returns is bounded by what the STORE holds
        (``MAX_THREAD_DEPTH``, write side) and by what the client selects: a
        deeper selection than we store simply comes back empty, never wrong. The
        loader fetched each subtree whole, so the depth of the tree does not
        change the number of queries.

        Visibility-filtered with the shared predicate, exactly as
        ``sublinkCount`` is — see ``services/social_link_visibility`` for why the
        two copies of the rule (queryset-level and per-row) are deliberate and
        why the filter applies on EVERY surface, ``mine`` included: only the
        queryset-level gates in ``get_public_social_media_links`` are exempt
        there.
        """
        rows = await _visible_subtree(info, self.id)
        # The loader returns the subtree depth-first with siblings already in
        # ``position`` order, so filtering on ``parent_id`` preserves that order:
        # no field sorts, so no two fields can sort the same children differently.
        return [row for row in rows if row.parent_id == self.id]

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
