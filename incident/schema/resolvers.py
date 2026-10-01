from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import List, Optional

import pendulum
import strawberry
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db.models import BigIntegerField, Count, Min, Q, QuerySet
from django.db.models.expressions import RawSQL
from django.utils import timezone
from strawberry.exceptions import GraphQLError
from strawberry.types import Info

from incident.enums import (
    CalendarIncidentSeverity,
    CalendarIncidentStatus,
    PassengerStatus,
    SocialMediaLinkStatus,
)
from incident.models import (
    CalendarIncident,
    CalendarIncidentCategory,
    LineStatusReport,
    SocialMediaLink,
)
from incident.schema.inputs import SocialMediaLinkStatusInput
from incident.schema.keyset import decode_keyset_cursor, encode_keyset_cursor
from incident.schema.mutations.shared import raise_service_error
from incident.schema.scalars import (
    CalendarIncidentGroupByDateSeverityScalar,
    CalendarIncidentHistoryEntryScalar,
    LineStatusHourBucket,
    LineStatusReportConnection,
    LineStatusReportEdge,
    LineStatusReportPageInfo,
    SocialMediaLinkConnection,
    SocialMediaLinkEdge,
    SocialMediaLinkPageInfo,
)
from incident.services.access import get_incident
from incident.services.errors import IncidentServiceError
from incident.services.line_status import load_line_status_history, service_day_start
from operation.schema.scalars import PassengerStatusCount

_HISTORY_TYPE_MAP = {"+": "created", "~": "updated", "-": "deleted"}

# simple-history internal metadata fields — excluded from changed_fields so the
# frontend never sees e.g. "history_date" listed as a changed field.
_HISTORY_INTERNAL_FIELDS = frozenset(
    {
        "history_id",
        "history_date",
        "history_user",
        "history_user_id",
        "history_type",
        "history_change_reason",
    }
)


@strawberry.enum
class GroupByEnum(Enum):
    DAY = "DAY"
    MONTH = "MONTH"


async def get_calendar_incidents_by_severity_count(
    root,
    start_date: strawberry.Maybe[date] = None,
    end_date: strawberry.Maybe[date] = None,
    group_by: GroupByEnum = GroupByEnum.DAY,
) -> List[CalendarIncidentGroupByDateSeverityScalar]:
    if (
        start_date is None
        or end_date is None
        or start_date == strawberry.UNSET
        or end_date == strawberry.UNSET
    ):
        raise GraphQLError("start_date and end_date required")

    start = start_date.value
    end = end_date.value

    return_list = []
    qs = CalendarIncident.objects.filter(
        Q(Q(start_datetime__date__lte=end) & Q(start_datetime__date__gte=start))
        & Q(
            Q(end_datetime__isnull=True)
            | Q(Q(end_datetime__date__gte=start) & Q(end_datetime__date__lte=end))
        )
    )
    min = (await qs.aaggregate(min=Min("start_datetime__date")))["min"]
    today = date.today()

    if min is None:
        return []

    interval = pendulum.interval(
        min if start > min else start,
        today if today < end else end,
    )

    aggregations = {}
    if group_by == GroupByEnum.MONTH:
        range = interval.range("months")
        for range_date in range:
            range_str = range_date.strftime("%Y-%m")
            range_year, range_month = range_str.split("-")

            for severity in CalendarIncidentSeverity.values:
                aggregations[f"{range_str}_{severity}"] = Count(
                    "id",
                    filter=Q(
                        Q(
                            start_datetime__year__lte=range_year,
                            start_datetime__month__lte=range_month,
                        )
                        & Q(
                            Q(
                                end_datetime__year__lte=range_year,
                                end_datetime__month__lte=range_month,
                            )
                            | Q(end_datetime__isnull=True)
                        )
                        & Q(severity=severity)
                    ),
                )

        for key, value in (await qs.aaggregate(**aggregations)).items():
            if value > 0:
                incident_date, severity = key.split("_")
                year, month = incident_date.split("-")

                return_list.append(
                    CalendarIncidentGroupByDateSeverityScalar(
                        date=date(int(year), int(month), 1),
                        severity=severity,
                        count=value,
                        is_long_term=None,
                    )
                )

    elif group_by == GroupByEnum.DAY:
        range = interval.range("days")
        for range_date in range:
            long_term_filter = Q(Q(long_term=True) & Q(start_datetime__date=range_date))

            short_term_filter = Q(
                Q(long_term=False)
                & Q(start_datetime__date__lte=range_date)
                & Q(
                    Q(end_datetime__date__gte=range_date) | Q(end_datetime__isnull=True)
                )
            )

            for term in ["long", "short"]:
                for severity in CalendarIncidentSeverity.values:
                    aggregations[f"{range_date}_{severity}_{term}"] = Count(
                        "id",
                        filter=Q(
                            Q(severity=severity)
                            & Q(
                                long_term_filter
                                if term == "long"
                                else short_term_filter
                            )
                        ),
                    )

        for key, value in (await qs.aaggregate(**aggregations)).items():
            if value > 0:
                incident_date, severity, term = key.split("_")
                year, month, day = incident_date.split("-")

                return_list.append(
                    CalendarIncidentGroupByDateSeverityScalar(
                        date=date(int(year), int(month), int(day)),
                        severity=severity,
                        count=value,
                        is_long_term=True if term == "long" else False,
                    )
                )
    else:
        raise NotImplementedError(
            f"Expected one of 'DAY' or 'MONTH' but got {group_by}"
        )

    return return_list


