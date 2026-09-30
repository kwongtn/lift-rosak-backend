from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import List, Optional

import pendulum
import strawberry
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Exists, Min, OuterRef, Q
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
    """
    return datetime.combine((now - timedelta(days=6)).date(), time.min)


def _event_window(bound: datetime, *, collapse: bool) -> Q:
    """``occurred_at >= bound``, widened to the whole thread when collapsed.

    On the flat feed a row IS an event, so the window is one comparison. Under
    ``collapse_threads`` a row is a THREAD rendered by its root, and the two are
    no longer the same question: the window asks "did this happen in this
    window?", and a collapsed card's answer is "did *anything* in this
    conversation happen in this window?". Filtering on the root alone answers a
    stricter question than the flag advertises — ``currentServiceDayOnly`` reads
    as "today's activity", not "threads that started today".

    The root-only reading is not a near-miss: grouping elects the EARLIEST link
    as root precisely so a thread reads oldest-first, which means every member
    is LATER than its root by construction. A conversation that opened before
    the window and got a follow-up inside it therefore has a root outside the
    window and a member inside it, and the root-keyed filter drops the entire
    thread from the feed the follow-up belongs in. Since the collapsed surface
    renders the ROOT, the member is then not merely unlisted — it is
    unreachable, which is what makes this worth fixing rather than documenting.
    That shape needs no ``occurredAt`` edit; the editable event time only adds
    the mirror-image case on top of it, where an admin moves a member EARLIER
    than its root and the "root is earliest" premise stops holding outright.

    The converse is accepted, not fixed: a root admitted only because a member
    is in the window carries the ROOT's (older) timestamp on the card, so a
    "today" feed can show a card stamped before today. Ordering stays on the
    root for the same reason the keyset cursor does — the row is the page unit,
    so a mixed-thread page still has one deterministic order. The card nests the
    in-window member next to it, which is the honest rendering: the
    conversation did have something today.

    Implemented as a correlated ``EXISTS`` rather than a join to
    ``thread_members`` on purpose: a join multiplies a root by its number of
    in-window members, which would inflate ``totalCount`` and repeat edges
    within one page unless every downstream filter also carried ``.distinct()``.
    ``Exists`` cannot multiply rows, so the collapsed page, its count and its
    keyset are byte-identical to the flat path apart from the extra predicate.
    """
    if not collapse:
        return Q(occurred_at__gte=bound)
    return Q(occurred_at__gte=bound) | Exists(
        SocialMediaLink.objects.filter(thread_id=OuterRef("pk"), occurred_at__gte=bound)
    )


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
    ``last_week_only`` keeps only links occurring at/after local midnight six
    days ago — today plus the previous six calendar days, a seven-day window
    (see ``last_week_start``); it composes with ``current_service_day_only``
    (both narrow the same queryset).

    ``collapse_threads`` (default ``False``) swaps the flat member list for
    thread roots — see below. ``totalCount`` is the size of the whole filtered
    set after *every* narrowing (window flags, ``status``, and thread collapse
    when requested), unaffected by the ``after`` cursor and by
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

    ``collapse_threads`` — thread-root pages.

    When ``true`` the queryset is narrowed to thread roots
    (``thread IS NULL``) and each root carries its members through the scalar's
    ``threadLinks`` / ``threadSize``, so a page of N cards shows N conversations
    rather than the first N fragments of them. The narrowing happens *before*
    the count and before the cursor, so ``totalCount`` counts roots.

    Why roots must be paginated rather than grouped client-side: with
    ``occurred_at`` ordering, a thread's members are **not** adjacent. An admin
    can group a 09:00 post with an 11:00 post, and between them sit whatever
    else happened — including members of *other* threads. A flat page is
    therefore not a superset of whole threads, so no post-processing of one page
    can reconstruct the grouping: a member's root may not even be on the page.
    Paginating over roots and nesting the members is the only shape in which
    "every conversation that starts here is fully shown" is true.

    The visibility rule that follows from it: **a thread is public iff its root
    is public**, so hiding a root hides its whole thread on a collapsed surface
    (the gates below are queryset-level and see the root row). That coupling is
    accepted rather than worked around — the console shows each row's
    ``threadSize``, so an admin can see what a moderation decision will take
    with it before making it.

    ⚠️ **The time windows are NOT resolved on the root — the moderation gates
    are, and the asymmetry is deliberate.** A collapsed row is admitted into
    ``currentServiceDayOnly`` / ``lastWeekOnly`` if the ROOT *or any of its
    members* occurred at/after the bound (``_event_window``), while visibility
    and status are still decided on the root alone. Both are the fail-safe
    direction for their own question: a window asks "what happened in this
    window", and a thread is in it if any part of it was, whereas a moderation
    gate asks "may this be shown", and the cautious answer for a shared object
    is that hiding any representative removes the whole group. Conflating them
    would either leak a hidden member into a day-grouped feed or drop a
    just-reported link from today's activity.

    This is not a rare corner. Grouping elects the earliest link as root so the
    thread reads oldest-first, so members are LATER than the root by
    construction: any conversation that opened before the window and got a
    follow-up inside it has a root outside the window and a member inside it.
    Resolved on the root, the whole thread — and with it the follow-up, since
    the collapsed surface renders the root — vanished from the day's feed.
    Making ``occurredAt`` editable adds the mirror case (an admin moves a member
    earlier than its root, so "the root is earliest" stops being an invariant),
    which is why the root-only reading could not be left as a documented quirk.

    The accepted consequence: a root admitted only because a member is in the
    window renders with the ROOT's older ``occurredAt`` on its card, so a
    "today" feed can show a card stamped before today. It is a rendering quirk,
    not a filter bug — the link is reachable, and its thread is exactly where
    the user expects it. Re-grouping the thread (the console's "Group into
    thread" over the whole set) re-elects the earliest link as root and makes
    the card's timestamp correct again.

    ``collapse_threads`` is **ignored when ``mine`` is requested**: "My
    Submitted Links" is the caller's own list of their own submissions, where
    every row they submitted is the row they expect to find, so members are
    never collapsed there. ``mine`` also stays ungated by moderation, for the
    same personal reason (see the excludes below).
    """

    mine_requested = mine is not None and mine.value
    # Thread collapse is a *feed* affordance, so it is suppressed for ``mine``:
    # that page is the caller's own list of their own submissions, and hiding
    # their own members behind a root would be data loss on a personal list.
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
    # the single source of truth and is what non-queryset code (the scalar
    # thread fields) imports. These two excludes are its queryset-level twin and
    # are deliberately NOT replaced by it: a per-row Python filter would not
    # shrink ``totalCount`` or the fetched page, so page and count would stop
    # agreeing. Any change to the rule must be made in the shared predicate first.
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
    # paginates over roots and nests the members on each root, so "M of M" must
    # count roots too. Placed after the moderation gates because visibility is
    # decided on the root row — a thread is public iff its root is public.
    if collapse_requested:
        queryset = queryset.filter(thread__isnull=True)

    # The windows run AFTER the collapse narrowing above, so on a collapsed page
    # they are evaluated over the whole thread, not over the root that represents
    # it — see ``_event_window``. Without the collapse they are the plain
    # single-column comparison, unchanged.
    if current_service_day_only:
        queryset = queryset.filter(
            _event_window(
                service_day_start(timezone.now()), collapse=collapse_requested
            )
        )

    if last_week_only:
        queryset = queryset.filter(
            _event_window(last_week_start(timezone.now()), collapse=collapse_requested)
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
