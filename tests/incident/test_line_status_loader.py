"""DB-level tests for load_line_pulses batching contract (backs a DataLoader)."""

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.models import User
from incident.enums import PassengerStatus
from incident.models import LineStatusReport, SocialMediaLink
from incident.services.line_status import load_line_pulses
from operation.models import Line


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"test-user-pulse-{n}")


async def _make_line(code: str) -> Line:
    return await sync_to_async(Line.objects.create)(
        code=code,
        display_name=f"Line {code}",
        display_color="#FF0000",
    )


async def _make_link(user: User, url: str) -> SocialMediaLink:
    return await sync_to_async(SocialMediaLink.objects.create)(url=url, user=user)


async def _make_report(
    line: Line,
    user: User,
    status: str,
    *,
    minutes_ago: int = 0,
    link: SocialMediaLink | None = None,
) -> LineStatusReport:
    report = await sync_to_async(LineStatusReport.objects.create)(
        line=line,
        status=status,
        user=user,
        link=link,
    )
    created = timezone.now() - timedelta(minutes=minutes_ago)
    await sync_to_async(LineStatusReport.objects.filter(pk=report.pk).update)(
        created=created
    )
    report.created = created
    return report


@pytest.mark.django_db
async def test_line_with_report_gets_consolidated_pulse_and_others_are_empty():
    user = await _make_user(1)
    line = await _make_line("P1")
    empty_line = await _make_line("P2")
    await _make_report(line, user, PassengerStatus.CROWDED)

    pulses = await load_line_pulses([line.id, empty_line.id])

    assert set(pulses) == {line.id, empty_line.id}
    assert pulses[line.id].status == PassengerStatus.CROWDED
    assert pulses[line.id].count == 1
    assert pulses[line.id].message == (
        "According to 1 social media entry, this line is Crowded."
    )
    assert pulses[empty_line.id].status is None
    assert pulses[empty_line.id].message is None
    assert pulses[empty_line.id].count == 0
    assert pulses[empty_line.id].links == []


@pytest.mark.django_db
async def test_reports_older_than_window_are_ignored():
    user = await _make_user(2)
    line = await _make_line("P3")
    await _make_report(line, user, PassengerStatus.DISRUPTED, minutes_ago=7 * 60)

    pulses = await load_line_pulses([line.id])

    assert pulses[line.id].status is None
    assert pulses[line.id].count == 0


@pytest.mark.django_db
async def test_pulse_links_are_newest_first_distinct_and_capped_at_five():
    user = await _make_user(3)
    line = await _make_line("P4")
    links = [await _make_link(user, f"https://example.com/pulse-{i}") for i in range(6)]
    # r0 newest; r1 duplicates link[0]; then link[1]..link[5] get older.
    await _make_report(line, user, PassengerStatus.NORMAL, link=links[0])
    await _make_report(line, user, PassengerStatus.NORMAL, minutes_ago=1, link=links[0])
    for i in range(1, 6):
        await _make_report(
            line,
            user,
            PassengerStatus.NORMAL,
            minutes_ago=i + 1,
            link=links[i],
        )

    pulses = await load_line_pulses([line.id])

    assert pulses[line.id].count == 7
    assert [link.id for link in pulses[line.id].links] == [
        link.id for link in links[:5]
    ]
