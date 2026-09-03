"""CalendarIncident create/update/approve/reject/delete business logic."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from asgiref.sync import sync_to_async
from django.db import transaction
from safedelete.models import HARD_DELETE

from common.models import User
from incident.enums import CalendarIncidentStatus
from incident.models import (
    CalendarIncident,
    CalendarIncidentChronology,
    CalendarIncidentMedia,
)

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
    """Swap the incident's chronologies for `writes`; new rows inherit status.

    Pending-moderation states (PENDING_DELETION, PENDING_APPROVAL) on old rows
    survive the replace when the new write matches the same chronology by the
    stable identity tuple (indicator, datetime, source_url, content) — so an
    admin saving a LIVE incident does not silently cancel a pending chronology
    deletion request. Only approve/rejectChronologyDeletion mutations may
    resolve a PENDING_DELETION state.

    Caveat: if a user edits BOTH a chronology's content and expects the
    deletion-preservation for that same row, the flag is lost — the content
    change means no old row matches, so inherit_status applies. Acceptable:
    they materially changed the row.
    """

    _PRESERVE = frozenset(
        {
            CalendarIncidentStatus.PENDING_DELETION,
            CalendarIncidentStatus.PENDING_APPROVAL,
        }
    )

    def _sync() -> None:
        with transaction.atomic():
            # Snapshot old pending statuses keyed by stable identity.
            snapshot: dict[
                tuple[str, dt.datetime | None, str, str],
                CalendarIncidentStatus,
            ] = {}
            for existing in incident.chronologies.all():
                if existing.status in _PRESERVE:
                    snapshot[
                        (
                            existing.indicator,
                            existing.datetime,
                            existing.source_url or "",
                            existing.content or "",
                        )
                    ] = existing.status
                existing.delete()

            for write in writes:
                key = (
                    write.indicator,
                    write.datetime,
                    write.source_url or "",
                    write.content or "",
                )
                status = snapshot.pop(key, inherit_status)
                chronology = CalendarIncidentChronology(
                    calendar_incident=incident,
                    indicator=write.indicator,
                    datetime=write.datetime,
                    source_url=write.source_url or "",
                    content=write.content or "",
                    status=status,
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
        title=data.title or "",
        brief=data.brief or "",
        details=data.details or "",
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
        if incident.status != CalendarIncidentStatus.LIVE:
            raise IncidentNotEditableError(
                "Only the author or an admin may edit this incident."
            )

    if incident.status == CalendarIncidentStatus.DRAFT:
        updated = await _apply_field_update(incident, data, chronologies)
        return UpdateResult(incident=updated, created_revision=False)

    if is_admin:
        updated = await _apply_field_update(incident, data, chronologies)
        return UpdateResult(incident=updated, created_revision=False)

    # Spec C1: author editing their own PENDING_APPROVAL incident contributes
    # back to the same object — no revision spawned (only the creator can edit
    # a pending row, and all edits fold back into it).
    if (
        is_author(editor, incident)
        and incident.status == CalendarIncidentStatus.PENDING_APPROVAL
    ):
        updated = await _apply_field_update(incident, data, chronologies)
        return UpdateResult(incident=updated, created_revision=False)

    open_draft = await CalendarIncident.objects.filter(
        parent_incident=incident,
        status=CalendarIncidentStatus.DRAFT,
    ).afirst()
    if open_draft is not None:
        if open_draft.created_by_id == editor.id:
            # Same actor resumes their own open draft (e.g. retry after a
            # failed submit). Apply in place to the existing DRAFT — frontend
            # gets its id back to (re)chain submitCalendarIncident.
            updated = await _apply_field_update(open_draft, data, chronologies)
            return UpdateResult(incident=updated, created_revision=True)
        raise IncidentNotEditableError(
            "An unapproved edit draft already exists for this incident. "
            "Please allow the draft to approve before proceeding."
        )

    revision = await _create_revision(editor, incident, data, chronologies)
    return UpdateResult(incident=revision, created_revision=True)


async def _apply_field_update(
    incident: CalendarIncident,
    data: IncidentWrite,
    chronologies: tuple[ChronologyWrite, ...],
) -> CalendarIncident:
    def _sync() -> None:
        with transaction.atomic():
            incident.title = data.title or ""
            incident.brief = data.brief or ""
            incident.details = data.details or ""
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
    editor: User,
    live_incident: CalendarIncident,
    data: IncidentWrite,
    chronologies: tuple[ChronologyWrite, ...],
) -> CalendarIncident:
    revision = await sync_to_async(CalendarIncident.objects.create)(
        title=data.title or "",
        brief=data.brief or "",
        details=data.details or "",
        start_datetime=data.start_datetime,
        end_datetime=data.end_datetime,
        long_term=data.long_term,
        inaccurate=data.inaccurate,
        severity=data.severity,
        impact_factor=data.impact_factor,
        status=CalendarIncidentStatus.DRAFT,
        parent_incident_id=live_incident.pk,
        created_by=editor,
    )
    await _apply_m2m(revision, data)
    await replace_chronologies(
        revision, chronologies, inherit_status=CalendarIncidentStatus.DRAFT
    )
    return revision


async def submit_incident(
    actor: User, *, is_admin: bool, incident_id: int
) -> CalendarIncident:
    """Move an author's DRAFT into PENDING_APPROVAL for admin review."""

    incident = await get_incident(incident_id)

    if incident.status != CalendarIncidentStatus.DRAFT:
        raise IncidentNotEditableError(
            "Only DRAFT incidents can be submitted for approval."
        )

    if not may_edit(actor, is_admin=is_admin, incident=incident):
        raise IncidentNotEditableError(
            "Only the author or an admin may submit this incident."
        )

    def _sync() -> None:
        incident.status = CalendarIncidentStatus.PENDING_APPROVAL
        incident.save()

    await sync_to_async(_sync)()
    return incident


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

            parent.title = revision.title or ""
            parent.brief = revision.brief or ""
            parent.details = revision.details or ""
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

            existing_media_ids = set(parent.medias.values_list("id", flat=True))
            for media in revision.medias.all():
                if media.id not in existing_media_ids:
                    CalendarIncidentMedia.objects.create(
                        calendar_incident=parent,
                        media=media,
                    )
                    existing_media_ids.add(media.id)

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

    if not is_admin:
        if not is_author(actor, incident) or incident.status not in (
            CalendarIncidentStatus.DRAFT,
            CalendarIncidentStatus.PENDING_APPROVAL,
        ):
            raise IncidentNotEditableError(
                "Authors may only delete their own drafts or pending submissions; "
                "admins may delete any."
            )

    # Resolve pending children before soft-deleting the parent. safedelete's
    # SOFT_DELETE does NOT cascade (by design — that's why this step exists):
    # orphaned draft revisions and pending chronologies would otherwise
    # survive the parent. HARD_DELETE paths keep DB-level CASCADE.
    await _resolve_pending_children(incident)
    await sync_to_async(incident.delete)()


async def _resolve_pending_children(incident: CalendarIncident) -> None:
    """Soft-delete open draft revisions and pending chronologies of `incident`.

    Called before the parent is soft-deleted so no orphaned pending children
    survive (spec D6). Covers the explicit gap: a chronology marked
    PENDING_DELETION on a LIVE incident, then the admin deletes the parent —
    the chronology's pending state dies with the parent.
    """

    def _sync() -> None:
        # Open draft revisions (parent_incident=incident, status=DRAFT).
        for revision in CalendarIncident.objects.filter(
            parent_incident=incident,
            status=CalendarIncidentStatus.DRAFT,
        ):
            revision.delete()

        # Chronologies with a pending state (PENDING_APPROVAL or PENDING_DELETION).
        for chronology in CalendarIncidentChronology.objects.filter(
            calendar_incident=incident,
            status__in=(
                CalendarIncidentStatus.PENDING_APPROVAL,
                CalendarIncidentStatus.PENDING_DELETION,
            ),
        ):
            chronology.delete()

    await sync_to_async(_sync)()
