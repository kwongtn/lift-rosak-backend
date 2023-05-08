from typing import List

from strawberry_django_plus import gql

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


@gql.type
class IncidentScalars:
    vehicle_incidents: List[VehicleIncident] = gql.django.field(
        filters=VehicleIncidentFilter
    )
    station_incidents: List[StationIncident] = gql.django.field(
        filters=StationIncidentFilter
    )

    calendar_incidents: List[CalendarIncidentScalar] = gql.django.field(
        filters=CalendarIncidentFilter,
        order=CalendarIncidentOrder,
    )

    calendar_incidents_by_severity_count: List[
        CalendarIncidentGroupByDateSeverityScalar
    ] = gql.field(resolver=get_calendar_incidents_by_severity_count)


@gql.type
class IncidentMutations:
    pass
