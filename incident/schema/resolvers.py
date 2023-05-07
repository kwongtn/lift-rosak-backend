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

    if group_by == GroupByEnum.MONTH:
        raise NotImplementedError()

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

    period = pendulum.period(
        min if start_date > min else start_date,
        today if today < end_date else end_date,
    )
    range = period.range("days")

    aggregations = {}
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

    return_list = []
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

    return return_list
