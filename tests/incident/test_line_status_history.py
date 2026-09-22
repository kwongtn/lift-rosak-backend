"""Service- and schema-level tests for line status history (hourly buckets)."""

import copy
from datetime import timedelta

import pytest
import strawberry
from asgiref.sync import async_to_sync, sync_to_async
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from dotmap import DotMap

from common.models import User
from incident.enums import PassengerStatus
from incident.models import LineStatusReport
from incident.schema.loaders import IncidentContextLoaders
from incident.services.errors import IncidentServiceError
from incident.services.line_status import load_line_status_history
from operation.models import Line

# Fixed "now" so buckets are deterministic regardless of wall clock.
NOW = timezone.now().replace(hour=5, minute=30, second=0, microsecond=0)
DAY_START = NOW.replace(hour=3, minute=0, second=0, microsecond=0)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"history-user-{n}")


async def _make_line(code: str) -> Line:
    return await sync_to_async(Line.objects.create)(
        code=code,
        display_name=f"Line {code}",
        display_color="#FF0000",
    )


async def _make_report(line: Line, user: User, status: str, at) -> LineStatusReport:
    report = await sync_to_async(LineStatusReport.objects.create)(
        line=line, status=status, user=user
    )
    await sync_to_async(LineStatusReport.objects.filter(pk=report.pk).update)(
        created=at
    )
    return report


@pytest.mark.django_db
async def test_history_buckets_include_empty_hours_and_counts():
    user = await _make_user(1)
    line = await _make_line("H1")
    await _make_report(
        line, user, PassengerStatus.CROWDED, DAY_START + timedelta(minutes=30)
    )
    await _make_report(
        line, user, PassengerStatus.CROWDED, DAY_START + timedelta(hours=1, minutes=10)
    )
    await _make_report(
        line, user, PassengerStatus.DELAYED, DAY_START + timedelta(hours=1, minutes=20)
    )

    buckets = await load_line_status_history(line.id, now=NOW)

    assert len(buckets) == 24
    assert [b.hour_start.hour for b in buckets] == list(range(3, 24)) + [0, 1, 2]
    assert [b.count for b in buckets] == [1, 2, 0] + [0] * 21
    assert [b.dominant_status for b in buckets] == [
        PassengerStatus.CROWDED,
        PassengerStatus.DELAYED,
    ] + [None] * 22


@pytest.mark.django_db
async def test_history_only_returns_the_requested_line():
    user = await _make_user(2)
    line = await _make_line("H2")
    other = await _make_line("H3")
    await _make_report(
        line, user, PassengerStatus.NORMAL, DAY_START + timedelta(minutes=5)
    )
    await _make_report(
        other, user, PassengerStatus.DISRUPTED, DAY_START + timedelta(minutes=5)
    )

    buckets = await load_line_status_history(line.id, now=NOW)

    assert len(buckets) == 24
    assert sum(b.count for b in buckets) == 1
    assert buckets[0].dominant_status == PassengerStatus.NORMAL


@pytest.mark.django_db
async def test_line_without_reports_returns_empty_list():
    line = await _make_line("H4")

    buckets = await load_line_status_history(line.id, now=NOW)

    assert buckets == []


@pytest.mark.django_db
async def test_report_before_service_day_start_is_excluded():
    user = await _make_user(3)
    line = await _make_line("H9")
    await _make_report(
        line, user, PassengerStatus.DISRUPTED, DAY_START - timedelta(minutes=30)
    )

    buckets = await load_line_status_history(line.id, now=NOW)

    assert buckets == []


@pytest.mark.django_db
async def test_invalid_day_start_hour_raises_typed_error():
    line = await _make_line("H5")

    with pytest.raises(IncidentServiceError):
        await load_line_status_history(line.id, day_start_hour=24, now=NOW)

    with pytest.raises(IncidentServiceError):
        await load_line_status_history(line.id, day_start_hour=-1, now=NOW)


@pytest.mark.django_db
def test_history_uses_one_query_regardless_of_row_count():
    user = User.objects.create(firebase_id="history-query-user")
    line = Line.objects.create(
        code="H8", display_name="Line H8", display_color="#FF0000"
    )
    for _ in range(5):
        LineStatusReport.objects.create(
            line=line, status=PassengerStatus.NORMAL, user=user
        )

    with CaptureQueriesContext(connection) as captured:
        buckets = async_to_sync(load_line_status_history)(line.id, now=timezone.now())

    assert len(captured.captured_queries) == 1
    assert len(buckets) == 24
    assert sum(b.count for b in buckets) == 5


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


@pytest.mark.django_db
async def test_schema_line_status_history_returns_the_full_service_day():
    user = await _make_user(4)
    line = await _make_line("H6")
    await _make_report(line, user, PassengerStatus.CROWDED, timezone.now())
    # dayStartHour = current hour -> 24 buckets starting at the current hour.
    current_hour = timezone.now().hour

    result = await _build_schema().execute(
        """
        query($id: ID!, $hour: Int!) {
          lineStatusHistory(lineId: $id, dayStartHour: $hour) {
            hourStart
            hourEnd
            count
            dominantStatus
          }
        }
        """,
        variable_values={"id": str(line.id), "hour": current_hour},
        context_value=_context(),
    )

    assert result.errors is None, result.errors
    buckets = result.data["lineStatusHistory"]
    assert len(buckets) == 24
    assert buckets[0]["count"] == 1
    assert buckets[0]["dominantStatus"] == "CROWDED"


@pytest.mark.django_db
async def test_schema_line_status_history_invalid_hour_reports_error():
    line = await _make_line("H7")

    result = await _build_schema().execute(
        """
        query($id: ID!) {
          lineStatusHistory(lineId: $id, dayStartHour: 99) {
            count
          }
        }
        """,
        variable_values={"id": str(line.id)},
        context_value=_context(),
    )

    assert result.errors is not None
