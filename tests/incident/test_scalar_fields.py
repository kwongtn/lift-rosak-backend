"""Tests for Task 1 scalar exposure: `version`, chronology `status`, `completedBy`.

Executes the real GraphQL schema (not just introspection) and asserts the actual
values returned for each newly exposed field, including null/default cases.
"""

import copy

import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.utils import timezone
from dotmap import DotMap

from common.models import User
from incident.enums import CalendarIncidentStatus
from incident.models import (
    CalendarIncident,
    CalendarIncidentChronology,
    SocialMediaLink,
)
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


async def _make_incident(**overrides) -> CalendarIncident:
    defaults = dict(
        title="Scalar Incident",
        brief="scalar brief",
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


@pytest.mark.django_db
async def test_calendar_incident_scalar_exposes_version():
    incident = await _make_incident(version=3)

    data = await _execute(
        _build_schema(),
        """
        query {
          calendarIncidents {
            id
            version
          }
        }
        """,
    )

    by_id = {item["id"]: item["version"] for item in data["calendarIncidents"]}
    assert by_id[str(incident.id)] == 3


@pytest.mark.django_db
async def test_chronology_scalar_exposes_status_default_draft():
    incident = await _make_incident()
    chronology = await sync_to_async(CalendarIncidentChronology.objects.create)(
        calendar_incident=incident,
        indicator="GREEN",
        datetime=timezone.now(),
    )
    assert chronology.status == CalendarIncidentStatus.DRAFT

    data = await _execute(
        _build_schema(),
        """
        query {
          calendarIncidents {
            id
            chronologies {
              id
              status
            }
          }
        }
        """,
    )

    incident_item = next(
        item for item in data["calendarIncidents"] if item["id"] == str(incident.id)
    )
    chrono_item = next(
        c for c in incident_item["chronologies"] if c["id"] == str(chronology.id)
    )
    assert chrono_item["status"] == "DRAFT"


@pytest.mark.django_db
async def test_chronology_scalar_exposes_non_default_status():
    incident = await _make_incident()
    chronology = await sync_to_async(CalendarIncidentChronology.objects.create)(
        calendar_incident=incident,
        indicator="GREEN",
        datetime=timezone.now(),
        status=CalendarIncidentStatus.PENDING_APPROVAL,
    )

    data = await _execute(
        _build_schema(),
        """
        query {
          calendarIncidents {
            id
            chronologies {
              id
              status
            }
          }
        }
        """,
    )

    incident_item = next(
        item for item in data["calendarIncidents"] if item["id"] == str(incident.id)
    )
    chrono_item = next(
        c for c in incident_item["chronologies"] if c["id"] == str(chronology.id)
    )
    assert chrono_item["status"] == "PENDING_APPROVAL"


@pytest.mark.django_db
async def test_social_media_link_completed_by_null_when_never_completed():
    submitter = await _make_user("test-scalar-user-1")
    link = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/open",
        title="",
        user=submitter,
    )

    data = await _execute(
        _build_schema(),
        """
        query {
          publicSocialMediaLinks {
            edges {
              node {
                id
                completedBy
              }
            }
          }
        }
        """,
    )

    edges = data["publicSocialMediaLinks"]["edges"]
    item = next(e["node"] for e in edges if e["node"]["id"] == str(link.id))
    assert item["completedBy"] is None


@pytest.mark.django_db
async def test_social_media_link_completed_by_returns_nickname():
    submitter = await _make_user("test-scalar-user-2")
    admin = await _make_user("test-scalar-admin-1", nickname="Console Admin")
    link = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/done",
        title="",
        user=submitter,
        completed=True,
        completed_at=timezone.now(),
        completed_by=admin,
    )

    data = await _execute(
        _build_schema(),
        """
        query {
          publicSocialMediaLinks {
            edges {
              node {
                id
                completedBy
              }
            }
          }
        }
        """,
    )

    edges = data["publicSocialMediaLinks"]["edges"]
    item = next(e["node"] for e in edges if e["node"]["id"] == str(link.id))
    assert item["completedBy"] == "Console Admin"


@pytest.mark.django_db
async def test_social_media_link_completed_by_falls_back_to_short_id():
    submitter = await _make_user("test-scalar-user-3")
    admin = await _make_user("abcdef1234567890")
    link = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/done2",
        title="",
        user=submitter,
        completed=True,
        completed_at=timezone.now(),
        completed_by=admin,
    )

    data = await _execute(
        _build_schema(),
        """
        query {
          publicSocialMediaLinks {
            edges {
              node {
                id
                completedBy
              }
            }
          }
        }
        """,
    )

    edges = data["publicSocialMediaLinks"]["edges"]
    item = next(e["node"] for e in edges if e["node"]["id"] == str(link.id))
    assert item["completedBy"] == "abcdef12"


@pytest.mark.django_db
async def test_calendar_incident_scalar_exposes_author_short_id():
    author = await _make_user("cal-incident-author-1", nickname="Author One")
    incident = await _make_incident(created_by=author)

    data = await _execute(
        _build_schema(),
        """
        query {
          calendarIncidents {
            id
            user {
              shortId
              nickname
            }
          }
        }
        """,
    )

    item = next(i for i in data["calendarIncidents"] if i["id"] == str(incident.id))
    assert item["user"]["shortId"] == "cal-inci"
    assert item["user"]["nickname"] == "Author One"


@pytest.mark.django_db
async def test_calendar_incident_scalar_author_null_when_no_created_by():
    incident = await _make_incident()

    data = await _execute(
        _build_schema(),
        """
        query {
          calendarIncidents {
            id
            user {
              shortId
            }
          }
        }
        """,
    )

    item = next(i for i in data["calendarIncidents"] if i["id"] == str(incident.id))
    assert item["user"] is None
