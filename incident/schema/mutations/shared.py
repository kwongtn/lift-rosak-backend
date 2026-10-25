"""Shared helpers for the incident mutation modules."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import strawberry
from django.conf import settings
from django.utils import timezone
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


def naive_kl(value: dt.datetime) -> dt.datetime:
    """`value` as naive Asia/Kuala_Lumpur wall time, the frame the DB reads back.

    ``USE_TZ = False`` returns naive KL values, while the GraphQL ``DateTime``
    scalar parses a ``...Z`` or offset string to an aware value. The web console
    sent ``...Z`` until rosak_firebase f853bb67 and a58e18af; stale bundles and
    other API clients still can. The stored instant is the same either way;
    converting once here keeps in-memory comparisons (the chronology identity key
    in ``replace_chronologies``) in a single frame.
    """
    if timezone.is_aware(value):
        return timezone.make_naive(value, ZoneInfo(settings.TIME_ZONE))
    return value


def write_from_input(data: CalendarIncidentInput) -> services.IncidentWrite:
    end = maybe_value(data.end_datetime)
    return services.IncidentWrite(
        title=data.title,
        brief=data.brief,
        start_datetime=naive_kl(data.start_datetime),
        severity=data.severity,
        end_datetime=None if end is None else naive_kl(end),
        long_term=maybe_value(data.long_term, False),
        inaccurate=maybe_value(data.inaccurate, False),
        impact_factor=Decimal(str(maybe_value(data.impact_factor, 0))),
        details=maybe_value(data.details, "") or "",
        line_ids=tuple(maybe_value(data.line_ids) or ()),
        vehicle_ids=tuple(maybe_value(data.vehicle_ids) or ()),
        station_ids=tuple(maybe_value(data.station_ids) or ()),
        category_ids=tuple(maybe_value(data.category_ids) or ()),
    )


def chronology_write_from_input(
    chronology: CalendarIncidentChronologyInput,
) -> services.ChronologyWrite:
    when = maybe_value(chronology.datetime)
    return services.ChronologyWrite(
        indicator=chronology.indicator,
        datetime=None if when is None else naive_kl(when),
        source_url=maybe_value(chronology.source_url, "") or "",
        content=maybe_value(chronology.content, "") or "",
    )


def chronology_writes(
    data: CalendarIncidentInput,
) -> tuple[services.ChronologyWrite, ...]:
    return tuple(
        chronology_write_from_input(chronology)
        for chronology in maybe_value(data.chronologies) or ()
    )