async def get_pending_calendar_incidents(
    root,
    search: strawberry.Maybe[str] = None,
) -> List[CalendarIncident]:
    """Console approval queue: PENDING_APPROVAL incidents, oldest first — plus LIVE
    incidents that have at least one chronology flagged for deletion (status
    PENDING_DELETION, spec E1) so admins get a surface to approve/reject deletion
    requests (Task 6 mutations). A PENDING_APPROVAL incident's chronologies can never be
    PENDING_DELETION (the request flow is LIVE-only), so the union is clean. ``distinct()``
    deduplicates a LIVE incident carrying several pending-deletion chronologies."""

    queryset = (
        CalendarIncident.objects.filter(
            Q(status=CalendarIncidentStatus.PENDING_APPROVAL)
            | Q(
                status=CalendarIncidentStatus.LIVE,
                chronologies__status=CalendarIncidentStatus.PENDING_DELETION,
            )
        )
        .order_by("created", "id")
        .distinct()
    )

    if search is not None and (term := search.value.strip()):
        queryset = queryset.filter(
            Q(title__icontains=term)
            | Q(brief__icontains=term)
            | Q(details__icontains=term)
            | Q(chronologies__source_url__icontains=term)
        ).distinct()

    return [incident async for incident in queryset]


async def get_social_media_links(
    root,
    search: strawberry.Maybe[str] = None,
    category_id: strawberry.Maybe[strawberry.ID] = None,
    completed: strawberry.Maybe[bool] = None,
    line_id: strawberry.Maybe[strawberry.ID] = None,
    vehicle_id: strawberry.Maybe[strawberry.ID] = None,
    station_id: strawberry.Maybe[strawberry.ID] = None,
    occurred_after: strawberry.Maybe[datetime] = None,
    occurred_before: strawberry.Maybe[datetime] = None,
) -> List[SocialMediaLink]:
    """Console social-media-link queue, newest *occurrence* first.

    Ordered ``-occurred_at, -id``. The queue answers "what happened most
    recently?", which is the same question the public feed answers, so an admin
    moderating the top of this list is looking at the rows a visitor sees at the
    top of the feed. The ``-id`` tie-break makes the order total: ``occurred_at``
    is NOT NULL but is not unique (an admin can group posts that share a
    minute), and a single-key order would leave equal rows in an arbitrary order
    that can change between two identical queries — which, with no cursor here,
    looks like the queue shuffling under the admin.

    ``occurred_after`` / ``occurred_before`` are inclusive (``>=`` / ``<=``) and
    window on ``occurred_at`` — the same column the sort uses, so the filter can
    never exclude the very rows at the top of the list. An admin who needs the
    *submission*-time view ("what did we just get handed?") still has it: it is
    the ``created`` column on every row below.

    ⚠️ **Breaking GraphQL argument rename** (accepted deliberately): the filters
    were ``createdAfter`` / ``createdBefore`` and are now ``occurredAfter`` /
    ``occurredBefore``. The old names are *not* aliased — passing them is a
    GraphQL validation error ("Unknown argument"), not a silent no-op, so a
    stale client fails loudly instead of quietly filtering on the wrong column.
    The admin console is updated in the same change; any other caller must be
    renamed too.
    """

    queryset = SocialMediaLink.objects.all().order_by("-occurred_at", "-id")

    if search is not None and (term := search.value.strip()):
        queryset = queryset.filter(Q(url__icontains=term) | Q(title__icontains=term))

    if category_id is not None:
        queryset = queryset.filter(categories__id=int(category_id.value))

    if completed is not None:
        queryset = queryset.filter(completed=completed.value)

    if line_id is not None:
        queryset = queryset.filter(lines__id=int(line_id.value))

    if vehicle_id is not None:
        queryset = queryset.filter(vehicles__id=int(vehicle_id.value))

    if station_id is not None:
        queryset = queryset.filter(stations__id=int(station_id.value))

    if occurred_after is not None:
        queryset = queryset.filter(occurred_at__gte=occurred_after.value)

    if occurred_before is not None:
        queryset = queryset.filter(occurred_at__lte=occurred_before.value)

    return [link async for link in queryset.distinct()]


def last_week_start(now: datetime) -> datetime:
    """Local midnight starting the 7-day window that ends today.

    With ``USE_TZ = False`` every datetime is naive Asia/Kuala_Lumpur, so this
    is the local midnight six days before ``now`` — the window covers today plus
    the previous six calendar days (seven date groups, inclusive). Mirrors the
    naive-day arithmetic of ``service_day_start``.

    The window is applied to ``occurred_at``, not ``created``: it answers "which
    days is this view showing?", and a backdated report belongs to the day it
    happened. Filtering on ``created`` instead would open the window on
    submission time and admit (or hide) rows whose *event* day is outside it,
    which contradicts the ``occurred_at`` ordering the same page is rendered in.

    This helper supplies the LOWER bound only. The resolver closes the window at
    today's local midnight by default — ``_event_window_before`` — so the
    effective default range is ``[six days ago 00:00, today 00:00)``, i.e. the
    six COMPLETED calendar days rather than seven. Callers that want the
    inclusive form (``displayTodayInLastWeek: true``) simply do not add the
    upper bound; that asymmetry is the flag's entire reason to exist, so it
    belongs at the call site and not hidden inside this helper.
    """
    return datetime.combine((now - timedelta(days=6)).date(), time.min)


