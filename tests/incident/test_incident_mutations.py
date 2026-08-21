import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.models import User
from incident import services
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident


def _write(**overrides) -> services.IncidentWrite:
    defaults = dict(
        title="Test Incident",
        brief="Test brief",
        start_datetime=timezone.now(),
        severity="MINOR",
    )
    defaults.update(overrides)
    return services.IncidentWrite(**defaults)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=f"test-user-mutation-{n}"
    )


@pytest.mark.django_db
async def test_user_creates_draft():
    user = await _make_user(1)

    incident = await services.create_incident(user, is_admin=False, data=_write())

    assert incident.status == CalendarIncidentStatus.DRAFT
    assert incident.created_by_id == user.id
    assert incident.version == 1


@pytest.mark.django_db
async def test_admin_creates_live():
    admin = await _make_user(2)

    incident = await services.create_incident(
        admin,
        is_admin=True,
        data=_write(),
        chronologies=(
            services.ChronologyWrite(indicator="GREEN", content="line down"),
        ),
    )

    assert incident.status == CalendarIncidentStatus.LIVE
    chronologies = [c async for c in incident.chronologies.all()]
    assert len(chronologies) == 1
    assert chronologies[0].status == CalendarIncidentStatus.LIVE


@pytest.mark.django_db
async def test_user_edit_creates_draft_revision():
    author = await _make_user(3)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    result = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Edited"),
    )

    assert result.created_revision
    assert result.incident.status == CalendarIncidentStatus.DRAFT
    assert result.incident.parent_incident_id == live.id

    await sync_to_async(live.refresh_from_db)()
    assert live.title == "Original"
    assert live.status == CalendarIncidentStatus.LIVE


@pytest.mark.django_db
async def test_approve_merges_draft_to_parent():
    author = await _make_user(4)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )
    revision_result = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=None,
        data=_write(title="Merged Title"),
        chronologies=(services.ChronologyWrite(indicator="RED", content="revised"),),
    )
    version_before_merge = live.version

    await services.approve_incident(author, incident_id=revision_result.incident.id)

    await sync_to_async(live.refresh_from_db)()
    assert live.title == "Merged Title"
    assert live.status == CalendarIncidentStatus.LIVE
    assert live.version == version_before_merge + 1

    chronologies = [c async for c in live.chronologies.all()]
    assert len(chronologies) == 1
    assert chronologies[0].content == "revised"

    assert not await CalendarIncident.all_objects.filter(
        pk=revision_result.incident.id
    ).aexists()


@pytest.mark.django_db
async def test_optimistic_concurrency_control():
    author = await _make_user(5)
    draft = await services.create_incident(author, is_admin=False, data=_write())

    await services.update_incident(
        author,
        is_admin=False,
        incident_id=draft.id,
        expected_version=draft.version,
        data=_write(title="First edit"),
    )
    await sync_to_async(draft.refresh_from_db)()
    assert draft.version == 2

    with pytest.raises(services.ConcurrencyConflictError):
        await services.update_incident(
            author,
            is_admin=False,
            incident_id=draft.id,
            expected_version=1,
            data=_write(title="Stale edit"),
        )

    await sync_to_async(draft.refresh_from_db)()
    assert draft.title == "First edit"


@pytest.mark.django_db
async def test_reject_records_reason_and_status():
    author = await _make_user(6)
    pending = await services.create_incident(author, is_admin=False, data=_write())
    await sync_to_async(pending.__setattr__)(
        "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(pending.save)()

    rejected = await services.reject_incident(
        author, incident_id=pending.id, reason="Duplicate of #12"
    )

    assert rejected.status == CalendarIncidentStatus.REJECTED
    assert rejected.rejection_reason == "Duplicate of #12"


@pytest.mark.django_db
async def test_delete_rules():
    author = await _make_user(7)
    other = await _make_user(8)
    admin = await _make_user(9)

    own_draft = await services.create_incident(author, is_admin=False, data=_write())
    await services.delete_incident(author, is_admin=False, incident_id=own_draft.id)
    assert not await CalendarIncident.objects.filter(pk=own_draft.id).aexists()
    assert await CalendarIncident.all_objects.filter(pk=own_draft.id).aexists()

    someone_elses_draft = await services.create_incident(
        other, is_admin=False, data=_write()
    )
    with pytest.raises(services.IncidentNotEditableError):
        await services.delete_incident(
            author, is_admin=False, incident_id=someone_elses_draft.id
        )

    live = await services.create_incident(other, is_admin=True, data=_write())
    with pytest.raises(services.IncidentNotEditableError):
        await services.delete_incident(other, is_admin=False, incident_id=live.id)
    await services.delete_incident(admin, is_admin=True, incident_id=live.id)
    assert not await CalendarIncident.objects.filter(pk=live.id).aexists()


@pytest.mark.django_db
async def test_approve_requires_pending_for_non_revision():
    author = await _make_user(10)
    draft = await services.create_incident(author, is_admin=False, data=_write())

    with pytest.raises(services.IncidentNotEditableError):
        await services.approve_incident(author, incident_id=draft.id)
