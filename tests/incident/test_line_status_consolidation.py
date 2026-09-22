"""Pure-function tests for the line-status consolidation engine (no DB)."""

from datetime import datetime, timedelta, timezone

from incident.enums import PassengerStatus
from incident.services.line_status import (
    SEVERITY_RANK,
    Consolidation,
    ReportEntry,
    consolidate,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _entry(
    status: str, *, minutes_ago: int = 0, link_id: int | None = None
) -> ReportEntry:
    return ReportEntry(
        status=status,
        created=NOW - timedelta(minutes=minutes_ago),
        link_id=link_id,
    )


def test_severity_rank_matches_enum_declaration_order():
    assert SEVERITY_RANK == {
        PassengerStatus.NORMAL: 0,
        PassengerStatus.BUSY: 1,
        PassengerStatus.CROWDED: 2,
        PassengerStatus.EXTREMELY_CROWDED: 3,
        PassengerStatus.BACKLOGGED: 4,
        PassengerStatus.DELAYED: 5,
        PassengerStatus.DISRUPTED: 6,
    }


def test_majority_weight_wins():
    # (a) two NORMAL out-weigh one DELAYED when no votes exist.
    entries = [
        _entry(PassengerStatus.NORMAL, minutes_ago=5),
        _entry(PassengerStatus.NORMAL, minutes_ago=4),
        _entry(PassengerStatus.DELAYED, minutes_ago=3),
    ]

    result = consolidate(entries, {}, now=NOW)

    assert result is not None
    assert result.status == PassengerStatus.NORMAL
    assert result.count == 3


def test_upvotes_amplify_a_report():
    # (b) a CROWDED report with 5 upvotes (weight 6) beats two NORMAL (weight 1 each).
    entries = [
        _entry(PassengerStatus.CROWDED, minutes_ago=3, link_id=10),
        _entry(PassengerStatus.NORMAL, minutes_ago=2),
        _entry(PassengerStatus.NORMAL, minutes_ago=1),
    ]

    result = consolidate(entries, {10: 5}, now=NOW)

    assert result is not None
    assert result.status == PassengerStatus.CROWDED
    assert result.count == 3


def test_zero_vote_linked_report_still_counts():
    # (c) a freshly submitted, zero-vote linked report is not invisible.
    # CROWDED (weight 1) beats NORMAL whose link is heavily downvoted (weight 1);
    # the tie is broken by severity, proving the zero-vote report counted.
    entries = [
        _entry(PassengerStatus.CROWDED, minutes_ago=1, link_id=20),
        _entry(PassengerStatus.NORMAL, minutes_ago=1, link_id=21),
    ]

    result = consolidate(entries, {20: 0, 21: -5}, now=NOW)

    assert result is not None
    assert result.status == PassengerStatus.CROWDED
    assert result.count == 2


def test_linkless_reports_each_weigh_one():
    # (d) two link-less NORMAL (1 + 1) beat one linked DELAYED at weight 1.
    entries = [
        _entry(PassengerStatus.NORMAL, minutes_ago=3),
        _entry(PassengerStatus.NORMAL, minutes_ago=2),
        _entry(PassengerStatus.DELAYED, minutes_ago=1, link_id=30),
    ]

    result = consolidate(entries, {30: 0}, now=NOW)

    assert result is not None
    assert result.status == PassengerStatus.NORMAL
    assert result.count == 3


def test_below_min_reports_returns_none():
    # (e)
    entries = [_entry(PassengerStatus.NORMAL)]

    assert consolidate(entries, {}, now=NOW, min_reports=2) is None


def test_empty_entries_returns_none():
    # (f)
    assert consolidate([], {}, now=NOW) is None


def test_tie_on_weight_most_recent_wins():
    # (g) NORMAL is more recent and wins despite DELAYED's higher severity.
    entries = [
        _entry(PassengerStatus.DELAYED, minutes_ago=10),
        _entry(PassengerStatus.NORMAL, minutes_ago=1),
    ]

    result = consolidate(entries, {}, now=NOW)

    assert result is not None
    assert result.status == PassengerStatus.NORMAL


def test_weight_and_recency_tie_severity_rank_wins():
    # (h) identical weight and identical created -> severity rank breaks it.
    entries = [
        _entry(PassengerStatus.NORMAL, minutes_ago=0),
        _entry(PassengerStatus.DELAYED, minutes_ago=0),
    ]

    result = consolidate(entries, {}, now=NOW)

    assert result is not None
    assert result.status == PassengerStatus.DELAYED


def test_window_excludes_older_report():
    # (i)
    entries = [
        _entry(PassengerStatus.CROWDED, minutes_ago=30),
        _entry(PassengerStatus.NORMAL, minutes_ago=5),
    ]

    result = consolidate(entries, {}, now=NOW)

    assert result is not None
    assert result.status == PassengerStatus.NORMAL
    assert result.count == 1


def test_default_window_is_fifteen_minutes():
    # 14 minutes inside the window, 16 minutes outside.
    inside = _entry(PassengerStatus.NORMAL, minutes_ago=14)
    outside = _entry(PassengerStatus.CROWDED, minutes_ago=16)

    assert consolidate([inside], {}, now=NOW) is not None
    assert consolidate([outside], {}, now=NOW) is None


def test_status_count_counts_only_the_winning_status():
    entries = [
        _entry(PassengerStatus.NORMAL, minutes_ago=5),
        _entry(PassengerStatus.NORMAL, minutes_ago=3),
        _entry(PassengerStatus.DELAYED, minutes_ago=1),
    ]

    result = consolidate(entries, {}, now=NOW)

    assert result is not None
    assert result.status == PassengerStatus.NORMAL
    assert result.count == 3
    assert result.status_count == 2
    assert result.status_counts == {
        PassengerStatus.NORMAL: 2,
        PassengerStatus.DELAYED: 1,
    }


def test_only_old_reports_returns_none():
    # (i, cont.) a report outside the window does not count at all.
    entries = [_entry(PassengerStatus.CROWDED, minutes_ago=30)]

    assert consolidate(entries, {}, now=NOW) is None


def test_message_singular_phrasing():
    # (j)
    result = consolidate([_entry(PassengerStatus.NORMAL)], {}, now=NOW)

    assert result == Consolidation(
        status=PassengerStatus.NORMAL,
        count=1,
        status_count=1,
        status_counts={PassengerStatus.NORMAL: 1},
        message="According to 1 social media entry, this line is Normal.",
    )


def test_message_plural_phrasing_and_label():
    # (j)
    entries = [
        _entry(PassengerStatus.EXTREMELY_CROWDED, minutes_ago=2),
        _entry(PassengerStatus.EXTREMELY_CROWDED, minutes_ago=1),
    ]

    result = consolidate(entries, {}, now=NOW)

    assert result is not None
    assert result.count == 2
    assert (
        result.message
        == "According to 2 social media entries, this line is Extremely Crowded."
    )