def _in_window_subtree_roots(bound: datetime) -> QuerySet:
    """Subquery of the root ids whose subtree holds a link at/after ``bound``.

    The shape is a *single un-correlated* recursive CTE, folded into the
    caller's filter as ``pk__in`` — one SQL statement, one tree walk, no
    per-row subquery. Read ``tree_path[1]`` as "the root of the tree this row
    belongs to", so the set is exactly "the conversations that had something
    happen in this window", which is the question a window asks.

    WHY NOT THE OBVIOUS CORRELATED ``EXISTS``. The previous wave correlated
    ``Exists`` against the outer row's ``pk``, which was a two-hop indexed
    lookup and cheap. The same shape at tree depth means "is any descendant of
    this row in the window", which can only be answered by walking the subtree
    — so the correlated subquery would have to run the recursion *per candidate
    root*. A correlated SubPlan re-executes on every outer row (there is no
    correlation-free part Postgres can hoist out of it), and ``EXPLAIN
    (ANALYZE)`` on the hand-written correlated form shows exactly that: a
    ``Recursive Union`` nested inside ``EXISTS(SubPlan 2)``, i.e. one full
    ``Seq Scan`` of the table as the CTE anchor per row. Un-correlated, the
    planner turns the same work into ``ANY (id = (hashed SubPlan N).col1)`` with
    the subplan at ``loops=1``: the walk happens once, is hashed, and the outer
    scan probes it. One walk per query instead of one per row is the whole
    difference, and the ORM cannot even express the correlated form — its
    ``tree_path__contains`` lookup is literal-only (``OuterRef("pk")`` raises
    ``TypeError: Field 'id' expected a number but got Col(...)``) and
    ``RawSQL`` cannot carry an ``OuterRef`` *parameter*
    (``can't adapt type 'OuterRef'``), so the outer column would have to be
    interpolated as guessed alias text. The un-correlated form is both cheaper
    and the only one that is writable without guessing at aliases.

    WHY THE SUBTREE ROOT AND NOT "THE ANCESTORS OF THE ROW". Because the caller
    filters to roots, the only ancestor that can match a candidate row is the
    root, and every node in a tree shares one — so mapping each in-window node
    to its tree's root loses nothing and yields a set the size of the number of
    conversations rather than the number of links. It also folds the "the root
    itself is in the window" case in for free: a root's own ``tree_path`` is
    ``[root]``, so ``tree_path[1]`` is the root and the row admits itself
    without a second code path. ``_event_window`` still ORs the plain
    ``occurred_at >= bound`` in so the widening is *additive by construction* —
    a root inside the window stays in even if this subquery were wrong.

    WHY THE SUBQUERY IS DELIBERATELY UNFILTERED (no status, no moderation
    excludes, no ``incident_id``). The window asks "what happened in this
    window", and what happened does not stop being a fact because a member was
    hidden — and the moderation asymmetry is *root-only* by design (see
    ``_event_window``), so letting a member's status decide whether its
    conversation appears would smuggle the gate back in through the widening.
    Everything that decides *visibility* stays on the outer query, which is the
    queryset that actually returns rows. The price is that the walk covers the
    whole table rather than the page: bounded by the table, not by page size,
    and paid only when a window flag and ``collapse_threads`` are both on.

    ``RawSQL`` here is not a shortcut past the ORM, it is the one thing the ORM
    has no expression for. ``__tree`` is the CTE django-tree-queries prepends to
    every tree query and inner-joins to the base table on ``__tree.tree_pk =
    socialmedialink.id``; the name is part of that library's compiler contract
    (its own ``TreeColumn`` annotation renders the same identifier, and
    ``TreeJoin.table_name`` is the declaration), not a private detail, and the
    only alternative — a hand-rolled recursive CTE walking ``parent_id`` upward
    — would be a second, unreviewed implementation of the tree in raw SQL. A
    rename upstream surfaces as a ``ProgrammingError`` on the first collapsed
    windowed feed, not as a silently empty list. The ``::bigint`` cast matches
    the pk type so the comparison holds whatever the pk's integer width is; the
    array is 1-based, hence index 1 for the root.

    🔴 ``tree_filter``/``tree_exclude`` — the library's documented performance
    lever — are NOT used here, and applying them to this bound is not merely
    slower, it is **wrong**. They restrict the base table *before* the
    recursion, so filtering the rank table down to the in-window rows deletes
    the out-of-window root from the CTE, the recursion can no longer reach
    anything below it, and each orphaned descendant becomes a root of its own
    truncated tree: ``tree_path[1]`` then returns the descendant instead of the
    conversation's real root, and the widening silently stops working. Verified
    against a 3-level tree whose root and child are both out of window — the
    unfiltered subquery admits the root, the ``tree_filter``-ed one does not. It
    also forfeits the cheap CTE: any tree filter forces the ``__rank_table``
    variant with a ``ROW_NUMBER()`` window over the whole table, where the
    unfiltered query gets the ``__tree``-only template.
    """
    return (
        SocialMediaLink.objects.with_tree_fields()
        .filter(occurred_at__gte=bound)
        .annotate(
            subtree_root=RawSQL(
                "(__tree.tree_path[1])::bigint",
                (),
                output_field=BigIntegerField(),
            )
        )
        # ``.distinct()`` is load-bearing twice over: it is the deduplication the
        # set needs (a conversation with four in-window links would otherwise be
        # listed four times), and it is what suppresses the library's implicit
        # depth-first ``ORDER BY __tree.tree_ordering`` — a sort of every row in
        # the table on an un-indexable computed array, for a subquery whose
        # result is only ever probed for membership. The library skips both the
        # ordering and the tree columns in a ``DISTINCT`` subquery, and an
        # explicit ``.order_by()`` does NOT have that effect (the tree compiler
        # tests truthiness of the ordering, and "no ordering" is empty).
        .distinct()
        .values("subtree_root")
    )


