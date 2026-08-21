import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.models import User
from incident import services
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident, CalendarIncidentChronology


def _write(**overrides) -> services.IncidentWrite:
    defaults = dict(
        title="Test Incident",
        brief="Test brief",
        start_datetime=timezone.now(),
        severity="MINOR",
    )
    defaults.update(overrides)
    return services.IncidentWrite(**defaults)


def _chronology_write(**overrides) -> services.ChronologyWrite:
    defaults = dict(indicator="GREEN", content="train stalled at KL Sentral")
    defaults.update(overrides)
    return services.ChronologyWrite(**defaults)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=f"test-user-chronology-{n}"
    )


async def _make_incident(
    author: User, *, is_admin: bool, status: CalendarIncidentStatus
) -> CalendarIncident:
    incident = await services.create_incident(author, is_admin=is_admin, data=_write())
    if incident.status != status:
        await sync_to_async(setattr)(incident, "status", status)
        await sync_to_async(incident.save)()
    return incident


@pytest.mark.django_db
async def test_chronology_inherits_parent_status_on_creation():
    author = await _make_user(1)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    draft = await _make_incident(
        author, is_admin=False, status=CalendarIncidentStatus.DRAFT
    )

    under_live = await services.create_chronology(
        author,
        is_admin=False,
        calendar_incident_id=live.id,
        write=_chronology_write(),
    )
    under_draft = await services.create_chronology(
        author,
        is_admin=False,
        calendar_incident_id=draft.id,
        write=_chronology_write(),
    )

    assert under_live.status == CalendarIncidentStatus.LIVE
    assert under_draft.status == CalendarIncidentStatus.DRAFT


@pytest.mark.django_db
async def test_chronology_cannot_be_approved_if_parent_not_live():
    author = await _make_user(2)
    pending = await _make_incident(
        author, is_admin=False, status=CalendarIncidentStatus.PENDING_APPROVAL
    )
    chronology = await services.create_chronology(
        author,
        is_admin=False,
        calendar_incident_id=pending.id,
        write=_chronology_write(),
    )

    with pytest.raises(services.IncidentNotEditableError):
        await services.approve_chronology(author, chronology_id=chronology.id)

    await sync_to_async(chronology.refresh_from_db)()
    assert chronology.status == CalendarIncidentStatus.PENDING_APPROVAL


@pytest.mark.django_db
async def test_chronology_reorder():
    author = await _make_user(3)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )

    await services.create_chronology(
        author,
        is_admin=True,
        calendar_incident_id=live.id,
        write=_chronology_write(content="first"),
    )
    second = await services.create_chronology(
        author,
        is_admin=True,
        calendar_incident_id=live.id,
        write=_chronology_write(content="second"),
    )
    third = await services.create_chronology(
        author,
        is_admin=True,
        calendar_incident_id=live.id,
        write=_chronology_write(content="third"),
    )

    moved = await services.reorder_chronology(
        author, is_admin=False, chronology_id=third.id, target_order=0
    )

    orders = {
        c.content: c.order
        async for c in CalendarIncidentChronology.objects.filter(
            calendar_incident=live
        ).order_by("order")
    }
    assert moved.order == 0
    assert orders == {"third": 0, "first": 1, "second": 2}

    with pytest.raises(services.IncidentServiceError):
        await services.reorder_chronology(
            author, is_admin=False, chronology_id=second.id, target_order=99
        )


@pytest.mark.django_db
async def test_chronology_update_and_soft_delete():
    author = await _make_user(4)
    other = await _make_user(5)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        author, is_admin=False, calendar_incident_id=live.id, write=_chronology_write()
    )

    updated = await services.update_chronology(
        author,
        is_admin=False,
        chronology_id=chronology.id,
        write=_chronology_write(content="corrected", indicator="RED"),
    )
    assert updated.content == "corrected"
    assert updated.indicator == "RED"

    # LIVE chronologies are admin-only to delete, even for the incident author.
    with pytest.raises(services.IncidentNotEditableError):
        await services.delete_chronology(
            other, is_admin=False, chronology_id=chronology.id
        )

    # Draft chronologies are deletable by their incident's author.
    draft = await _make_incident(
        other, is_admin=False, status=CalendarIncidentStatus.DRAFT
    )
    draft_chronology = await services.create_chronology(
        other,
        is_admin=False,
        calendar_incident_id=draft.id,
        write=_chronology_write(),
    )
    await services.delete_chronology(
        other, is_admin=False, chronology_id=draft_chronology.id
    )
    assert not await CalendarIncidentChronology.objects.filter(
        pk=draft_chronology.id
    ).aexists()
    assert await CalendarIncidentChronology.all_objects.filter(
        pk=draft_chronology.id
    ).aexists()
