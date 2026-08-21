"""Shared helpers for the incident mutation modules."""

from decimal import Decimal

import strawberry
from graphql.error import GraphQLError

from incident import services
from incident.schema.inputs import (
    CalendarIncidentChronologyInput,
    CalendarIncidentInput,
)


def maybe_value(maybe_field, default=None):
    """Unwrap a Strawberry Maybe field.

    Returns `default` when the field was omitted (UNSET) or is a plain
    None; otherwise returns the wrapped payload (`Some(value)` -> `value`,
    `Some(None)` -> `None`).
    """
    if maybe_field is None or maybe_field is strawberry.UNSET:
        return default
    return maybe_field.value


def raise_service_error(exc: services.IncidentServiceError) -> None:
    raise GraphQLError(str(exc)) from exc


def write_from_input(data: CalendarIncidentInput) -> services.IncidentWrite:
    return services.IncidentWrite(
        title=data.title,
        brief=data.brief,
        start_datetime=data.start_datetime,
        severity=data.severity,
        end_datetime=maybe_value(data.end_datetime),
        long_term=maybe_value(data.long_term, False),
        inaccurate=maybe_value(data.inaccurate, False),
        impact_factor=Decimal(str(maybe_value(data.impact_factor, 0))),
        details=maybe_value(data.details, ""),
        line_ids=tuple(maybe_value(data.line_ids) or ()),
        vehicle_ids=tuple(maybe_value(data.vehicle_ids) or ()),
        station_ids=tuple(maybe_value(data.station_ids) or ()),
        category_ids=tuple(maybe_value(data.category_ids) or ()),
    )


def chronology_write_from_input(
    chronology: CalendarIncidentChronologyInput,
) -> services.ChronologyWrite:
    return services.ChronologyWrite(
        indicator=chronology.indicator,
        datetime=maybe_value(chronology.datetime),
        source_url=maybe_value(chronology.source_url, ""),
        content=maybe_value(chronology.content, ""),
    )


def chronology_writes(
    data: CalendarIncidentInput,
) -> tuple[services.ChronologyWrite, ...]:
    return tuple(
        chronology_write_from_input(chronology)
        for chronology in maybe_value(data.chronologies) or ()
    )