def _event_window(bound: datetime, *, collapse: bool) -> Q:
    """``occurred_at >= bound``, widened to the whole subtree when collapsed.

    On the flat feed a row IS an event, so the window is one comparison. Under
    ``collapse_threads`` a row is a CONVERSATION rendered by its root, and the
    two are no longer the same question: the window asks "did this happen in
    this window?", and a collapsed card's answer is "did *anything* in this
    conversation happen in this window?". Filtering on the root alone answers a
    stricter question than the flag advertises — ``currentServiceDayOnly`` reads
    as "today's activity", not "threads that started today".

    The root-only reading is not a near-miss: grouping elects the EARLIEST link
    as root precisely so a conversation reads oldest-first, which means every
    descendant is LATER than its root by construction. A conversation that
    opened before the window and got a follow-up inside it therefore has a root
    outside the window and a descendant inside it, and the root-keyed filter
    drops the entire conversation from the feed the follow-up belongs in. Since
    the collapsed surface renders the ROOT, the follow-up is then not merely
    unlisted — it is unreachable, which is what makes this worth fixing rather
    than documenting. That shape needs no ``occurredAt`` edit; the editable
    event time only adds the mirror-image case on top of it, where an admin
    moves a descendant EARLIER than its root and the "root is earliest" premise
    stops holding outright.

    Nesting widens this from a corner to the ordinary case, because "in the
    conversation" is now a question about an arbitrary-depth subtree rather than
    a single ``thread`` column: a root two levels above the in-window link is
    the same argument, and a reader who checked only the root's own children
    would have the same defect the first wave fixed, one level up. So the
    widening follows the whole subtree at any depth, and the three properties
    the tests pin hold at every depth: it **admits** a root whose descendant at
    any level is in-window; it never **rescues** a conversation with nothing in
    the window (it is a filter, not an OR that disables itself when the answer
    is no); and it never becomes **restrictive** (a root in-window is admitted
    on its own ``occurred_at``, which the first disjunct states outright).

    ⚠️ **The window is NOT resolved on the root — the moderation gates are, and
    the asymmetry is deliberate, and nesting makes it far more visible.** A
    collapsed row is admitted into ``currentServiceDayOnly`` / ``lastWeekOnly``
    if the ROOT *or any of its descendants* occurred at/after the bound, while
    visibility and status are still decided on the root alone. Under a flat
    thread the gap was one level and easy to read as an oversight; under a tree
    a root can be arbitrarily far from the link that dragged it into a window,
    which is exactly why the two questions must stay separate. Both are the
    fail-safe direction for their own question: a window asks "what happened in
    this window", and a conversation is in it if any part of it was, whereas a
    moderation gate asks "may this be shown", and the cautious answer for a
    shared object is that hiding any representative removes the whole group.
    Conflating them would either leak a hidden descendant into a day-grouped
    feed or drop a just-reported link from today's activity.

    The converse is accepted, not fixed: a root admitted only because a
    descendant is in the window carries the ROOT's (older) timestamp on the
    card, so a "today" feed can show a card stamped before today. Ordering
    stays on the root for the same reason the keyset cursor does — the row is
    the page unit, so a mixed page still has one deterministic order. The card
    nests the in-window link next to it, which is the honest rendering: the
    conversation did have something today.

    Implemented as a subquery (``_in_window_subtree_roots``) rather than a join
    to the descendants on purpose: a join multiplies a root by its number of
    in-window descendants, which would inflate ``totalCount`` and repeat edges
    within one page unless every downstream filter also carried ``.distinct()``.
    A subquery cannot multiply rows, so the collapsed page, its count and its
    keyset are byte-identical to the flat path apart from the extra predicate.
    """
    if not collapse:
        return Q(occurred_at__gte=bound)
    return Q(occurred_at__gte=bound) | Q(pk__in=_in_window_subtree_roots(bound))


def _event_window_before(bound: datetime, *, collapse: bool) -> Q:
    """``occurred_at < bound``, widened to the whole subtree when collapsed.

    The upper-bound counterpart of ``_event_window``, and it exists because a
    window needs BOTH ends: ``_event_window`` answers "did this happen at/after
    the lower bound", this one answers "did this happen strictly before the
    upper bound", and ``lastWeekOnly`` is the only flag that has an upper end
    (it is the flag that must not leak *today* into a "previous days" view).

    The collapse widening is the same question asked in the other direction,
    with the same reasoning and the same deliberate asymmetry against the
    moderation gates: a collapsed card is excluded when the ROOT **or any of its
    descendants, at any depth** occurred at/after ``bound``, because grouping
    elects the EARLIEST link as root, so a conversation that opened before the
    bound and was followed up inside today has a root outside the exclusion and
    a descendant inside it. Resolving that on the root would keep the whole
    conversation — and, since the collapsed surface renders the ROOT, the
    follow-up that belongs in the excluded window with it. The editable
    ``occurredAt`` adds the mirror case on top: an admin who moves a descendant
    LATER than its root breaks the "root is earliest" premise outright, and a
    root-only upper bound would then let a stale root into an exclusion built
    for the wrong reason.

    WHY BOTH CONJUNCTS ARE WRITTEN OUT, since ``~Q(pk__in=…)`` alone already
    covers the root: a root's own ``tree_path`` is ``[root]``, so
    ``tree_path[1]`` is the root and the row admits itself — the negation is
    sufficient. The explicit ``occurred_at__lt`` conjunct is deliberate
    SYMMETRY with ``_event_window`` rather than redundancy being tolerated: the
    lower bound states its own column comparison and widens it with ``|``, so
    the upper bound stating its own and narrowing it with ``&`` makes the two
    read as the same operation pointed the other way. It also keeps the
    predicate honest on the flat path, where the conjunct *is* the whole
    filter, so the collapsed and uncollapsed forms cannot drift apart in the
    one place a reader compares them.

    WHY NO MODERATION FILTERS IN THE SUBQUERY — the same reasoning as
    ``_in_window_subtree_roots``, and for the same reason: what happened does
    not stop being a fact because a member is hidden, and a hidden member must
    not decide whether its conversation survives the exclusion. Everything that
    decides *visibility* stays on the outer query.
    """
    if not collapse:
        return Q(occurred_at__lt=bound)
    return Q(occurred_at__lt=bound) & ~Q(pk__in=_in_window_subtree_roots(bound))


