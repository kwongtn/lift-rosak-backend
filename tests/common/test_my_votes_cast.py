"""Tests for `myVotesCast` (Task 25) — the logged-in user's aggregate votes-cast stat.

Executes the real GraphQL schema (like tests/incident/test_scalar_fields.py) and asserts:
- votes across MULTIPLE content types (CalendarIncident + CalendarIncidentChronology)
  sum into one count;
- downvotes count toward the total (votes cast = up + down);
- another user's votes never leak into the caller's count;
- anonymous callers are rejected by the IsLoggedIn permission.
"""

import copy

import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from dotmap import DotMap

from common.models import User, Vote
from incident.models import CalendarIncident, CalendarIncidentChronology
from incident.schema.loaders import IncidentContextLoaders


def _build_schema():
    import django

    django.setup()
    from rosak.schema import Query

    return strawberry.Schema(query=Query)


def _context(user=None):
    return DotMap(
        {
            "loaders": {"incident": copy.deepcopy(IncidentContextLoaders)},
            "request": None,
            "response": None,
            "user": user,
        }
    )


async def _execute(schema, query: str, user=None):
    result = await schema.execute(query, context_value=_context(user))
    assert result.errors is None, result.errors
    return result.data


async def _make_user(firebase_id: str) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=firebase_id)


async def _make_incident() -> CalendarIncident:
    return await sync_to_async(CalendarIncident.objects.create)(
        title="Votes-Cast Incident",
        brief="test brief",
        severity="MINOR",
        start_datetime=timezone.now(),
    )


async def _make_chronology(incident: CalendarIncident) -> CalendarIncidentChronology:
    return await sync_to_async(CalendarIncidentChronology.objects.create)(
        calendar_incident=incident,
        indicator="GREEN",
        datetime=timezone.now(),
    )


async def _content_type(model) -> ContentType:
    return await sync_to_async(ContentType.objects.get_for_model)(model)


async def _vote(user: User, model, object_id: int, value: int) -> Vote:
    return await sync_to_async(Vote.objects.create)(
        user=user,
        content_type=await _content_type(model),
        object_id=object_id,
        value=value,
    )


@pytest.mark.django_db
async def test_my_votes_cast_sums_across_content_types():
    user = await _make_user("votes-cast-user-1")
    incident = await _make_incident()
    chronology = await _make_chronology(incident)

    # One upvote on an incident + one downvote on a chronology: 2 votes cast.
    await _vote(user, CalendarIncident, incident.id, 1)
    await _vote(user, CalendarIncidentChronology, chronology.id, -1)

    data = await _execute(
        _build_schema(),
        """
        query {
          myVotesCast
        }
        """,
        user=user,
    )

    assert data["myVotesCast"] == 2


@pytest.mark.django_db
async def test_my_votes_cast_ignores_other_users_votes():
    caller = await _make_user("votes-cast-user-2")
    other = await _make_user("votes-cast-user-3")
    incident = await _make_incident()

    await _vote(caller, CalendarIncident, incident.id, 1)
    await _vote(other, CalendarIncident, incident.id, 1)
    await _vote(other, CalendarIncident, incident.id + 99999, -1)

    data = await _execute(
        _build_schema(),
        "query { myVotesCast }",
        user=caller,
    )

    assert data["myVotesCast"] == 1


@pytest.mark.django_db
async def test_my_votes_cast_zero_when_no_votes():
    user = await _make_user("votes-cast-user-4")

    data = await _execute(
        _build_schema(),
        "query { myVotesCast }",
        user=user,
    )

    assert data["myVotesCast"] == 0


@pytest.mark.django_db
async def test_my_votes_cast_anonymous_rejected():
    schema = _build_schema()

    result = await schema.execute("query { myVotesCast }", context_value=_context(None))

    assert result.errors is not None
    assert any("not logged in" in str(e.message) for e in result.errors)
