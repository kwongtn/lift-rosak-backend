from typing import List

import strawberry
import strawberry_django

from incident.schema.filters import (
    CalendarIncidentFilter,
    StationIncidentFilter,
    VehicleIncidentFilter,
)
from incident.schema.mutations.chronologies import ChronologyMutations
from incident.schema.mutations.incidents import IncidentCrudMutations
from incident.schema.mutations.interactions import (
    ExtractionMutations,
    SocialMediaLinkMutations,
    VoteMutations,
)
from incident.schema.orderings import CalendarIncidentOrder
from incident.schema.resolvers import (
    get_calendar_incident_categories,
    get_calendar_incident_history,
    get_calendar_incidents_by_severity_count,
    get_pending_calendar_incidents,
    get_public_social_media_links,
    get_social_media_links,
)
from incident.schema.scalars import (
    CalendarIncidentCategoryScalar,
    CalendarIncidentGroupByDateSeverityScalar,
    CalendarIncidentHistoryEntryScalar,
    CalendarIncidentScalar,
    SocialMediaLinkConnection,
    SocialMediaLinkScalar,
    StationIncident,
    VehicleIncident,
)
from rosak.permissions import IsAdmin, IsLoggedIn


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

    pending_calendar_incidents: List[CalendarIncidentScalar] = strawberry_django.field(
        resolver=get_pending_calendar_incidents,
        permission_classes=[IsAdmin],
    )

    social_media_links: List[SocialMediaLinkScalar] = strawberry_django.field(
        resolver=get_social_media_links,
        permission_classes=[IsAdmin],
    )

    public_social_media_links: SocialMediaLinkConnection = strawberry.field(
        resolver=get_public_social_media_links,
    )

    calendar_incident_categories: List[CalendarIncidentCategoryScalar] = (
        strawberry_django.field(resolver=get_calendar_incident_categories)
    )

    calendar_incident_history: List[CalendarIncidentHistoryEntryScalar] = (
        strawberry.field(
            resolver=get_calendar_incident_history,
            permission_classes=[IsLoggedIn],
        )
    )


@strawberry.type
class IncidentMutations(
    IncidentCrudMutations,
    ChronologyMutations,
    VoteMutations,
    SocialMediaLinkMutations,
    ExtractionMutations,
):
    pass
