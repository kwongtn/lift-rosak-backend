"""Chronology CRUD and reorder business logic."""

import datetime as dt
from dataclasses import dataclass

from asgiref.sync import sync_to_async

from common.models import User
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident, CalendarIncidentChronology

from .access import get_incident, is_author, may_edit
from .errors import IncidentNotEditableError, IncidentServiceError


@dataclass(frozen=True, slots=True)
class ChronologyUpdate:
    """Field payload for update_chronology; status changes go through approval."""

    indicator: str
    datetime: dt.datetime | None = None
    source_url: str = ""
    content: str = ""


async def _chronology_with_parent(
    chronology_id: int,
) -> tuple[CalendarIncidentChronology, CalendarIncident]:
    chronology = await CalendarIncidentChronology.objects.aget(pk=chronology_id)
    incident = await get_incident(chronology.calendar_incident_id)
    return chronology, incident


async def create_chronology(
    actor: User,
    *,
    is_admin: bool,
    calendar_incident_id: int,
    write: ChronologyUpdate,
) -> CalendarIncidentChronology:
    incident = await get_incident(calendar_incident_id)

    if not may_edit(actor, is_admin=is_admin, incident=incident):
        raise IncidentNotEditableError(
            "Only the author or an admin may add chronologies to this incident."
        )

    chronology = CalendarIncidentChronology(
        calendar_incident=incident,
        indicator=write.indicator,
        datetime=write.datetime,
        source_url=write.source_url,
        content=write.content,
        status=incident.status,
    )
    chronology.clean()
    await sync_to_async(chronology.save)()
    return chronology


async def update_chronology(
    actor: User,
    *,
    is_admin: bool,
    chronology_id: int,
    write: ChronologyUpdate,
) -> CalendarIncidentChronology:
    chronology, incident = await _chronology_with_parent(chronology_id)

    if not may_edit(actor, is_admin=is_admin, incident=incident):
        raise IncidentNotEditableError(
            "Only the author or an admin may edit this chronology."
        )

    def _sync() -> None:
        chronology.indicator = write.indicator
        chronology.datetime = write.datetime
        chronology.source_url = write.source_url
        chronology.content = write.content
        chronology.calendar_incident = incident
        chronology.clean()
        chronology.save()

    await sync_to_async(_sync)()
    return chronology


async def approve_chronology(
    admin: User, *, chronology_id: int
) -> CalendarIncidentChronology:
    chronology = await CalendarIncidentChronology.objects.aget(pk=chronology_id)
    incident = await get_incident(chronology.calendar_incident_id)

    if incident.status != CalendarIncidentStatus.LIVE:
        raise IncidentNotEditableError(
            "Chronology cannot be approved while its parent incident is not LIVE."
        )

    def _sync() -> None:
        chronology.status = CalendarIncidentStatus.LIVE
        chronology.clean()
        chronology.save()

    await sync_to_async(_sync)()
    return chronology


async def reorder_chronology(
    actor: User,
    *,
    is_admin: bool,
    chronology_id: int,
    target_order: int,
) -> CalendarIncidentChronology:
    chronology, incident = await _chronology_with_parent(chronology_id)

    if not may_edit(actor, is_admin=is_admin, incident=incident):
        raise IncidentNotEditableError(
            "Only the author or an admin may reorder this chronology."
        )

    sibling_count = await CalendarIncidentChronology.objects.filter(
        calendar_incident_id=chronology.calendar_incident_id
    ).acount()
    if not 0 <= target_order < sibling_count:
        raise IncidentServiceError(
            f"target_order must be between 0 and {sibling_count - 1}."
        )

    await sync_to_async(chronology.to)(target_order)
    await sync_to_async(chronology.refresh_from_db)()
    return chronology


async def delete_chronology(actor: User, *, is_admin: bool, chronology_id: int) -> None:
    chronology, incident = await _chronology_with_parent(chronology_id)

    if not is_admin and (
        chronology.status != CalendarIncidentStatus.DRAFT
        or not is_author(actor, incident)
    ):
        raise IncidentNotEditableError(
            "Authors may only delete their own draft chronologies; "
            "admins may delete any."
        )

    await sync_to_async(chronology.delete)()