async def get_public_social_media_links(
    root,
    info: Info,
    incident_id: strawberry.Maybe[strawberry.ID] = None,
    line_id: strawberry.Maybe[strawberry.ID] = None,
    first: int = 20,
    after: Optional[str] = None,
    mine: strawberry.Maybe[bool] = None,
    status: strawberry.Maybe[SocialMediaLinkStatusInput] = None,
    current_service_day_only: bool = False,
    last_week_only: bool = False,
    align_page_to_day: bool = False,
    display_today_in_last_week: bool = False,
    collapse_threads: bool = False,
) -> SocialMediaLinkConnection:
    """Public social-media-link feed, cursor-paginated.

    **Ordering —** ``occurred_at DESC, id DESC``. The feed answers "what
    happened most recently?", so the leading key is the *event* time
    (``occurred_at``), not the submission time (``created``), which stays the
    provenance column an admin moderates against. ``occurred_at`` is NOT NULL, so
    the order is total; ``id`` is the tie-break because it is not unique (an
    admin can group posts that share a minute), and without it a cursor could
    both skip and duplicate rows sharing a timestamp. Both window flags below
    are on the same column, deliberately: ordering by ``occurred_at`` while
    windowing by ``created`` puts a backdated report at the top of a day it does
    not belong to.

    **Cursor —** base64("<occurred_at isoformat>|<id>"), the same helper
    ``incident.schema.keyset`` provides. The keyset predicate is
    ``occurred_at < cursor OR (occurred_at = cursor AND id < cursor_id)``. An
    old cursor (one whose payload is a submission timestamp) still *decodes* —
    the payload is an opaque ISO datetime — but it now means "the row after
    this ``occurred_at``", so a cursor minted by an older deployment resumes at
    a position that may skip or repeat rows. In-flight cursors across a deploy
    are therefore not guaranteed to be seamless; relaunch the feed from page one.

    ``mine`` returns only the caller's own links (status-independent);
    anonymous ``mine`` returns an empty page. ``status`` optionally narrows the
    feed to one approval status; omitted, both LIVE and PENDING_APPROVAL are
    returned (unchanged default) — except for automatically ingested posts,
    which are excluded while ``PENDING_APPROVAL`` so an official announcement
    only becomes public once an admin approves it. ``HIDDEN`` rows are never
    returned on this public feed, not even when asked for by name.
    ``current_service_day_only`` keeps only links that *occurred* within the
    current service day (03:00 rollover, see ``service_day_start``).
    ``last_week_only`` keeps only links occurring in the last six COMPLETED
    calendar days — at/after local midnight six days ago (``last_week_start``) and
    strictly before local midnight THIS morning, so the default range is
    ``[six days ago 00:00, today 00:00)`` and a "previous days" view never shows a
    link that happened today. "Today" here is the CALENDAR day, not the service
    day: the cut is plain midnight, deliberately NOT ``service_day_start``'s
    03:00 rollover, because a calendar-day view that opened at 03:00 would hide
    the first three hours of this morning from the reader. It composes with
    ``current_service_day_only`` (both narrow the same queryset).
    ``display_today_in_last_week`` (default ``False``) is the single opt-out: it
    drops the upper bound and restores the inclusive seven-day window
    ``occurred_at >=`` six-days-ago midnight, today included. It is inert when
    ``last_week_only`` is ``False`` — there is no other upper bound to lift, and
    inventing one would make the flag mean two different things.
    The exclusion is applied before ``totalCount``, so the count reports the rows
    the page can actually show.

    ``collapse_threads`` (default ``False``) swaps the flat link list for
    conversation roots — see below. ``totalCount`` is the size of the whole
    filtered set after *every* narrowing (window flags, ``status``, and the
    collapse when requested), unaffected by the ``after`` cursor and by
    ``align_page_to_day``, so "Showing N of M" stays truthful: M counts what the
    surface can show, not what a flat list would have contained.

    ``align_page_to_day`` makes a page never end mid-day. After the standard
    ``first + 1`` lookahead fetch, if the lookahead row falls on the same local
    calendar day as the page's last row — compared on ``occurred_at``, so "the
    day" means the event day, the day the card groups under — every remaining
    row of that day is appended, so the page may exceed ``first`` — there is
    **no cap**: a whole day lands on one page even when that day alone is larger
    than ``first``. ``endCursor`` then points at that day's last row and
    ``hasNextPage`` probes for any row after it. A lookahead on a different day
    leaves the page exactly as it would be without alignment. Both flags default
    to ``False``.

    ``collapse_threads`` — conversation-root pages over the link tree.

    When ``true`` the queryset is narrowed to tree roots (``parent IS NULL``)
    and each root carries its subtree through the scalar's ``sublinks`` /
    ``sublinkCount``, so a page of N cards shows N conversations rather than the
    first N fragments of them. "Thread" is now a *tree*, not a flat group: a
    root can have children, children can have their own children, and only the
    roots are page units. The narrowing happens *before* the count and before
    the cursor, so ``totalCount`` counts roots.

    Why roots must be paginated rather than grouped client-side: with
    ``occurred_at`` ordering, a conversation's descendants are **not** adjacent.
    An admin can group a 09:00 post with an 11:00 post, and between them sit
    whatever else happened — including sublinks of *other* conversations. A flat
    page is therefore not a superset of whole conversations, so no
    post-processing of one page can reconstruct the grouping: a descendant's
    root may not even be on the page. Paginating over roots and nesting the
    subtree is the only shape in which "every conversation that starts here is
    fully shown" is true — and with nesting, "fully shown" also means every
    level of it, which is why the read side fetches a whole subtree in one
    query rather than a level at a time.

    The visibility rule that follows from it: **a conversation is public iff its
    root is public**, so hiding a root hides its whole subtree on a collapsed
    surface (the gates below are queryset-level and see the root row). That
    coupling is accepted rather than worked around — the console shows each
    row's ``sublinkCount``, so an admin can see what a moderation decision will
    take with it before making it.

    ⚠️ **The time windows are NOT resolved on the root — the moderation gates
    are, and the asymmetry is deliberate and load-bearing here.** A collapsed
    row is admitted into ``currentServiceDayOnly`` / ``lastWeekOnly`` if the
    ROOT *or any of its descendants, at any depth* occurred at/after the bound
    (``_event_window``), while visibility and status are still decided on the
    root alone. The ``lastWeekOnly`` UPPER bound is subtree-aware in the same
    way and for the same reason (``_event_window_before``): a conversation is
    excluded when the root **or any descendant at any depth** occurred at/after
    today's midnight, so "this view does not show today" holds for the card as
    the reader sees it and not merely for the row the group happens to render.
    Resolving that end on the root alone would let a stale root — the ordinary
    shape, since grouping elects the earliest link — carry a today follow-up
    into a view that is supposed to be the previous days. Both are the fail-safe direction for their own question: a
    window asks "what happened in this window", and a conversation is in it if
    any part of it was, whereas a moderation gate asks "may this be shown", and
    the cautious answer for a shared object is that hiding any representative
    removes the whole group. Conflating them would either leak a hidden
    descendant into a day-grouped feed or drop a just-reported link from
    today's activity. Nesting is what makes the split non-negotiable: the
    distance between the row that is moderated and the row that happened is no
    longer bounded by one hop, so a single shared rule could not serve both
    questions.

    This is not a rare corner. Grouping elects the earliest link as root so the
    conversation reads oldest-first, so descendants are LATER than the root by
    construction: any conversation that opened before the window and got a
    follow-up inside it has a root outside the window and a descendant inside
    it — at depth 1 or, once sublinks have their own sublinks, at depth 2+.
    Resolved on the root, the whole conversation — and with it the follow-up,
    since the collapsed surface renders the root — vanished from the day's
    feed. Making ``occurredAt`` editable adds the mirror case (an admin moves a
    descendant earlier than its root, so "the root is earliest" stops being an
    invariant), which is why the root-only reading could not be left as a
    documented quirk.

    The accepted consequence: a root admitted only because a descendant is in
    the window renders with the ROOT's older ``occurredAt`` on its card, so a
    "today" feed can show a card stamped before today. It is a rendering quirk,
    not a filter bug — the link is reachable, and its conversation is exactly
    where the user expects it. Re-grouping the conversation (the console's
    "Group into thread" over the whole set) re-elects the earliest link as root
    and makes the card's timestamp correct again.

    ``collapse_threads`` is **ignored when ``mine`` is requested**: "My
    Submitted Links" is the caller's own list of their own submissions, where
    every row they submitted is the row they expect to find, so sublinks are
    never collapsed there. ``mine`` also stays ungated by moderation, for the
    same personal reason (see the excludes below).
    """

    mine_requested = mine is not None and mine.value
    # Tree collapse is a *feed* affordance, so it is suppressed for ``mine``:
    # that page is the caller's own list of their own submissions, and hiding
    # their own sublinks behind a root would be data loss on a personal list.
    collapse_requested = collapse_threads and not mine_requested
    if mine_requested:
        user = info.context.user
        if not user:
            return SocialMediaLinkConnection(
                edges=[],
                page_info=SocialMediaLinkPageInfo(has_next_page=False, end_cursor=None),
                total_count=0,
            )
        queryset = SocialMediaLink.objects.filter(user=user)
    else:
        queryset = SocialMediaLink.objects.all()

    if incident_id is not None:
        content_type = await sync_to_async(ContentType.objects.get_for_model)(
            CalendarIncident
        )
        queryset = queryset.filter(
            content_type=content_type, object_id=int(incident_id.value)
        )

    if line_id is not None:
        queryset = queryset.filter(lines__id=int(line_id.value))

    if status is not None:
        queryset = queryset.filter(status=status.value)

    # Moderation gate: a HIDDEN row is never public. Applied *after* the
    # optional status narrowing, so ``status: HIDDEN`` returns an empty page
    # instead of resurrecting what the moderation decision removed — the same
    # defeat-by-exclusion shape as the automated-pending gate below, and before
    # the count so totalCount and the page always agree.
    #
    # The same rule exists as a per-row predicate,
    # ``incident.services.social_link_visibility.is_publicly_visible``, which is
    # the single source of truth and is what non-queryset code (the scalar's
    # ``sublinks`` / ``sublinkCount``) imports. These two excludes are its
    # queryset-level twin and are deliberately NOT replaced by it: a per-row
    # Python filter would not shrink ``totalCount`` or the fetched page, so page
    # and count would stop agreeing. Any change to the rule must be made in the
    # shared predicate first.
    #
    # Deliberately not applied to ``mine``: that page is the owner's own
    # submission list, not a public feed, so a person can still see (and seek
    # admin help with) a submission an admin has hidden from everyone else.
    if not mine_requested:
        queryset = queryset.exclude(status=SocialMediaLinkStatus.HIDDEN)

    # Approval gates publication for automatically ingested posts: an
    # unapproved official post is not public. Scoped to is_automated on
    # purpose — a *community* link awaiting approval keeps today's behaviour
    # and still surfaces (with its pending icon), so hiding pending rows
    # wholesale would silently hide hand-submitted reports too. Applied before
    # the count so totalCount and the page both agree with what is published.
    # See the shared-predicate note above: same rule, queryset-level form.
    queryset = queryset.exclude(
        is_automated=True, status=SocialMediaLinkStatus.PENDING_APPROVAL
    )

    # Thread collapse, before both the count and the cursor: a collapsed page
    # paginates over roots and nests the subtree on each root, so "M of M" must
    # count roots too. Placed after the moderation gates because visibility is
    # decided on the root row — a conversation is public iff its root is.
    #
    # ``parent__isnull`` is CHEAPER than the flat ``thread`` column it replaces,
    # not merely differently spelled. Both are plain indexed null tests on a
    # self-FK, but the old column existed only to *mark membership* — a second
    # statement of something ``parent`` now says structurally. "Is a root" and
    # "has no parent" are the same question here, so the narrowing costs what
    # the old one did and reads as the data model instead of a convention.
    if collapse_requested:
        queryset = queryset.filter(parent__isnull=True)

    # The windows run AFTER the collapse narrowing above, so on a collapsed page
    # they are evaluated over the whole subtree, not over the root that
    # represents it — see ``_event_window``. Without the collapse they are the
    # plain single-column comparison, unchanged, which is the point of the
    # ``collapse`` flag: the recursive subquery that widens the window is built
    # only on the collapsed path, so no other surface pays for it.
    #
    # ``now`` is captured ONCE and shared by both bounds, so the two ends of the
    # ``lastWeekOnly`` window cannot straddle a midnight: a request that landed
    # at 23:59:59.9 must not open on yesterday's arithmetic and close on
    # today's.
    now = timezone.now()
    if current_service_day_only:
        queryset = queryset.filter(
            _event_window(service_day_start(now), collapse=collapse_requested)
        )

    if last_week_only:
        queryset = queryset.filter(
            _event_window(last_week_start(now), collapse=collapse_requested)
        )
        # Today is excluded by default: the flag reads as "the last few days",
        # and a view that silently includes the day in progress is neither
        # complete (it changes under the reader) nor comparable with the day
        # groups it is rendered next to. The cut is CALENDAR midnight, not the
        # 03:00 service-day rollover, so it matches the day headers the same page
        # draws. Placed before the count below, so ``totalCount`` and the page
        # agree; and subtree-aware under collapse, so "no today on this card"
        # holds for the whole conversation rather than only for its root. The
        # opt-out is a single absent filter, not a second window definition.
        if not display_today_in_last_week:
            queryset = queryset.filter(
                _event_window_before(
                    datetime.combine(now.date(), time.min),
                    collapse=collapse_requested,
                )
            )

    # Count before the cursor filter: a cursor narrows the page, not the feed.
    total_count = await queryset.acount()

    queryset = queryset.order_by("-occurred_at", "-id")

    if after is not None:
        cursor_occurred_at, cursor_id = decode_keyset_cursor(after)
        queryset = queryset.filter(
            Q(occurred_at__lt=cursor_occurred_at)
            | Q(occurred_at=cursor_occurred_at, id__lt=cursor_id)
        )

    # Fetch first + 1 to determine has_next_page without a separate count.
    raw_rows = [link async for link in queryset[: first + 1]]
    # A negative ``first`` must not index the list (raw_rows[first] would raise
    # IndexError); guard it so the legacy empty-page result is preserved.
    lookahead = raw_rows[first] if first >= 0 and len(raw_rows) > first else None
    rows = raw_rows[:first]
    has_next_page = lookahead is not None

    # Complete-day page: when the lookahead shares the last row's calendar day,
    # pull in the lookahead and every remaining row of that same day (no cap, so
    # a whole day lands together even if it exceeds ``first``). The keyset
    # predicate starts *at* the lookahead, so no row is dropped between the page
    # and the continuation; the queryset's own ordering preserves -occurred_at, -id.
    if (
        align_page_to_day
        and lookahead is not None
        and rows
        and lookahead.occurred_at.date() == rows[-1].occurred_at.date()
    ):
        rows = rows + [lookahead]
        # Half-open naive-local day range instead of ``occurred_at__date`` so
        # the range can use the ``occurred_at`` index (a date cast cannot).
        day_start = datetime.combine(lookahead.occurred_at.date(), time.min)
        rows += [
            link
            async for link in queryset.filter(
                Q(
                    occurred_at__gte=day_start,
                    occurred_at__lt=day_start + timedelta(days=1),
                ),
                Q(occurred_at__lt=lookahead.occurred_at)
                | Q(occurred_at=lookahead.occurred_at, id__lt=lookahead.id),
            )
        ]
        last = rows[-1]
        has_next_page = await queryset.filter(
            Q(occurred_at__lt=last.occurred_at)
            | Q(occurred_at=last.occurred_at, id__lt=last.id)
        ).aexists()

    edges = [
        SocialMediaLinkEdge(
            node=link, cursor=encode_keyset_cursor(link.occurred_at, link.id)
        )
        for link in rows
    ]

    end_cursor = edges[-1].cursor if edges else None

    return SocialMediaLinkConnection(
        edges=edges,
        page_info=SocialMediaLinkPageInfo(
            has_next_page=has_next_page, end_cursor=end_cursor
        ),
        total_count=total_count,
    )


