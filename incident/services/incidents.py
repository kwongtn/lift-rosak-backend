"""CalendarIncident create/update/approve/reject/delete business logic."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from asgiref.sync import sync_to_async
from django.db import transaction
from safedelete.models import HARD_DELETE

from common.models import User
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident, CalendarIncidentChronology

from .access import get_incident, is_author, may_edit
from .errors import ConcurrencyConflictError, IncidentNotEditableError


@dataclass(frozen=True, slots=True)
class ChronologyWrite:
    indicator: str
    datetime: dt.datetime | None = None
    source_url: str = ""
    content: str = ""


@dataclass(frozen=True, slots=True)
class IncidentWrite:
    title: str
    brief: str
    start_datetime: dt.datetime
    severity: str
    end_datetime: dt.datetime | None = None
    long_term: bool = False
    inaccurate: bool = False
    impact_factor: Decimal = Decimal("0")
    details: str = ""
    line_ids: tuple[int, ...] = ()
    vehicle_ids: tuple[int, ...] = ()
    station_ids: tuple[int, ...] = ()
    category_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdateResult:
    incident: CalendarIncident
    created_revision: bool


async def _apply_m2m(incident: CalendarIncident, data: IncidentWrite) -> None:
    def _sync() -> None:
        incident.lines.set(data.line_ids)
        incident.vehicles.set(data.vehicle_ids)
        incident.stations.set(data.station_ids)
        incident.categories.set(data.category_ids)

    await sync_to_async(_sync)()


async def replace_chronologies(
    incident: CalendarIncident,
    writes: tuple[ChronologyWrite, ...],
    inherit_status: CalendarIncidentStatus,
) -> None:
    """Swap the incident's chronologies for `writes`; new rows inherit status."""

    def _sync() -> None:
        with transaction.atomic():
            for existing in incident.chronologies.all():
                existing.delete()
            for write in writes:
                chronology = CalendarIncidentChronology(
                    calendar_incident=incident,
                    indicator=write.indicator,
                    datetime=write.datetime,
                    source_url=write.source_url,
                    content=write.content,
                    status=inherit_status,
                )
                chronology.clean()
                chronology.save()

    await sync_to_async(_sync)()


async def create_incident(
    author: User,
    *,
    is_admin: bool,
    data: IncidentWrite,
    chronologies: tuple[ChronologyWrite, ...] = (),
) -> CalendarIncident:
    status = CalendarIncidentStatus.LIVE if is_admin else CalendarIncidentStatus.DRAFT
    incident = await sync_to_async(CalendarIncident.objects.create)(
        title=data.title,
        brief=data.brief,
        details=data.details,
        start_datetime=data.start_datetime,
        end_datetime=data.end_datetime,
        long_term=data.long_term,
        inaccurate=data.inaccurate,
        severity=data.severity,
        impact_factor=data.impact_factor,
        status=status,
        created_by=author,
    )
    await _apply_m2m(incident, data)
    await replace_chronologies(incident, chronologies, inherit_status=status)
    return incident


async def update_incident(
    editor: User,
    *,
    is_admin: bool,
    incident_id: int,
    expected_version: int | None,
    data: IncidentWrite,
    chronologies: tuple[ChronologyWrite, ...] = (),
) -> UpdateResult:
    incident = await get_incident(incident_id)

    if expected_version is not None and expected_version != incident.version:
        raise ConcurrencyConflictError(
            f"Version mismatch: client has v{expected_version}, "
            f"server is at v{incident.version}; reload and retry."
        )

    if not may_edit(editor, is_admin=is_admin, incident=incident):
        raise IncidentNotEditableError(
            "Only the author or an admin may edit this incident."
        )

    if incident.status == CalendarIncidentStatus.DRAFT:
        updated = await _apply_field_update(incident, data, chronologies)
        return UpdateResult(incident=updated, created_revision=False)

    revision = await _create_revision(incident, data, chronologies)
    return UpdateResult(incident=revision, created_revision=True)


