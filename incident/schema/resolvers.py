from datetime import date
from enum import Enum
from typing import List

import pendulum
import strawberry
from django.db.models import Count, Min, Q
from strawberry.exceptions import GraphQLError

from incident.enums import CalendarIncidentSeverity, CalendarIncidentStatus
from incident.models import CalendarIncident, CalendarIncidentCategory, SocialMediaLink
from incident.schema.scalars import CalendarIncidentGroupByDateSeverityScalar


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
    """Console approval queue: PENDING_APPROVAL incidents, oldest first."""

    queryset = CalendarIncident.objects.filter(
        status=CalendarIncidentStatus.PENDING_APPROVAL
    ).order_by("created", "id")

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
) -> List[SocialMediaLink]:
    """Console social-media-link queue, newest submissions first."""

    queryset = SocialMediaLink.objects.all().order_by("-created")

    if search is not None and (term := search.value.strip()):
        queryset = queryset.filter(Q(url__icontains=term) | Q(title__icontains=term))

    if category_id is not None:
        queryset = queryset.filter(categories__id=int(category_id.value))

    if completed is not None:
        queryset = queryset.filter(completed=completed.value)

    return [link async for link in queryset.distinct()]


async def get_public_social_media_links(
    root,
    line_id: strawberry.Maybe[strawberry.ID] = None,
) -> List[SocialMediaLink]:
    queryset = SocialMediaLink.objects.all().order_by("-created")

    if line_id is not None:
        queryset = queryset.filter(lines__id=line_id.value)

    return [link async for link in queryset.distinct()]


async def get_calendar_incident_categories(root) -> List[CalendarIncidentCategory]:
    return [
        category async for category in CalendarIncidentCategory.objects.order_by("name")
    ]