async def get_calendar_incident_categories(root) -> List[CalendarIncidentCategory]:
    return [
        category async for category in CalendarIncidentCategory.objects.order_by("name")
    ]


async def get_calendar_incident_history(
    root,
    info: Info,
    id: strawberry.ID,
    limit: int = 50,
) -> List[CalendarIncidentHistoryEntryScalar]:
    """History entries for a CalendarIncident, latest-first.

    Returns django-simple-history records diffed to show what changed, capped
    at ``limit`` entries (default 50) to avoid loading the full history table.
    Each entry carries the timestamp, actor, change type, and the list of model
    field names that changed since the previous record.

    Soft-deleted incidents are treated as non-existent (the alive manager
    lookup raises ``IncidentServiceError``) — consistent with ``get_incident``.

    No DataLoader needed: this query targets a single incident by id and
    fetches its history in one query (``select_related("history_user")`` joins
    the actor so resolving ``actor`` needs no N+1). History is per-incident
    data that cannot be batched across multiple parent ids.
    """
    try:
        incident = await get_incident(int(id))
    except IncidentServiceError as exc:
        raise GraphQLError(str(exc)) from exc

    records = [
        record
        async for record in incident.history.select_related("history_user").order_by(
            "-history_date"
        )[:limit]
    ]

    entries: List[CalendarIncidentHistoryEntryScalar] = []
    for i, record in enumerate(records):
        change_type = _HISTORY_TYPE_MAP.get(record.history_type, "unknown")

        if record.history_type == "+":
            changed_fields = ["created"]
        elif record.history_type == "-":
            changed_fields = ["deleted"]
        elif i + 1 < len(records):
            delta = record.diff_against(records[i + 1])
            changed_fields = [
                change.field
                for change in delta.changes
                if change.field not in _HISTORY_INTERNAL_FIELDS
            ]
        else:
            prev = record.prev_record
            if prev is None:
                changed_fields = ["created"]
            else:
                delta = record.diff_against(prev)
                changed_fields = [
                    change.field
                    for change in delta.changes
                    if change.field not in _HISTORY_INTERNAL_FIELDS
                ]

        actor: Optional[str] = None
        if record.history_user is not None:
            # The history_user FK targets settings.AUTH_USER_MODEL (auth.User);
            # use str() for a model-agnostic display identity (username for
            # auth.User, firebase_id[:8] for common.User) rather than assuming
            # a display_name attribute that only common.User defines.
            actor = str(record.history_user)

        entries.append(
            CalendarIncidentHistoryEntryScalar(
                timestamp=record.history_date,
                actor=actor,
                change_type=change_type,
                changed_fields=changed_fields,
            )
        )

    return entries


