from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from safedelete.query import DELETED_VISIBLE

from common.models import User
from incident import services
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident
from incident.tasks import purge_rejected_incidents, purge_soft_deleted_incidents


def _write(**overrides) -> services.IncidentWrite:
    defaults = dict(
        title="Purge Candidate",
        brief="Test brief",
        start_datetime=timezone.now(),
        severity="MINOR",
    )
    defaults.update(overrides)
    return services.IncidentWrite(**defaults)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"test-user-purge-{n}")


async def _backdate(incident_pk: int, field: str, days_ago: int) -> None:
    await (
        CalendarIncident.all_objects.all(force_visibility=DELETED_VISIBLE)
        .filter(pk=incident_pk)
        .aupdate(**{field: timezone.now() - timedelta(days=days_ago)})
    )


@pytest.mark.django_db
async def test_purges_soft_deleted_after_90_days():
    user = await _make_user(1)
    incident = await services.create_incident(user, is_admin=False, data=_write())
    await sync_to_async(incident.delete)()
    await _backdate(incident.pk, "deleted", 91)

    count = await sync_to_async(purge_soft_deleted_incidents)()

    assert count == 1
    assert not await CalendarIncident.all_objects.filter(pk=incident.pk).aexists()


@pytest.mark.django_db
async def test_purges_rejected_after_30_days():
    user = await _make_user(2)
    pending = await services.create_incident(user, is_admin=False, data=_write())
    await sync_to_async(setattr)(
        pending, "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(pending.save)()
    await services.reject_incident(user, incident_id=pending.id, reason="spam")
    await _backdate(pending.pk, "modified", 31)

    count = await sync_to_async(purge_rejected_incidents)()

    assert count == 1
    assert not await CalendarIncident.all_objects.filter(pk=pending.pk).aexists()


@pytest.mark.django_db
async def test_does_not_purge_recent_entries():
    user = await _make_user(3)

    recent_deleted = await services.create_incident(user, is_admin=False, data=_write())
    await sync_to_async(recent_deleted.delete)()
    await _backdate(recent_deleted.pk, "deleted", 10)

    recent_rejected = await services.create_incident(
        user, is_admin=False, data=_write()
    )
    await sync_to_async(setattr)(
        recent_rejected, "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(recent_rejected.save)()
    await services.reject_incident(user, incident_id=recent_rejected.id, reason="dup")
    await _backdate(recent_rejected.pk, "modified", 5)

    old_live = await services.create_incident(user, is_admin=True, data=_write())
    await _backdate(old_live.pk, "modified", 400)

    assert await sync_to_async(purge_soft_deleted_incidents)() == 0
    assert await sync_to_async(purge_rejected_incidents)() == 0

    for pk in (recent_deleted.pk, recent_rejected.pk, old_live.pk):
        assert await CalendarIncident.all_objects.filter(pk=pk).aexists()
