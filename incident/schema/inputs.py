import datetime as dt
from typing import List

import strawberry
from strawberry.types.maybe import Maybe

# TRAP: annotate datetime-typed fields via the `dt` alias. An annotated
# assignment binds its value before evaluating its annotation, so any field
# named `datetime` shadows both the type and the module inside this class body.
from incident.enums import (
    CalendarIncidentChronologyIndicator,
    CalendarIncidentSeverity,
    SocialMediaLinkStatus,
)

# Register the TextChoices enums with Strawberry so they render as GraphQL
# enums (matching the `strawberry.auto` exposure on the scalars, which shares
# the same cached enum definition).
CalendarIncidentSeverityInput = strawberry.enum(CalendarIncidentSeverity)
CalendarIncidentChronologyIndicatorInput = strawberry.enum(
    CalendarIncidentChronologyIndicator
)
SocialMediaLinkStatusInput = strawberry.enum(SocialMediaLinkStatus)


@strawberry.input
class CalendarIncidentChronologyInput:
    indicator: CalendarIncidentChronologyIndicatorInput
    datetime: Maybe[dt.datetime | None] = strawberry.UNSET
    source_url: Maybe[str | None] = strawberry.UNSET
    content: Maybe[str | None] = strawberry.UNSET


@strawberry.input
class CalendarIncidentInput:
    title: str
    brief: str
    start_datetime: dt.datetime
    severity: CalendarIncidentSeverityInput
    end_datetime: Maybe[dt.datetime | None] = strawberry.UNSET
    long_term: Maybe[bool | None] = strawberry.UNSET
    inaccurate: Maybe[bool | None] = strawberry.UNSET
    impact_factor: Maybe[float | None] = strawberry.UNSET
    details: Maybe[str | None] = strawberry.UNSET
    line_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    vehicle_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    station_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    category_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    chronologies: Maybe[List[CalendarIncidentChronologyInput] | None] = strawberry.UNSET
    # Optimistic concurrency control: client echoes back the version it read;
    # a mismatch rejects the update instead of silently clobbering.
    version: Maybe[int | None] = strawberry.UNSET


@strawberry.input
class ExtractDataInput:
    url: str


@strawberry.input
class SocialMediaLinkInput:
    url: str
    title: Maybe[str | None] = strawberry.UNSET
    description: Maybe[str | None] = strawberry.UNSET
    # Optional GenericFK target — omit for "just dumping" links.
    incident_id: Maybe[strawberry.ID | None] = strawberry.UNSET
    category_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    line_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    vehicle_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    station_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    # Tri-state: omit to leave unchanged on update; set explicitly to change.
    status: Maybe[SocialMediaLinkStatusInput | None] = strawberry.UNSET
