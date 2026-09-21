"""Tests for incident.services.feed_links.submit_line_status_report.

A report submitted without a social-media link is standalone (link_id is None).
"""

import pytest
from asgiref.sync import sync_to_async

from common.models import User
from incident import services
from incident.enums import PassengerStatus
from operation.models import Line, Station


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"test-user-lsr-{n}")


async def _make_line(code: str) -> Line:
    return await sync_to_async(Line.objects.create)(
        code=code,
        display_name=f"Status Line {code}",
        display_color="#00AA00",
    )


async def _make_station(name: str) -> Station:
    return await sync_to_async(Station.objects.create)(display_name=name)


@pytest.mark.django_db(transaction=True)
async def test_creates_link_less_report_with_stations():
    user = await _make_user(1)
    line = await _make_line("LSR1")
    station = await _make_station("Status Station 1")

    report = await services.submit_line_status_report(
        user,
        line_id=line.id,
        status=PassengerStatus.BUSY,
        station_ids=[station.id],
        delay_minutes=None,
        notes="packed platform",
    )

    assert report.pk is not None
    assert report.link_id is None
    assert report.line_id == line.id
    assert report.status == PassengerStatus.BUSY
    assert report.notes == "packed platform"
    assert {obj.id async for obj in report.stations.all()} == {station.id}


@pytest.mark.django_db(transaction=True)
async def test_unknown_line_raises_service_error():
    user = await _make_user(2)

    with pytest.raises(services.IncidentServiceError, match="does not exist"):
        await services.submit_line_status_report(
            user,
            line_id=999_999,
            status=PassengerStatus.NORMAL,
            station_ids=[],
            delay_minutes=None,
            notes="",
        )
