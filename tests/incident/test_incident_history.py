"""Tests for the calendarIncidentHistory query (Task 18 backend).

Executes the real GraphQL schema and asserts the history entries returned for
created/updated incidents, actor mapping, permissions, latest-first ordering,
and the unknown-id error path.
"""

import copy

import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.utils import timezone
from dotmap import DotMap

from common.models import User
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident
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
    return result


async def _make_incident(**overrides) -> CalendarIncident:
    defaults = dict(
        title="History Incident",
        brief="history brief",
        severity="MINOR",
        start_datetime=timezone.now(),
        status=CalendarIncidentStatus.LIVE,
    )
    defaults.update(overrides)
    return await sync_to_async(CalendarIncident.objects.create)(**defaults)


async def _make_user(firebase_id: str, nickname: str = "") -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=firebase_id, nickname=nickname
    )


def _history_query(incident_id: int) -> str:
    return f"""
        query {{
            calendarIncidentHistory(id: "{incident_id}") {{
                timestamp
                actor
                changeType
                changedFields
            }}
        }}
    """


@pytest.mark.django_db
async def test_created_incident_has_single_created_entry():
    incident = await _make_incident()

    result = await _execute(
        _build_schema(),
        _history_query(incident.id),
        user=await _make_user("history-tester-1"),
    )
    assert result.errors is None, result.errors

    entries = result.data["calendarIncidentHistory"]
    assert len(entries) == 1
    assert entries[0]["changeType"] == "created"
    assert entries[0]["changedFields"] == ["created"]


@pytest.mark.django_db
async def test_updated_incident_latest_entry_shows_updated_and_changed_title():
    incident = await _make_incident(title="Original Title")
    incident.title = "Updated Title"
    await sync_to_async(incident.save)()

    result = await _execute(
        _build_schema(),
        _history_query(incident.id),
        user=await _make_user("history-tester-2"),
    )
    assert result.errors is None, result.errors

    entries = result.data["calendarIncidentHistory"]
    assert len(entries) == 2
    latest = entries[0]
    assert latest["changeType"] == "updated"
    assert "title" in latest["changedFields"]


@pytest.mark.django_db
async def test_actor_mapping_auth_user_username():
    # The history_user FK targets auth.User (settings.AUTH_USER_MODEL), not
    # common.User. Create an auth.User and set it as _history_user to verify
    # the actor is populated from the history record.
    from django.contrib.auth.models import User as AuthUser

    auth_user = await sync_to_async(AuthUser.objects.create_user)(
        username="history-actor-1", password="x"
    )
    incident = await _make_incident()
    incident._history_user = auth_user
    incident.title = "Edited By Actor"
    await sync_to_async(incident.save)()

    result = await _execute(
        _build_schema(),
        _history_query(incident.id),
        user=await _make_user("history-tester-3"),
    )
    assert result.errors is None, result.errors

    entries = result.data["calendarIncidentHistory"]
    # Latest entry is the update made by the user.
    latest = entries[0]
    assert latest["changeType"] == "updated"
    assert latest["actor"] == "history-actor-1"


@pytest.mark.django_db
async def test_actor_null_when_system_makes_change():
    incident = await _make_incident()
    # No _history_user set → simple-history records None.
    incident.title = "System Edit"
    await sync_to_async(incident.save)()

    result = await _execute(
        _build_schema(),
        _history_query(incident.id),
        user=await _make_user("history-tester-4"),
    )
    assert result.errors is None, result.errors

    entries = result.data["calendarIncidentHistory"]
    latest = entries[0]
    assert latest["changeType"] == "updated"
    assert latest["actor"] is None


@pytest.mark.django_db
async def test_anonymous_access_rejected():
    incident = await _make_incident()

    result = await _execute(_build_schema(), _history_query(incident.id), user=None)
    assert result.errors is not None
    assert any("not logged in" in str(e.message) for e in result.errors)


@pytest.mark.django_db
async def test_latest_first_ordering():
    incident = await _make_incident(title="V1")
    incident.title = "V2"
    await sync_to_async(incident.save)()
    incident.title = "V3"
    await sync_to_async(incident.save)()

    result = await _execute(
        _build_schema(),
        _history_query(incident.id),
        user=await _make_user("history-tester-6"),
    )
    assert result.errors is None, result.errors

    entries = result.data["calendarIncidentHistory"]
    assert len(entries) == 3
    # Latest-first: V3 (updated) → V2 (updated) → V1 (created).
    assert entries[0]["changeType"] == "updated"
    assert entries[1]["changeType"] == "updated"
    assert entries[2]["changeType"] == "created"
    # Timestamps are non-increasing.
    timestamps = [e["timestamp"] for e in entries]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.django_db
async def test_unknown_id_returns_error():
    result = await _execute(
        _build_schema(),
        _history_query(999999),
        user=await _make_user("history-tester-7"),
    )
    assert result.errors is not None
    assert any("does not exist" in str(e.message) for e in result.errors)
