"""Schema tests for `lineStatusReports` keyset pagination over LineStatusReport."""

import copy
from datetime import timedelta

import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.utils import timezone
from dotmap import DotMap

from common.models import User
from incident.enums import PassengerStatus
from incident.models import LineStatusReport
from incident.schema.loaders import IncidentContextLoaders
from operation.models import Line

QUERY = """
query($id: ID!, $first: Int!, $after: String) {
  lineStatusReports(lineId: $id, first: $first, after: $after) {
    edges {
      node {
        id
        status
        delayMinutes
        notes
        user { nickname }
      }
      cursor
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _build_schema():
    import django

    django.setup()
    from rosak.schema import Query

    return strawberry.Schema(query=Query)


def _context():
    return DotMap(
        {
            "loaders": {"incident": copy.deepcopy(IncidentContextLoaders)},
            "request": None,
            "response": None,
            "user": None,
        }
    )


async def _execute(line_id, first=20, after=None):
    result = await _build_schema().execute(
        QUERY,
        variable_values={"id": str(line_id), "first": first, "after": after},
        context_value=_context(),
    )
    assert result.errors is None, result.errors
    return result.data["lineStatusReports"]


async def _make_user(firebase_id: str, nickname: str) -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=firebase_id, nickname=nickname
    )


async def _make_line(code: str) -> Line:
    return await sync_to_async(Line.objects.create)(
        code=code,
        display_name=f"Line {code}",
        display_color="#FF0000",
    )


async def _make_report(
    line: Line, user: User, status: str, *, minutes_ago: int, notes=""
):
    report = await sync_to_async(LineStatusReport.objects.create)(
        line=line, status=status, user=user, notes=notes, delay_minutes=5
    )
    await sync_to_async(LineStatusReport.objects.filter(pk=report.pk).update)(
        created=timezone.now() - timedelta(minutes=minutes_ago)
    )
    return report


@pytest.mark.django_db
async def test_reports_are_newest_first():
    user = await _make_user("reports-owner", "Owner")
    line = await _make_line("R1")
    oldest = await _make_report(line, user, PassengerStatus.NORMAL, minutes_ago=30)
    middle = await _make_report(line, user, PassengerStatus.BUSY, minutes_ago=20)
    newest = await _make_report(line, user, PassengerStatus.CROWDED, minutes_ago=10)

    page = await _execute(line.id)

    assert [e["node"]["id"] for e in page["edges"]] == [
        str(newest.id),
        str(middle.id),
        str(oldest.id),
    ]
    assert page["pageInfo"]["hasNextPage"] is False
    node = page["edges"][0]["node"]
    assert node["status"] == "CROWDED"
    assert node["delayMinutes"] == 5
    assert node["user"] == {"nickname": "Owner"}


@pytest.mark.django_db
async def test_keyset_pagination_walks_two_pages_without_gaps():
    user = await _make_user("reports-page", "Pager")
    line = await _make_line("R2")
    reports = [
        await _make_report(line, user, PassengerStatus.NORMAL, minutes_ago=40 - i)
        for i in range(3)
    ]
    expected = [str(r.id) for r in reversed(reports)]

    first_page = await _execute(line.id, first=2)
    assert [e["node"]["id"] for e in first_page["edges"]] == expected[:2]
    assert first_page["pageInfo"]["hasNextPage"] is True
    cursor = first_page["pageInfo"]["endCursor"]
    assert cursor is not None

    second_page = await _execute(line.id, first=2, after=cursor)
    assert [e["node"]["id"] for e in second_page["edges"]] == expected[2:]
    assert second_page["pageInfo"]["hasNextPage"] is False


@pytest.mark.django_db
async def test_reports_filter_to_one_line_only():
    user = await _make_user("reports-two-lines", "Both")
    line = await _make_line("R3")
    other = await _make_line("R4")
    mine = await _make_report(line, user, PassengerStatus.CROWDED, minutes_ago=5)
    await _make_report(other, user, PassengerStatus.DISRUPTED, minutes_ago=5)

    page = await _execute(line.id)

    assert [e["node"]["id"] for e in page["edges"]] == [str(mine.id)]
