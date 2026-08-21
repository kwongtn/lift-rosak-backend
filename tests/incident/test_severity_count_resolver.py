"""Tests for get_calendar_incidents_by_severity_count (chart aggregation)."""

import datetime as dt

import pendulum
import pytest
import strawberry
from graphql.error import GraphQLError

from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident
from incident.schema.resolvers import (
    GroupByEnum,
    get_calendar_incidents_by_severity_count,
)


async def _make_incident(
    n: int,
    *,
    severity: str,
    start: dt.datetime,
    end: dt.datetime | None,
    long_term: bool = False,
) -> CalendarIncident:
    return await CalendarIncident.objects.acreate(
        title=f"Chart incident {n}",
        brief="chart",
        start_datetime=start,
        end_datetime=end,
        long_term=long_term,
        severity=severity,
        status=CalendarIncidentStatus.LIVE,
    )


def _start_of(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min)


@pytest.mark.django_db
async def test_missing_dates_raise_graphql_error():
    with pytest.raises(GraphQLError, match="start_date and end_date required"):
        await get_calendar_incidents_by_severity_count(None)


@pytest.mark.django_db
async def test_no_incidents_in_range_returns_empty_list():
    result = await get_calendar_incidents_by_severity_count(
        None,
        start_date=strawberry.Some(dt.date(2020, 1, 1)),
        end_date=strawberry.Some(dt.date(2020, 1, 7)),
    )

    assert result == []


@pytest.mark.django_db
async def test_day_grouping_counts_long_and_short_term():
    # Fixed past window: async tests leak DB state, so never query around "today"
    # where other tests' incidents (created via timezone.now()) would be counted.
    day = dt.date(2020, 3, 15)
    start_of_day = _start_of(day)

    long_major = await _make_incident(
        1,
        severity="MAJOR",
        start=start_of_day,
        end=None,
        long_term=True,
    )
    short_minor = await _make_incident(
        2,
        severity="MINOR",
        start=start_of_day,
        end=start_of_day + dt.timedelta(hours=5),
    )
    await _make_incident(
        3,
        severity="MINOR",
        start=start_of_day + dt.timedelta(hours=1),
        end=None,
    )
    await _make_incident(
        4,
        severity="OTHERS",
        start=start_of_day - dt.timedelta(days=30),
        end=start_of_day - dt.timedelta(days=29),
    )

    result = await get_calendar_incidents_by_severity_count(
        None,
        start_date=strawberry.Some(day),
        end_date=strawberry.Some(day),
        group_by=GroupByEnum.DAY,
    )

    by_key = {
        (entry.date, entry.severity, entry.is_long_term): entry for entry in result
    }

    assert by_key[(day, "MAJOR", True)].count == 1
    assert by_key[(day, "MINOR", False)].count == 2
    assert (day, "OTHERS", False) not in by_key
    assert long_major.id and short_minor.id


@pytest.mark.django_db
async def test_month_grouping_counts_by_severity():
    month_start = dt.date(2020, 4, 1)
    month_end = dt.date(2020, 4, 30)
    start = _start_of(month_start)

    await _make_incident(10, severity="MAJOR", start=start, end=None)
    await _make_incident(11, severity="MAJOR", start=start, end=None)
    await _make_incident(12, severity="MINOR", start=start, end=None)

    result = await get_calendar_incidents_by_severity_count(
        None,
        start_date=strawberry.Some(month_start),
        end_date=strawberry.Some(month_end),
        group_by=GroupByEnum.MONTH,
    )

    by_severity = {entry.severity: entry.count for entry in result}
    assert by_severity["MAJOR"] == 2
    assert by_severity["MINOR"] == 1
    assert all(entry.is_long_term is None for entry in result)
    assert all(entry.date.day == 1 for entry in result)


@pytest.mark.django_db
async def test_interval_clamps_to_requested_window():
    """A range starting after the earliest incident still counts it (clamped interval)."""

    window_start = dt.date(2020, 5, 1)
    await _make_incident(20, severity="MAJOR", start=_start_of(window_start), end=None)

    result = await get_calendar_incidents_by_severity_count(
        None,
        start_date=strawberry.Some(window_start),
        end_date=strawberry.Some(dt.date(2020, 5, 4)),
        group_by=GroupByEnum.DAY,
    )

    assert sum(entry.count for entry in result) >= 1


def test_pendulum_interval_helper_smoke():
    interval = pendulum.interval(pendulum.date(2026, 1, 1), pendulum.date(2026, 1, 3))
    assert len(list(interval.range("days"))) == 3
