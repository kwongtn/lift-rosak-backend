"""Pure-function tests for hourly bucketing of line status reports (no DB)."""

from datetime import datetime, timedelta, timezone

from incident.enums import PassengerStatus
from incident.services.line_status import (
    HOURS_IN_SERVICE_DAY,
    ReportEntry,
    bucket_hourly,
)

DAY_START = datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 2, 5, 30, tzinfo=timezone.utc)
HOUR_STARTS = [
    DAY_START + timedelta(hours=offset) for offset in range(HOURS_IN_SERVICE_DAY)
]


def _entry(status: str, at: datetime) -> ReportEntry:
    return ReportEntry(status=status, created=at)


def test_no_reports_yields_empty_list():
    assert bucket_hourly([], day_start=DAY_START, now=NOW) == []


def test_reports_yield_all_24_hours_of_the_service_day():
    entries = [
        _entry(PassengerStatus.NORMAL, DAY_START + timedelta(minutes=10)),
        _entry(PassengerStatus.CROWDED, DAY_START + timedelta(hours=1, minutes=5)),
        _entry(PassengerStatus.DELAYED, DAY_START + timedelta(hours=2, minutes=29)),
    ]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert [b.hour_start for b in buckets] == HOUR_STARTS
    assert [b.hour_end for b in buckets] == [
        hour + timedelta(hours=1) for hour in HOUR_STARTS
    ]
    assert [b.count for b in buckets] == [1, 1, 1] + [0] * 21
    assert [b.dominant_status for b in buckets] == [
        PassengerStatus.NORMAL,
        PassengerStatus.CROWDED,
        PassengerStatus.DELAYED,
    ] + [None] * 21
    assert [b.status_counts for b in buckets] == [
        {PassengerStatus.NORMAL: 1},
        {PassengerStatus.CROWDED: 1},
        {PassengerStatus.DELAYED: 1},
    ] + [{}] * 21
    # The chart always gets its full 24 labels: 03:00 through 02:00 next morning.
    assert buckets[-1].hour_start == DAY_START + timedelta(hours=23)
    assert buckets[-1].hour_start.hour == 2


def test_report_in_the_final_hour_lands_in_the_last_bucket():
    end_of_day = DAY_START + timedelta(hours=24)
    entries = [
        _entry(PassengerStatus.BACKLOGGED, end_of_day - timedelta(minutes=1)),
    ]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=end_of_day)

    assert len(buckets) == HOURS_IN_SERVICE_DAY
    assert buckets[-1].count == 1
    assert buckets[-1].dominant_status == PassengerStatus.BACKLOGGED


def test_report_before_day_start_is_excluded():
    # 02:30 belongs to the PREVIOUS service day (day starts at 03:00), so this
    # line has no report in the current service day.
    entries = [_entry(PassengerStatus.DISRUPTED, DAY_START - timedelta(minutes=30))]

    assert bucket_hourly(entries, day_start=DAY_START, now=NOW) == []


def test_report_at_exactly_day_start_belongs_to_first_bucket():
    entries = [_entry(PassengerStatus.CROWDED, DAY_START)]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert len(buckets) == HOURS_IN_SERVICE_DAY
    assert buckets[0].count == 1
    assert buckets[0].dominant_status == PassengerStatus.CROWDED


def test_dominant_status_is_the_most_frequent():
    entries = [
        _entry(PassengerStatus.NORMAL, DAY_START + timedelta(minutes=5)),
        _entry(PassengerStatus.NORMAL, DAY_START + timedelta(minutes=15)),
        _entry(PassengerStatus.DELAYED, DAY_START + timedelta(minutes=25)),
    ]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert len(buckets) == HOURS_IN_SERVICE_DAY
    assert buckets[0].count == 3
    assert buckets[0].dominant_status == PassengerStatus.NORMAL
    assert buckets[0].status_counts == {
        PassengerStatus.NORMAL: 2,
        PassengerStatus.DELAYED: 1,
    }
    assert sum(buckets[0].status_counts.values()) == buckets[0].count


def test_dominant_status_tie_breaks_on_severity_rank():
    entries = [
        _entry(PassengerStatus.NORMAL, DAY_START + timedelta(minutes=5)),
        _entry(PassengerStatus.DELAYED, DAY_START + timedelta(minutes=15)),
    ]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert buckets[0].dominant_status == PassengerStatus.DELAYED
    assert buckets[0].status_counts == {
        PassengerStatus.NORMAL: 1,
        PassengerStatus.DELAYED: 1,
    }
    assert buckets[0].count == 2
    assert sum(buckets[0].status_counts.values()) == buckets[0].count
