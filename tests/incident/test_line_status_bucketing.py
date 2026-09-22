"""Pure-function tests for hourly bucketing of line status reports (no DB)."""

from datetime import datetime, timedelta, timezone

from incident.enums import PassengerStatus
from incident.services.line_status import ReportEntry, bucket_hourly

DAY_START = datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 2, 5, 30, tzinfo=timezone.utc)


def _entry(status: str, at: datetime) -> ReportEntry:
    return ReportEntry(status=status, created=at)


def test_empty_buckets_span_day_start_to_current_hour_inclusive():
    buckets = bucket_hourly([], day_start=DAY_START, now=NOW)

    assert [b.hour_start for b in buckets] == [
        DAY_START,
        DAY_START + timedelta(hours=1),
        DAY_START + timedelta(hours=2),
    ]
    assert [b.hour_end for b in buckets] == [
        DAY_START + timedelta(hours=1),
        DAY_START + timedelta(hours=2),
        DAY_START + timedelta(hours=3),
    ]
    assert [b.count for b in buckets] == [0, 0, 0]
    assert [b.dominant_status for b in buckets] == [None, None, None]


def test_entries_land_in_their_hour_bucket():
    entries = [
        _entry(PassengerStatus.NORMAL, DAY_START + timedelta(minutes=10)),
        _entry(PassengerStatus.CROWDED, DAY_START + timedelta(hours=1, minutes=5)),
        _entry(PassengerStatus.DELAYED, DAY_START + timedelta(hours=2, minutes=29)),
    ]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert [b.count for b in buckets] == [1, 1, 1]
    assert [b.dominant_status for b in buckets] == [
        PassengerStatus.NORMAL,
        PassengerStatus.CROWDED,
        PassengerStatus.DELAYED,
    ]


def test_report_before_day_start_is_excluded():
    # 02:30 belongs to the PREVIOUS service day (day starts at 03:00).
    entries = [_entry(PassengerStatus.DISRUPTED, DAY_START - timedelta(minutes=30))]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert [b.count for b in buckets] == [0, 0, 0]


def test_report_at_exactly_day_start_belongs_to_first_bucket():
    entries = [_entry(PassengerStatus.CROWDED, DAY_START)]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert buckets[0].count == 1
    assert buckets[0].dominant_status == PassengerStatus.CROWDED


def test_dominant_status_is_the_most_frequent():
    entries = [
        _entry(PassengerStatus.NORMAL, DAY_START + timedelta(minutes=5)),
        _entry(PassengerStatus.NORMAL, DAY_START + timedelta(minutes=15)),
        _entry(PassengerStatus.DELAYED, DAY_START + timedelta(minutes=25)),
    ]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert buckets[0].count == 3
    assert buckets[0].dominant_status == PassengerStatus.NORMAL


def test_dominant_status_tie_breaks_on_severity_rank():
    entries = [
        _entry(PassengerStatus.NORMAL, DAY_START + timedelta(minutes=5)),
        _entry(PassengerStatus.DELAYED, DAY_START + timedelta(minutes=15)),
    ]

    buckets = bucket_hourly(entries, day_start=DAY_START, now=NOW)

    assert buckets[0].dominant_status == PassengerStatus.DELAYED
