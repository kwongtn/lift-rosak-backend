from typing import List

import strawberry
import strawberry_django

from incident.schema.filters import (
    CalendarIncidentFilter,
    StationIncidentFilter,
    VehicleIncidentFilter,
)
from incident.schema.orderings import CalendarIncidentOrder
from incident.schema.resolvers import get_calendar_incidents_by_severity_count
from incident.schema.scalars import (
    CalendarIncidentGroupByDateSeverityScalar,
    CalendarIncidentScalar,
    StationIncident,
    VehicleIncident,
)


@strawberry.type
class IncidentScalars:
    vehicle_incidents: List[VehicleIncident] = strawberry_django.field(
        filters=VehicleIncidentFilter
    )
    station_incidents: List[StationIncident] = strawberry_django.field(
        filters=StationIncidentFilter
    )

    calendar_incidents: List[CalendarIncidentScalar] = strawberry_django.field(
        filters=CalendarIncidentFilter,
        order=CalendarIncidentOrder,
    )

    calendar_incidents_by_severity_count: List[
        CalendarIncidentGroupByDateSeverityScalar
    ] = strawberry.field(resolver=get_calendar_incidents_by_severity_count)


@strawberry.type
class IncidentMutations:
    pass
