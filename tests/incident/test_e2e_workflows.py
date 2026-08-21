"""Complete user-journey workflows through the real DRAFT -> PENDING_APPROVAL intake.

Unlike test_integration_workflows.py (which simulates submission by setting
the status directly), every journey here goes through services.submit_incident
and asserts queue visibility through the same resolvers the console uses.
"""

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from safedelete.query import DELETED_VISIBLE

from common.models import User, Vote
from incident import services
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident
from incident.schema.loaders import batch_load_vote_scores
from incident.schema.resolvers import get_pending_calendar_incidents
from incident.tasks import purge_rejected_incidents, purge_soft_deleted_incidents


def _write(**overrides) -> services.IncidentWrite:
    defaults = dict(
        title="E2E Journey Incident",
        brief="journey brief",
        start_datetime=timezone.now(),
        severity="MINOR",
    )
    defaults.update(overrides)
    return services.IncidentWrite(**defaults)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"test-user-e2e-{n}")


async def _vote_score(incident_id: int) -> int:
    content_type = await sync_to_async(ContentType.objects.get_for_model)(
        CalendarIncident
    )
    scores = await batch_load_vote_scores([(content_type.id, incident_id)])
    return scores[0]


async def _backdate(incident_pk: int, field: str, days_ago: int) -> None:
    await (
        CalendarIncident.all_objects.all(force_visibility=DELETED_VISIBLE)
        .filter(pk=incident_pk)
        .aupdate(**{field: timezone.now() - timedelta(days=days_ago)})
    )


@pytest.mark.django_db
async def test_journey_user_submits_admin_approves_user_upvotes():
    user = await _make_user(1)
    admin = await _make_user(2)

    draft = await services.create_incident(
        user,
        is_admin=False,
        data=_write(),
        chronologies=(services.ChronologyWrite(indicator="RED", content="delay"),),
    )
    assert draft.status == CalendarIncidentStatus.DRAFT

    await services.submit_incident(user, is_admin=False, incident_id=draft.id)

    queue = await get_pending_calendar_incidents(None)
    assert [i.id for i in queue] == [draft.id]

    approved = await services.approve_incident(admin, incident_id=draft.id)
    assert approved.status == CalendarIncidentStatus.LIVE

    assert await get_pending_calendar_incidents(None) == []

    await services.set_incident_vote(user, incident_id=approved.id, value=1)
    assert await _vote_score(approved.id) == 1


@pytest.mark.django_db
async def test_journey_edit_live_revision_flows_through_queue_and_merges():
    author = await _make_user(3)
    admin = await _make_user(4)

    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original title")
    )

    result = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Corrected title"),
        chronologies=(services.ChronologyWrite(indicator="BLUE", content="fix"),),
    )
    assert result.created_revision
    revision = result.incident
    assert revision.status == CalendarIncidentStatus.DRAFT

    await services.submit_incident(author, is_admin=False, incident_id=revision.id)
    queue_ids = {i.id for i in await get_pending_calendar_incidents(None)}
    assert revision.id in queue_ids

    merged = await services.approve_incident(admin, incident_id=revision.id)

    assert merged.id == live.id
    assert merged.title == "Corrected title"
    chronology_contents = [c.content async for c in merged.chronologies.all()]
    assert chronology_contents == ["fix"]
    assert not await CalendarIncident.all_objects.filter(pk=revision.id).aexists()


@pytest.mark.django_db
async def test_journey_submit_then_reject_then_purge_after_30_days():
    user = await _make_user(5)
    admin = await _make_user(6)

    draft = await services.create_incident(user, is_admin=False, data=_write())
    await services.submit_incident(user, is_admin=False, incident_id=draft.id)

    rejected = await services.reject_incident(
        admin, incident_id=draft.id, reason="Duplicate of an existing report"
    )
    assert rejected.status == CalendarIncidentStatus.REJECTED
    assert rejected.rejection_reason == "Duplicate of an existing report"

    assert await get_pending_calendar_incidents(None) == []

    recent = await sync_to_async(purge_rejected_incidents)()
    assert recent == 0
    assert await CalendarIncident.all_objects.filter(pk=draft.pk).aexists()

    await _backdate(draft.pk, "modified", 31)
    count = await sync_to_async(purge_rejected_incidents)()
    assert count == 1
    assert not await CalendarIncident.all_objects.filter(pk=draft.pk).aexists()


@pytest.mark.django_db
async def test_journey_live_soft_delete_then_purge_after_90_days():
    author = await _make_user(7)
    voter = await _make_user(8)

    incident = await services.create_incident(
        author,
        is_admin=True,
        data=_write(),
        chronologies=(services.ChronologyWrite(indicator="GREEN", content="restored"),),
    )
    await services.set_incident_vote(voter, incident_id=incident.id, value=1)

    await services.delete_incident(author, is_admin=True, incident_id=incident.id)
    assert await CalendarIncident.all_objects.filter(pk=incident.pk).aexists()
    assert not await CalendarIncident.objects.filter(pk=incident.pk).aexists()

    await _backdate(incident.pk, "deleted", 91)
    count = await sync_to_async(purge_soft_deleted_incidents)()

    assert count == 1
    assert not await CalendarIncident.all_objects.filter(pk=incident.pk).aexists()
    assert not await Vote.objects.filter(object_id=incident.pk).aexists()
