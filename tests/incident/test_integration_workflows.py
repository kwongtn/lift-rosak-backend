"""End-to-end workflow tests spanning services, votes, and purge tasks."""

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
from incident.tasks import purge_rejected_incidents, purge_soft_deleted_incidents


def _write(**overrides) -> services.IncidentWrite:
    defaults = dict(
        title="Workflow Incident",
        brief="Workflow brief",
        start_datetime=timezone.now(),
        severity="MINOR",
    )
    defaults.update(overrides)
    return services.IncidentWrite(**defaults)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=f"test-user-integration-{n}"
    )


async def _upvote(user: User, incident_id: int) -> None:
    await services.set_incident_vote(user, incident_id=incident_id, value=1)


async def _vote_score(incident_id: int) -> int:
    content_type = await sync_to_async(ContentType.objects.get_for_model)(
        CalendarIncident
    )
    scores = await batch_load_vote_scores([(content_type.id, incident_id)])
    return scores[0]


@pytest.mark.django_db
async def test_submit_approve_upvote_workflow():
    user = await _make_user(1)
    admin = await _make_user(2)

    draft = await services.create_incident(user, is_admin=False, data=_write())
    assert draft.status == CalendarIncidentStatus.DRAFT

    draft.status = CalendarIncidentStatus.PENDING_APPROVAL
    await sync_to_async(draft.save)()

    approved = await services.approve_incident(admin, incident_id=draft.id)
    assert approved.status == CalendarIncidentStatus.LIVE

    await _upvote(user, approved.id)

    assert await _vote_score(approved.id) == 1
    votes = [v async for v in approved.votes.all()]
    assert len(votes) == 1
    assert votes[0].value == 1
    assert votes[0].user_id == user.id


@pytest.mark.django_db
async def test_edit_live_merge_preserves_votes():
    author = await _make_user(3)
    voter = await _make_user(4)
    admin = await _make_user(5)

    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )
    await _upvote(voter, live.id)

    result = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Revised"),
        chronologies=(services.ChronologyWrite(indicator="RED", content="updated"),),
    )
    assert result.created_revision

    merged = await services.approve_incident(admin, incident_id=result.incident.id)

    assert merged.id == live.id
    assert merged.title == "Revised"
    assert merged.version == live.version + 1
    assert not await CalendarIncident.all_objects.filter(
        pk=result.incident.id
    ).aexists()

    assert await _vote_score(live.id) == 1
    remaining_votes = [v async for v in live.votes.all()]
    assert [v.user_id for v in remaining_votes] == [voter.id]


async def _backdate(incident_pk: int, field: str, days_ago: int) -> None:
    await (
        CalendarIncident.all_objects.all(force_visibility=DELETED_VISIBLE)
        .filter(pk=incident_pk)
        .aupdate(**{field: timezone.now() - timedelta(days=days_ago)})
    )


@pytest.mark.django_db
async def test_soft_delete_purge_after_90_days_cascades_votes():
    user = await _make_user(6)
    voter = await _make_user(7)

    incident = await services.create_incident(
        user,
        is_admin=False,
        data=_write(),
        chronologies=(services.ChronologyWrite(indicator="GREEN", content="delay"),),
    )
    await _upvote(voter, incident.id)

    await sync_to_async(incident.delete)()
    assert await CalendarIncident.all_objects.filter(pk=incident.pk).aexists()
    await _backdate(incident.pk, "deleted", 91)

    count = await sync_to_async(purge_soft_deleted_incidents)()

    assert count == 1
    assert not await CalendarIncident.all_objects.filter(pk=incident.pk).aexists()
    assert not await Vote.objects.filter(object_id=incident.pk).aexists()


@pytest.mark.django_db
async def test_rejected_purge_after_30_days():
    user = await _make_user(8)
    admin = await _make_user(9)

    pending = await services.create_incident(user, is_admin=False, data=_write())
    pending.status = CalendarIncidentStatus.PENDING_APPROVAL
    await sync_to_async(pending.save)()

    rejected = await services.reject_incident(
        admin, incident_id=pending.id, reason="Duplicate"
    )
    assert rejected.status == CalendarIncidentStatus.REJECTED
    await _backdate(pending.pk, "modified", 31)

    count = await sync_to_async(purge_rejected_incidents)()

    assert count == 1
    assert not await CalendarIncident.all_objects.filter(pk=pending.pk).aexists()


@pytest.mark.django_db
async def test_full_lifecycle_draft_to_live_to_soft_deleted():
    user = await _make_user(10)
    admin = await _make_user(11)

    draft = await services.create_incident(user, is_admin=False, data=_write())
    draft.status = CalendarIncidentStatus.PENDING_APPROVAL
    await sync_to_async(draft.save)()

    await services.approve_incident(admin, incident_id=draft.id)
    await sync_to_async(draft.refresh_from_db)()
    assert draft.status == CalendarIncidentStatus.LIVE

    result = await services.update_incident(
        user,
        is_admin=False,
        incident_id=draft.id,
        expected_version=draft.version,
        data=_write(title="Lifecycle Revised"),
    )
    await services.approve_incident(admin, incident_id=result.incident.id)
    await sync_to_async(draft.refresh_from_db)()
    assert draft.title == "Lifecycle Revised"

    await services.delete_incident(admin, is_admin=True, incident_id=draft.id)
    assert not await CalendarIncident.objects.filter(pk=draft.pk).aexists()
    assert await CalendarIncident.all_objects.filter(pk=draft.pk).aexists()
