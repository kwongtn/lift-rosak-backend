import pytest
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from common.models import User, Vote
from incident import services
from incident.models import CalendarIncident, CalendarIncidentChronology


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=f"test-user-vote-mut-{n}"
    )


async def _make_incident() -> CalendarIncident:
    return await sync_to_async(CalendarIncident.objects.create)(
        title="Votable Incident",
        brief="Test brief",
        severity="MINOR",
        start_datetime=timezone.now(),
    )


async def _make_chronology(incident: CalendarIncident) -> CalendarIncidentChronology:
    return await sync_to_async(CalendarIncidentChronology.objects.create)(
        calendar_incident=incident,
        indicator="RED",
        datetime=timezone.now(),
        content="Test chronology entry",
    )


async def _incident_content_type() -> ContentType:
    return await sync_to_async(ContentType.objects.get_for_model)(CalendarIncident)


async def _chronology_content_type() -> ContentType:
    return await sync_to_async(ContentType.objects.get_for_model)(
        CalendarIncidentChronology
    )


async def _vote_for(user: User, incident: CalendarIncident) -> Vote | None:
    ct = await _incident_content_type()
    return await Vote.objects.filter(
        user=user, content_type=ct, object_id=incident.id
    ).afirst()


async def _vote_for_chronology(
    user: User, chronology: CalendarIncidentChronology
) -> Vote | None:
    ct = await _chronology_content_type()
    return await Vote.objects.filter(
        user=user, content_type=ct, object_id=chronology.id
    ).afirst()


@pytest.mark.django_db
async def test_upvote_creates_vote():
    user = await _make_user(1)
    incident = await _make_incident()

    await services.set_incident_vote(user, incident_id=incident.id, value=1)

    vote = await _vote_for(user, incident)
    assert vote is not None
    assert vote.value == 1


@pytest.mark.django_db
async def test_upvote_changes_downvote():
    user = await _make_user(2)
    incident = await _make_incident()
    await services.set_incident_vote(user, incident_id=incident.id, value=-1)

    await services.set_incident_vote(user, incident_id=incident.id, value=1)

    votes = [v async for v in Vote.objects.filter(object_id=incident.id)]
    assert len(votes) == 1
    assert votes[0].value == 1


@pytest.mark.django_db
async def test_downvote_creates_vote():
    user = await _make_user(3)
    incident = await _make_incident()

    await services.set_incident_vote(user, incident_id=incident.id, value=-1)

    vote = await _vote_for(user, incident)
    assert vote is not None
    assert vote.value == -1


@pytest.mark.django_db
async def test_remove_vote():
    user = await _make_user(4)
    incident = await _make_incident()
    await services.set_incident_vote(user, incident_id=incident.id, value=1)

    removed = await services.remove_incident_vote(user, incident_id=incident.id)

    assert removed
    assert await _vote_for(user, incident) is None

    removed_again = await services.remove_incident_vote(user, incident_id=incident.id)
    assert not removed_again


# --- Chronology vote tests ---


@pytest.mark.django_db
async def test_chronology_upvote_creates_vote():
    user = await _make_user(10)
    incident = await _make_incident()
    chronology = await _make_chronology(incident)

    await services.set_chronology_vote(user, chronology_id=chronology.id, value=1)

    vote = await _vote_for_chronology(user, chronology)
    assert vote is not None
    assert vote.value == 1


@pytest.mark.django_db
async def test_chronology_upvote_changes_downvote():
    user = await _make_user(11)
    incident = await _make_incident()
    chronology = await _make_chronology(incident)
    await services.set_chronology_vote(user, chronology_id=chronology.id, value=-1)

    await services.set_chronology_vote(user, chronology_id=chronology.id, value=1)

    votes = [v async for v in Vote.objects.filter(object_id=chronology.id)]
    assert len(votes) == 1
    assert votes[0].value == 1


@pytest.mark.django_db
async def test_chronology_downvote_creates_vote():
    user = await _make_user(12)
    incident = await _make_incident()
    chronology = await _make_chronology(incident)

    await services.set_chronology_vote(user, chronology_id=chronology.id, value=-1)

    vote = await _vote_for_chronology(user, chronology)
    assert vote is not None
    assert vote.value == -1


@pytest.mark.django_db
async def test_chronology_remove_vote():
    user = await _make_user(13)
    incident = await _make_incident()
    chronology = await _make_chronology(incident)
    await services.set_chronology_vote(user, chronology_id=chronology.id, value=1)

    removed = await services.remove_chronology_vote(user, chronology_id=chronology.id)

    assert removed
    assert await _vote_for_chronology(user, chronology) is None

    removed_again = await services.remove_chronology_vote(
        user, chronology_id=chronology.id
    )
    assert not removed_again


@pytest.mark.django_db
async def test_chronology_vote_unknown_id_raises():
    user = await _make_user(14)

    with pytest.raises(services.IncidentServiceError, match="does not exist"):
        await services.set_chronology_vote(user, chronology_id=999_999, value=1)

    with pytest.raises(services.IncidentServiceError, match="does not exist"):
        await services.remove_chronology_vote(user, chronology_id=999_999)


@pytest.mark.django_db
async def test_incident_votes_still_work_regression():
    user = await _make_user(15)
    incident = await _make_incident()

    await services.set_incident_vote(user, incident_id=incident.id, value=1)
    vote = await _vote_for(user, incident)
    assert vote is not None
    assert vote.value == 1

    await services.set_incident_vote(user, incident_id=incident.id, value=-1)
    vote = await _vote_for(user, incident)
    assert vote.value == -1

    removed = await services.remove_incident_vote(user, incident_id=incident.id)
    assert removed
    assert await _vote_for(user, incident) is None
