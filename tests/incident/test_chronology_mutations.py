import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.models import User
from incident import services
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident, CalendarIncidentChronology

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 6 — Chronology mark-for-delete flow
# ---------------------------------------------------------------------------


@pytest.mark.django_db
async def test_request_chronology_deletion_by_author_sets_pending_deletion():
    author = await _make_user(10)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        author, is_admin=False, calendar_incident_id=live.id, write=_chronology_write()
    )

    updated = await services.request_chronology_deletion(
        author, is_admin=False, chronology_id=chronology.id
    )
    assert updated.status == CalendarIncidentStatus.PENDING_DELETION


@pytest.mark.django_db
async def test_request_chronology_deletion_by_non_author_rejected():
    author = await _make_user(11)
    stranger = await _make_user(12)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        author, is_admin=False, calendar_incident_id=live.id, write=_chronology_write()
    )

    with pytest.raises(services.IncidentNotEditableError):
        await services.request_chronology_deletion(
            stranger, is_admin=False, chronology_id=chronology.id
        )


@pytest.mark.django_db
async def test_request_chronology_deletion_on_non_live_chronology_rejected():
    author = await _make_user(13)
    draft = await _make_incident(
        author, is_admin=False, status=CalendarIncidentStatus.DRAFT
    )
    chronology = await services.create_chronology(
        author, is_admin=False, calendar_incident_id=draft.id, write=_chronology_write()
    )

    with pytest.raises(services.IncidentNotEditableError):
        await services.request_chronology_deletion(
            author, is_admin=False, chronology_id=chronology.id
        )


@pytest.mark.django_db
async def test_request_chronology_deletion_already_pending_is_error():
    admin = await _make_user(14)
    live = await _make_incident(
        admin, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        admin, is_admin=True, calendar_incident_id=live.id, write=_chronology_write()
    )

    await services.request_chronology_deletion(
        admin, is_admin=True, chronology_id=chronology.id
    )
    with pytest.raises(services.IncidentNotEditableError):
        await services.request_chronology_deletion(
            admin, is_admin=True, chronology_id=chronology.id
        )


@pytest.mark.django_db
async def test_approve_chronology_deletion_soft_deletes():
    admin = await _make_user(15)
    live = await _make_incident(
        admin, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        admin, is_admin=True, calendar_incident_id=live.id, write=_chronology_write()
    )

    await services.request_chronology_deletion(
        admin, is_admin=True, chronology_id=chronology.id
    )
    await services.approve_chronology_deletion(admin, chronology_id=chronology.id)

    assert not await CalendarIncidentChronology.objects.filter(
        pk=chronology.id
    ).aexists()
    assert await CalendarIncidentChronology.all_objects.filter(
        pk=chronology.id
    ).aexists()


@pytest.mark.django_db
async def test_reject_chronology_deletion_reverts_to_live():
    admin = await _make_user(16)
    live = await _make_incident(
        admin, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        admin, is_admin=True, calendar_incident_id=live.id, write=_chronology_write()
    )

    await services.request_chronology_deletion(
        admin, is_admin=True, chronology_id=chronology.id
    )
    reverted = await services.reject_chronology_deletion(
        admin, chronology_id=chronology.id
    )
    assert reverted.status == CalendarIncidentStatus.LIVE


# ---------------------------------------------------------------------------
# Task 6 — Relaxed delete_chronology matrix (spec E2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
async def test_delete_chronology_author_draft_on_live_parent():
    author = await _make_user(20)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    # Create a chronology on a LIVE parent — it inherits LIVE status.
    chronology = await services.create_chronology(
        author, is_admin=False, calendar_incident_id=live.id, write=_chronology_write()
    )
    # Move the chronology to DRAFT directly (simulating a draft chronology).
    await sync_to_async(setattr)(chronology, "status", CalendarIncidentStatus.DRAFT)
    await sync_to_async(chronology.save)()

    await services.delete_chronology(
        author, is_admin=False, chronology_id=chronology.id
    )
    assert not await CalendarIncidentChronology.objects.filter(
        pk=chronology.id
    ).aexists()


@pytest.mark.django_db
async def test_delete_chronology_author_pending_approval_on_live_parent():
    author = await _make_user(21)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        author, is_admin=False, calendar_incident_id=live.id, write=_chronology_write()
    )
    await sync_to_async(setattr)(
        chronology, "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(chronology.save)()

    await services.delete_chronology(
        author, is_admin=False, chronology_id=chronology.id
    )
    assert not await CalendarIncidentChronology.objects.filter(
        pk=chronology.id
    ).aexists()


@pytest.mark.django_db
async def test_delete_chronology_author_on_pending_parent():
    author = await _make_user(22)
    pending = await _make_incident(
        author, is_admin=False, status=CalendarIncidentStatus.PENDING_APPROVAL
    )
    chronology = await services.create_chronology(
        author,
        is_admin=False,
        calendar_incident_id=pending.id,
        write=_chronology_write(),
    )

    await services.delete_chronology(
        author, is_admin=False, chronology_id=chronology.id
    )
    assert not await CalendarIncidentChronology.objects.filter(
        pk=chronology.id
    ).aexists()


@pytest.mark.django_db
async def test_delete_chronology_author_live_on_live_parent_rejected():
    author = await _make_user(23)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        author, is_admin=False, calendar_incident_id=live.id, write=_chronology_write()
    )

    with pytest.raises(services.IncidentNotEditableError):
        await services.delete_chronology(
            author, is_admin=False, chronology_id=chronology.id
        )


# ---------------------------------------------------------------------------
# Task 6+7 — Spec gap scenario: pending chronology deletion + admin deletes parent
# ---------------------------------------------------------------------------


@pytest.mark.django_db
async def test_gap_scenario_pending_chronology_deletion_then_parent_deleted():
    """Spec D6 gap: chronology marked PENDING_DELETION on a LIVE incident,
    then admin deletes the parent → chronology is soft-deleted (no orphaned
    PENDING_DELETION child).
    """
    author = await _make_user(30)
    admin = await _make_user(31)
    live = await _make_incident(
        author, is_admin=True, status=CalendarIncidentStatus.LIVE
    )
    chronology = await services.create_chronology(
        author, is_admin=False, calendar_incident_id=live.id, write=_chronology_write()
    )

    await services.request_chronology_deletion(
        author, is_admin=False, chronology_id=chronology.id
    )

    await services.delete_incident(admin, is_admin=True, incident_id=live.id)

    assert not await CalendarIncidentChronology.objects.filter(
        pk=chronology.id
    ).aexists()
    assert await CalendarIncidentChronology.all_objects.filter(
        pk=chronology.id
    ).aexists()


@pytest.mark.django_db
async def test_draft_revision_resolution_on_parent_delete():
    """Spec D6: parent with an open draft revision deleted by admin →
    revision is soft-deleted too.
    """
    admin = await _make_user(32)
    editor = await _make_user(33)
    live = await _make_incident(
        admin, is_admin=True, status=CalendarIncidentStatus.LIVE
    )

    # Create a draft revision (as a non-admin editor would via update_incident).
    revision = await services.update_incident(
        editor,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Edited title"),
    )
    # update_incident returns UpdateResult; the revision is the incident field.
    revision_id = revision.incident.id
    assert revision.incident.status == CalendarIncidentStatus.DRAFT

    await services.delete_incident(admin, is_admin=True, incident_id=live.id)

    assert not await CalendarIncident.objects.filter(pk=revision_id).aexists()
    assert await CalendarIncident.all_objects.filter(pk=revision_id).aexists()
