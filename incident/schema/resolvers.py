from datetime import date
from enum import Enum
from typing import List

import pendulum
import strawberry
from django.db.models import Count, Min, Q

from incident.enums import CalendarIncidentSeverity
from incident.models import CalendarIncident
from incident.schema.scalars import CalendarIncidentGroupByDateSeverityScalar


@strawberry.enum
class GroupByEnum(Enum):
    DAY = "DAY"
    MONTH = "MONTH"


async def get_calendar_incidents_by_severity_count(
    root,
    start_date: date,
    end_date: date,
    group_by: GroupByEnum,
) -> List[CalendarIncidentGroupByDateSeverityScalar]:
    assert start_date != strawberry.UNSET and end_date != strawberry.UNSET

    return_list = []
    qs = CalendarIncident.objects.filter(
        Q(
            Q(start_datetime__date__lte=end_date)
            & Q(start_datetime__date__gte=start_date)
        )
        & Q(
            Q(end_datetime__isnull=True)
            | Q(
                Q(end_datetime__date__gte=start_date)
                & Q(end_datetime__date__lte=end_date)
            )
        )
    )
    min = (await qs.aaggregate(min=Min("start_datetime__date")))["min"]
    today = date.today()

    if min is None:
        return []

    period = pendulum.period(
        min if start_date > min else start_date,
        today if today < end_date else end_date,
    )

    aggregations = {}
    if group_by == GroupByEnum.MONTH:
        range = period.range("months")
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
                    )
                )

    elif group_by == GroupByEnum.DAY:
        range = period.range("days")
        for range_date in range:
            for severity in CalendarIncidentSeverity.values:
                aggregations[f"{range_date}_{severity}"] = Count(
                    "id",
                    filter=Q(
                        Q(start_datetime__date__lte=range_date)
                        & Q(
                            Q(end_datetime__date__gte=range_date)
                            | Q(end_datetime__isnull=True)
                        )
                        & Q(severity=severity)
                    ),
                )

        for key, value in (await qs.aaggregate(**aggregations)).items():
            if value > 0:
                incident_date, severity = key.split("_")
                year, month, day = incident_date.split("-")

                return_list.append(
                    CalendarIncidentGroupByDateSeverityScalar(
                        date=date(int(year), int(month), int(day)),
                        severity=severity,
                        count=value,
                    )
                )
    else:
        raise NotImplementedError(
            f"Expected one of 'DAY' or 'MONTH' but got {group_by}"
        )

    return return_list