async def get_line_status_history(
    root,
    info: Info,
    line_id: strawberry.ID,
    day_start_hour: Optional[int] = 3,
) -> List[LineStatusHourBucket]:
    """Hourly passenger-status history for one line over its current service day.

    Buckets always cover the whole service day — all 24 hours from the
    service-day start (``dayStartHour``, default 03:00) through 02:00, empty
    hours included. A line with no report that service day returns an empty
    list, which the frontend renders as its "No data" placeholder. One query
    per call.
    """
    if day_start_hour is None:
        day_start_hour = 3
    try:
        buckets = await load_line_status_history(
            int(line_id), day_start_hour=day_start_hour
        )
    except IncidentServiceError as exc:
        raise_service_error(exc)

    return [
        LineStatusHourBucket(
            hour_start=bucket.hour_start,
            hour_end=bucket.hour_end,
            count=bucket.count,
            dominant_status=PassengerStatus(bucket.dominant_status)
            if bucket.dominant_status
            else None,
            status_counts=[
                PassengerStatusCount(
                    status=status, count=bucket.status_counts[status.value]
                )
                for status in PassengerStatus
                if bucket.status_counts.get(status.value, 0) >= 1
            ],
        )
        for bucket in buckets
    ]


async def get_line_status_reports(
    root,
    info: Info,
    line_id: strawberry.ID,
    first: int = 20,
    after: Optional[str] = None,
) -> LineStatusReportConnection:
    """Per-line status reports, newest first (``created DESC, id DESC``).

    Keyset-paginated like ``publicSocialMediaLinks``: the cursor is
    base64("<created iso>|<id>") and the predicate is ``created < cursor OR
    (created = cursor AND id < cursor_id)``. ``first + 1`` rows are fetched to
    derive ``has_next_page`` without a count query. Filters on the plain
    ``line`` FK (not the report's station M2M).
    """
    queryset = (
        LineStatusReport.objects.filter(line_id=int(line_id))
        .select_related("user")
        .order_by("-created", "-id")
    )

    if after is not None:
        cursor_created, cursor_id = decode_keyset_cursor(after)
        queryset = queryset.filter(
            Q(created__lt=cursor_created) | Q(created=cursor_created, id__lt=cursor_id)
        )

    rows = [report async for report in queryset[: first + 1]]
    has_next_page = len(rows) > first
    rows = rows[:first]

    edges = [
        LineStatusReportEdge(
            node=report, cursor=encode_keyset_cursor(report.created, report.id)
        )
        for report in rows
    ]

    return LineStatusReportConnection(
        edges=edges,
        page_info=LineStatusReportPageInfo(
            has_next_page=has_next_page,
            end_cursor=edges[-1].cursor if edges else None,
        ),
    )
