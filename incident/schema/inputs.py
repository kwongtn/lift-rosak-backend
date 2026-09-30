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
    PassengerStatus,
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
PassengerStatusInput = strawberry.enum(PassengerStatus)


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
    # When the linked event HAPPENED, as opposed to ``created`` ("when someone
    # reported it"). Tri-state, and the third state is meaningful:
    #   omitted  -> update: leave unchanged.  submit: now().
    #   a value  -> set it (this is what every feed ordering is built on).
    #   explicit null -> update: reset to the submission time, i.e. "this
    #               happened when it was reported" — the documented escape
    #               hatch, since the column is NOT NULL and cannot hold null.
    # TRAP: this input is REPLACE-NOT-PATCH. The service assigns ``title`` and
    # calls ``.set()`` on four M2Ms unconditionally, so any caller re-sending a
    # payload that drops ``occurredAt`` also silently resets the event time to
    # "submitted" (on update: unchanged; on a re-create: now()). Every console
    # status change — Approve, Hide, Mark completed — must round-trip this
    # field, exactly like the fields above.
    occurred_at: Maybe[dt.datetime | None] = strawberry.UNSET


@strawberry.input
class FeedLinkInput:
    url: str
    title: Maybe[str | None] = strawberry.UNSET
    line_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    station_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    # Optional line-status report; requires at least one line_id (service rule).
    status: Maybe[PassengerStatusInput | None] = strawberry.UNSET
    delay_minutes: Maybe[int | None] = strawberry.UNSET
    notes: Maybe[str | None] = strawberry.UNSET
    # When the linked event HAPPENED, as opposed to ``created`` ("when someone
    # reported it"). Two states, because this path only ever INSERTS and the
    # column is NOT NULL:
    #   omitted / explicit null -> now(); the model default fires in the INSERT.
    #   a value                 -> stored verbatim, and it is what every feed
    #                             ordering (and thread-root selection) reads.
    # Unlike SocialMediaLinkInput there is no "reset to submitted" state to
    # express: the feed has no update path, so a second submission of the same
    # canonical URL is a duplicate, not an edit — the pre-existing row is
    # returned untouched (see ``services.feed_links.submit_feed_link``).
    occurred_at: Maybe[dt.datetime | None] = strawberry.UNSET


@strawberry.input
class LineStatusReportInput:
    line_id: strawberry.ID
    status: PassengerStatusInput
    station_ids: Maybe[List[strawberry.ID] | None] = strawberry.UNSET
    delay_minutes: Maybe[int | None] = strawberry.UNSET
    notes: Maybe[str | None] = strawberry.UNSET
