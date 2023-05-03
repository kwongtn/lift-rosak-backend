from typing import List

from strawberry_django_plus import gql

from incident.schema.filters import (
    CalendarIncidentFilter,
    StationIncidentFilter,
    VehicleIncidentFilter,
)
from incident.schema.scalars import (
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
        filters=CalendarIncidentFilter
    )


@gql.type
class IncidentMutations:
    pass
