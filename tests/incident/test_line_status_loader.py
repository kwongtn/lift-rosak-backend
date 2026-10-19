"""DB-level tests for load_line_pulses batching contract (backs a DataLoader)."""

from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
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
    assert pulses[line.id].status_count == 1
    assert pulses[line.id].window_minutes == 15
    assert pulses[line.id].message == (
        "According to 1 social media entry, this line is Crowded."
    )
    assert pulses[empty_line.id].status is None
    assert pulses[empty_line.id].message is None
    assert pulses[empty_line.id].count == 0
    assert pulses[empty_line.id].status_count == 0
    assert pulses[empty_line.id].window_minutes == 15
    assert pulses[empty_line.id].links == []


@pytest.mark.django_db
async def test_reports_older_than_window_are_ignored():
    user = await _make_user(2)
    line = await _make_line("P3")
    await _make_report(line, user, PassengerStatus.DISRUPTED, minutes_ago=20)

    pulses = await load_line_pulses([line.id])

    assert pulses[line.id].status is None
    assert pulses[line.id].count == 0
    assert pulses[line.id].status_count == 0


@pytest.mark.django_db
async def test_status_count_only_counts_the_consolidated_status():
    user = await _make_user(4)
    line = await _make_line("P5")
    await _make_report(line, user, PassengerStatus.NORMAL, minutes_ago=5)
    await _make_report(line, user, PassengerStatus.NORMAL, minutes_ago=3)
    await _make_report(line, user, PassengerStatus.DELAYED, minutes_ago=1)

    pulses = await load_line_pulses([line.id])

    assert pulses[line.id].status == PassengerStatus.NORMAL
    assert pulses[line.id].count == 3
    assert pulses[line.id].status_count == 2


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
    assert pulses[line.id].status_count == 7
    assert [link.id for link in pulses[line.id].links] == [
        link.id for link in links[:5]
    ]


@pytest.mark.django_db
def test_pulse_links_query_count_does_not_scale_with_link_count():
    user = User.objects.create(firebase_id="pulse-link-n1-user")
    # Warm the ContentType cache so the counts reflect only the pulse reads.
    ContentType.objects.get_for_model(SocialMediaLink)

    def _lines_with_links(tag: str, links_per_line: int) -> list[Line]:
        lines = []
        for i in range(3):
            line = Line.objects.create(
                code=f"{tag}{i}", display_name=f"{tag}{i}", display_color="#FF0000"
            )
            for j in range(links_per_line):
                link = SocialMediaLink.objects.create(
                    url=f"https://example.com/pulse-n1-{tag}-{i}-{j}", user=user
                )
                link.lines.add(line)
                LineStatusReport.objects.create(
                    line=line,
                    status=PassengerStatus.NORMAL,
                    user=user,
                    link=link,
                )
            lines.append(line)
        return lines

    def _load(lines: list[Line]):
        with CaptureQueriesContext(connection) as captured:
            pulses = async_to_sync(load_line_pulses)([line.id for line in lines])
        return pulses, len(captured.captured_queries)

    one_link_lines = _lines_with_links("S", 1)
    five_link_lines = _lines_with_links("L", 5)

    one_pulses, one_link_queries = _load(one_link_lines)
    five_pulses, five_link_queries = _load(five_link_lines)

    assert one_link_queries == five_link_queries
    links = [link for pulse in five_pulses.values() for link in pulse.links]
    assert len(links) == 15
    # Touching the relations the GraphQL type exposes must not query per link.
    with CaptureQueriesContext(connection) as touched:
        for link in links:
            assert link.user.id == user.id
            assert len(link.lines.all()) == 1
    assert touched.captured_queries == []
