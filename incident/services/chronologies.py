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
        source_url=write.source_url or "",
        content=write.content or "",
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
        chronology.source_url = write.source_url or ""
        chronology.content = write.content or ""
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


async def request_chronology_deletion(
    actor: User,
    *,
    is_admin: bool,
    chronology_id: int,
) -> CalendarIncidentChronology:
    """Mark a LIVE chronology for deletion (author-or-admin; sets PENDING_DELETION).

    Only valid on LIVE chronologies — DRAFT/PENDING_APPROVAL chronologies go
    through the relaxed direct-delete path in ``delete_chronology``. Requesting
    on an already-pending-deletion chronology raises an error.
    """

    chronology, incident = await _chronology_with_parent(chronology_id)

    if not may_edit(actor, is_admin=is_admin, incident=incident):
        raise IncidentNotEditableError(
            "Only the author or an admin may request deletion of this chronology."
        )

    if chronology.status == CalendarIncidentStatus.PENDING_DELETION:
        raise IncidentNotEditableError("This chronology is already pending deletion.")

    if chronology.status != CalendarIncidentStatus.LIVE:
        raise IncidentNotEditableError(
            "Only LIVE chronologies can be marked for deletion; "
            "draft or pending chronologies can be deleted directly."
        )

    def _sync() -> None:
        chronology.status = CalendarIncidentStatus.PENDING_DELETION
        chronology.clean()
        chronology.save()

    await sync_to_async(_sync)()
    return chronology


async def approve_chronology_deletion(admin: User, *, chronology_id: int) -> None:
    """Admin-only: soft-delete a chronology marked for deletion."""

    chronology, _ = await _chronology_with_parent(chronology_id)
    await sync_to_async(chronology.delete)()


async def reject_chronology_deletion(
    admin: User, *, chronology_id: int
) -> CalendarIncidentChronology:
    """Admin-only: revert a PENDING_DELETION chronology back to LIVE.

    The request flow only applies to LIVE chronologies, so the prior status
    is always LIVE — we unconditionally revert to LIVE here.
    """

    chronology, _ = await _chronology_with_parent(chronology_id)

    def _sync() -> None:
        chronology.status = CalendarIncidentStatus.LIVE
        chronology.clean()
        chronology.save()

    await sync_to_async(_sync)()
    return chronology


async def delete_chronology(actor: User, *, is_admin: bool, chronology_id: int) -> None:
    chronology, incident = await _chronology_with_parent(chronology_id)

    if not is_admin:
        if not is_author(actor, incident):
            raise IncidentNotEditableError(
                "Authors may only delete their own chronologies; admins may delete any."
            )
        chronology_or_parent_pending = chronology.status in (
            CalendarIncidentStatus.DRAFT,
            CalendarIncidentStatus.PENDING_APPROVAL,
        ) or incident.status in (
            CalendarIncidentStatus.DRAFT,
            CalendarIncidentStatus.PENDING_APPROVAL,
        )
        if not chronology_or_parent_pending:
            raise IncidentNotEditableError(
                "Authors may only delete draft or pending chronologies, "
                "or any chronology on a draft or pending incident."
            )

    await sync_to_async(chronology.delete)()
