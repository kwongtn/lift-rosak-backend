import pytest
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType

from common.models import User, Vote
from incident.models import CalendarIncident
from incident.schema.loaders import (
    batch_load_user_vote_value,
    batch_load_vote_breakdown,
    batch_load_vote_scores,
)


async def _make_incident(title: str) -> CalendarIncident:
    return await sync_to_async(CalendarIncident.objects.create)(
        title=title,
        brief="Test incident for vote loaders",
        severity="MINOR",
        start_datetime="2026-01-01T00:00:00Z",
    )


async def _make_voter(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"test-user-vote-{n}")


async def _cast_vote(user: User, incident: CalendarIncident, value: int) -> None:
    ct = await sync_to_async(ContentType.objects.get)(
        app_label="incident", model="calendarincident"
    )
    await Vote.objects.acreate(
        user=user, content_type=ct, object_id=incident.id, value=value
    )


async def _content_type() -> ContentType:
    return await sync_to_async(ContentType.objects.get)(
        app_label="incident", model="calendarincident"
    )


@pytest.mark.django_db
async def test_vote_score_aggregation():
    """5 upvotes + 2 downvotes = +3 net score."""
    incident = await _make_incident("Vote Test Incident")
    for i in range(5):
        await _cast_vote(await _make_voter(f"agg-{i}"), incident, 1)
    for i in range(2):
        await _cast_vote(await _make_voter(f"agg-down-{i}"), incident, -1)

    ct = await _content_type()
    score = await batch_load_vote_scores([(ct.id, incident.id)])
    assert score == [3]


@pytest.mark.django_db
async def test_vote_breakdown_loader():
    """Separate upvote/downvote counts."""
    incident = await _make_incident("Vote Breakdown Test Incident")
    for i in range(5):
        await _cast_vote(await _make_voter(f"brk-{i}"), incident, 1)
    for i in range(2):
        await _cast_vote(await _make_voter(f"brk-down-{i}"), incident, -1)

    ct = await _content_type()
    breakdown = await batch_load_vote_breakdown([(ct.id, incident.id)])
    assert breakdown == [{"upvotes": 5, "downvotes": 2}]


@pytest.mark.django_db
async def test_user_vote_value_loader():
    """Current user's vote value for objects; non-voters get 0."""
    voter_up = await _make_voter("value-up")
    voter_down = await _make_voter("value-down")
    bystander = await _make_voter("value-none")
    incident = await _make_incident("Vote Value Test Incident")

    await _cast_vote(voter_up, incident, 1)
    await _cast_vote(voter_down, incident, -1)

    ct = await _content_type()
    values = await batch_load_user_vote_value(
        [
            (voter_up.id, ct.id, incident.id),
            (voter_down.id, ct.id, incident.id),
            (bystander.id, ct.id, incident.id),
        ]
    )
    assert values == [1, -1, 0]
