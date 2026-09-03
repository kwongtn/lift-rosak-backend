from datetime import date, datetime
from enum import Enum
from typing import List, Optional

import pendulum
import strawberry
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Min, Q
from strawberry.exceptions import GraphQLError
from strawberry.types import Info

from incident.enums import CalendarIncidentSeverity, CalendarIncidentStatus
from incident.models import CalendarIncident, CalendarIncidentCategory, SocialMediaLink
from incident.schema.keyset import decode_keyset_cursor, encode_keyset_cursor
from incident.schema.scalars import (
    CalendarIncidentGroupByDateSeverityScalar,
    CalendarIncidentHistoryEntryScalar,
    SocialMediaLinkConnection,
    SocialMediaLinkEdge,
    SocialMediaLinkPageInfo,
)
from incident.services.access import get_incident
from incident.services.errors import IncidentServiceError

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
    created_after: strawberry.Maybe[datetime] = None,
    created_before: strawberry.Maybe[datetime] = None,
) -> List[SocialMediaLink]:
    """Console social-media-link queue, newest submissions first."""

    queryset = SocialMediaLink.objects.all().order_by("-created")

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

    if created_after is not None:
        queryset = queryset.filter(created__gte=created_after.value)

    if created_before is not None:
        queryset = queryset.filter(created__lte=created_before.value)

    return [link async for link in queryset.distinct()]


async def get_public_social_media_links(
    root,
    info: Info,
    incident_id: strawberry.Maybe[strawberry.ID] = None,
    line_id: strawberry.Maybe[strawberry.ID] = None,
    first: int = 20,
    after: Optional[str] = None,
    mine: strawberry.Maybe[bool] = None,
) -> SocialMediaLinkConnection:
    """Public social-media-link feed, cursor-paginated.

    Cursor is base64("<created_iso>|<id>"); ordering is created DESC, id DESC
    (id as tiebreaker) so keyset cursors never skip/duplicate. ``mine`` returns
    only the caller's own links (status-independent); anonymous ``mine`` returns
    an empty page.
    """

    if mine is not None and mine.value:
        user = info.context.user
        if not user:
            return SocialMediaLinkConnection(
                edges=[],
                page_info=SocialMediaLinkPageInfo(has_next_page=False, end_cursor=None),
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

    queryset = queryset.order_by("-created", "-id")

    if after is not None:
        cursor_created, cursor_id = decode_keyset_cursor(after)
        queryset = queryset.filter(
            Q(created__lt=cursor_created) | Q(created=cursor_created, id__lt=cursor_id)
        )

    # Fetch first + 1 to determine has_next_page without a separate count.
    rows = [link async for link in queryset[: first + 1]]
    has_next_page = len(rows) > first
    rows = rows[:first]

    edges = [
        SocialMediaLinkEdge(
            node=link, cursor=encode_keyset_cursor(link.created, link.id)
        )
        for link in rows
    ]

    end_cursor = edges[-1].cursor if edges else None

    return SocialMediaLinkConnection(
        edges=edges,
        page_info=SocialMediaLinkPageInfo(
            has_next_page=has_next_page, end_cursor=end_cursor
        ),
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