async def _apply_field_update(
    incident: CalendarIncident,
    data: IncidentWrite,
    chronologies: tuple[ChronologyWrite, ...],
) -> CalendarIncident:
    def _sync() -> None:
        with transaction.atomic():
            incident.title = data.title
            incident.brief = data.brief
            incident.details = data.details
            incident.start_datetime = data.start_datetime
            incident.end_datetime = data.end_datetime
            incident.long_term = data.long_term
            incident.inaccurate = data.inaccurate
            incident.severity = data.severity
            incident.impact_factor = data.impact_factor
            incident.version += 1
            incident.save()

    await sync_to_async(_sync)()
    await _apply_m2m(incident, data)
    await replace_chronologies(incident, chronologies, inherit_status=incident.status)
    return incident


async def _create_revision(
    live_incident: CalendarIncident,
    data: IncidentWrite,
    chronologies: tuple[ChronologyWrite, ...],
) -> CalendarIncident:
    revision = await sync_to_async(CalendarIncident.objects.create)(
        title=data.title,
        brief=data.brief,
        details=data.details,
        start_datetime=data.start_datetime,
        end_datetime=data.end_datetime,
        long_term=data.long_term,
        inaccurate=data.inaccurate,
        severity=data.severity,
        impact_factor=data.impact_factor,
        status=CalendarIncidentStatus.DRAFT,
        parent_incident_id=live_incident.pk,
        created_by_id=live_incident.created_by_id,
    )
    await _apply_m2m(revision, data)
    await replace_chronologies(
        revision, chronologies, inherit_status=CalendarIncidentStatus.DRAFT
    )
    return revision


async def approve_incident(admin: User, *, incident_id: int) -> CalendarIncident:
    target = await get_incident(incident_id)

    if target.parent_incident_id is not None:
        return await _merge_revision_into_parent(target)

    if target.status != CalendarIncidentStatus.PENDING_APPROVAL:
        raise IncidentNotEditableError(
            "Only PENDING_APPROVAL incidents can be approved."
        )

    def _promote() -> None:
        target.status = CalendarIncidentStatus.LIVE
        target.rejection_reason = ""
        target.save()

    await sync_to_async(_promote)()
    return target


async def _merge_revision_into_parent(
    revision: CalendarIncident,
) -> CalendarIncident:
    """Copy revision fields onto the parent atomically, then hard-delete it."""

    def _sync() -> int:
        with transaction.atomic():
            parent = CalendarIncident.objects.select_for_update().get(
                pk=revision.parent_incident_id
            )

            parent.title = revision.title
            parent.brief = revision.brief
            parent.details = revision.details
            parent.start_datetime = revision.start_datetime
            parent.end_datetime = revision.end_datetime
            parent.long_term = revision.long_term
            parent.inaccurate = revision.inaccurate
            parent.severity = revision.severity
            parent.impact_factor = revision.impact_factor
            parent.status = CalendarIncidentStatus.LIVE
            parent.rejection_reason = ""
            parent.version += 1
            parent.save()

            parent.lines.set(revision.lines.all())
            parent.vehicles.set(revision.vehicles.all())
            parent.stations.set(revision.stations.all())
            parent.categories.set(revision.categories.all())

            for existing in parent.chronologies.all():
                existing.delete()
            for order, chronology in enumerate(revision.chronologies.order_by("order")):
                chronology.calendar_incident = parent
                chronology.order = order
                chronology.save()

            revision.delete(force_policy=HARD_DELETE)
            return parent.pk

    parent_pk = await sync_to_async(_sync)()
    return await CalendarIncident.objects.aget(pk=parent_pk)


async def reject_incident(
    admin: User, *, incident_id: int, reason: str
) -> CalendarIncident:
    incident = await get_incident(incident_id)

    if incident.status not in (
        CalendarIncidentStatus.DRAFT,
        CalendarIncidentStatus.PENDING_APPROVAL,
    ):
        raise IncidentNotEditableError(
            "Only DRAFT or PENDING_APPROVAL incidents can be rejected."
        )

    def _sync() -> None:
        incident.status = CalendarIncidentStatus.REJECTED
        incident.rejection_reason = reason
        incident.save()

    await sync_to_async(_sync)()
    return incident


async def delete_incident(actor: User, *, is_admin: bool, incident_id: int) -> None:
    incident = await get_incident(incident_id)

    if not is_admin and (
        incident.status != CalendarIncidentStatus.DRAFT
        or not is_author(actor, incident)
    ):
        raise IncidentNotEditableError(
            "Authors may only delete their own drafts; admins may delete any."
        )

    await sync_to_async(incident.delete)()
