"""Tests for incident.services.feed_links.submit_feed_link.

The dedup key is the canonical URL. A duplicate submission must (a) return the
existing row with an indicator, (b) upsert exactly one upvote for the submitter,
and (c) not create a second row — even when the duplicate is re-submitted.

``transaction=True`` is deliberate: with the default wrapping, DB writes made
via ``sync_to_async`` land on another connection and are not rolled back, so
rows would leak between tests in this async suite. Counts are additionally
scoped to each test's own canonical URL.
"""

import pytest
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType

from common.models import User, Vote
from incident import services
from incident.enums import PassengerStatus, SocialMediaLinkStatus
from incident.models import LineStatusReport, SocialMediaLink
from incident.services import feed_links
from operation.models import Line, Station


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"test-user-feed-{n}")


async def _make_line(code: str) -> Line:
    return await sync_to_async(Line.objects.create)(
        code=code,
        display_name=f"Feed Line {code}",
        display_color="#FF0000",
    )


async def _make_station(name: str) -> Station:
    return await sync_to_async(Station.objects.create)(display_name=name)


async def _link_count_for(canonical_url: str) -> int:
    return await SocialMediaLink.objects.filter(normalized_url=canonical_url).acount()


async def _votes_for(user: User, link: SocialMediaLink) -> list[Vote]:
    content_type = await sync_to_async(ContentType.objects.get_for_model)(
        SocialMediaLink
    )
    return [
        vote
        async for vote in Vote.objects.filter(
            user=user, content_type=content_type, object_id=link.id
        )
    ]


@pytest.mark.django_db(transaction=True)
async def test_new_submit_creates_live_link_with_associations():
    user = await _make_user(1)
    line = await _make_line("FEED1")
    station = await _make_station("Feed Station 1")

    result = await services.submit_feed_link(
        user,
        url="https://example.com/feednew?utm_source=twitter",
        title="A post",
        line_ids=[line.id],
        station_ids=[station.id],
        status=None,
        delay_minutes=None,
        notes="",
    )

    assert result.is_duplicate is False
    assert result.duplicate_of_id is None
    assert result.user_vote == 0
    assert result.link.status == SocialMediaLinkStatus.LIVE
    assert result.link.normalized_url == "https://example.com/feednew"
    assert {obj.id async for obj in result.link.lines.all()} == {line.id}
    assert {obj.id async for obj in result.link.stations.all()} == {station.id}
    assert await _link_count_for("https://example.com/feednew") == 1


@pytest.mark.django_db(transaction=True)
async def test_blank_title_fetches_page_title(monkeypatch):
    user = await _make_user(2)
    calls: list[str] = []

    async def fake_fetch(url: str, **kwargs) -> str:
        calls.append(url)
        return "Fetched title"

    monkeypatch.setattr(feed_links, "fetch_page_title", fake_fetch)

    result = await services.submit_feed_link(
        user,
        url="https://example.com/feedblank",
        title="   ",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )

    assert calls == ["https://example.com/feedblank"]
    assert result.link.title == "Fetched title"


@pytest.mark.django_db(transaction=True)
async def test_supplied_title_skips_fetch(monkeypatch):
    user = await _make_user(3)

    async def fake_fetch(url: str, **kwargs) -> str:
        raise AssertionError("fetch_page_title must not run when a title is given")

    monkeypatch.setattr(feed_links, "fetch_page_title", fake_fetch)

    result = await services.submit_feed_link(
        user,
        url="https://example.com/feedgiven",
        title="Given title",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )

    assert result.link.title == "Given title"


@pytest.mark.django_db(transaction=True)
async def test_duplicate_by_tracking_params_dedups_and_upvotes():
    user = await _make_user(4)

    first = await services.submit_feed_link(
        user,
        url="https://example.com/feeddup",
        title="First",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )

    second = await services.submit_feed_link(
        user,
        url="https://example.com/feeddup/?fbclid=abc&utm_source=x#frag",
        title="Second",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )

    assert second.is_duplicate is True
    assert second.duplicate_of_id == first.link.id
    assert second.link.id == first.link.id
    assert second.user_vote == 1
    assert await _link_count_for("https://example.com/feeddup") == 1

    votes = await _votes_for(user, first.link)
    assert len(votes) == 1
    assert votes[0].value == 1


@pytest.mark.django_db(transaction=True)
async def test_resubmitting_same_duplicate_keeps_one_vote():
    user = await _make_user(5)

    first = await services.submit_feed_link(
        user,
        url="https://example.com/feedidem",
        title="First",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )
    await services.submit_feed_link(
        user,
        url="https://example.com/feedidem?utm_source=a",
        title="Second",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )
    await services.submit_feed_link(
        user,
        url="https://example.com/feedidem/?fbclid=b",
        title="Third",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )

    assert await _link_count_for("https://example.com/feedidem") == 1
    votes = await _votes_for(user, first.link)
    assert len(votes) == 1
    assert votes[0].value == 1


@pytest.mark.django_db(transaction=True)
async def test_different_canonical_urls_create_two_rows():
    user = await _make_user(6)

    first = await services.submit_feed_link(
        user,
        url="https://example.com/feedalpha",
        title="A",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )
    second = await services.submit_feed_link(
        user,
        url="https://example.com/feedbeta",
        title="B",
        line_ids=[],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )

    assert first.link.id != second.link.id
    assert second.is_duplicate is False
    assert await _link_count_for("https://example.com/feedalpha") == 1
    assert await _link_count_for("https://example.com/feedbeta") == 1


@pytest.mark.django_db(transaction=True)
async def test_status_without_lines_raises_validation_error():
    user = await _make_user(7)

    with pytest.raises(services.FeedLinkValidationError):
        await services.submit_feed_link(
            user,
            url="https://example.com/feednoline",
            title="Status only",
            line_ids=[],
            station_ids=[],
            status=PassengerStatus.DELAYED,
            delay_minutes=5,
            notes="",
        )


@pytest.mark.django_db(transaction=True)
async def test_status_with_lines_attaches_report():
    user = await _make_user(8)
    line = await _make_line("FEED8")

    result = await services.submit_feed_link(
        user,
        url="https://example.com/feedstatus",
        title="Delayed",
        line_ids=[line.id],
        station_ids=[],
        status=PassengerStatus.DELAYED,
        delay_minutes=5,
        notes="signal fault",
    )

    report = await LineStatusReport.objects.aget(link=result.link)
    assert report.line_id == line.id
    assert report.status == PassengerStatus.DELAYED
    assert report.delay_minutes == 5
    assert report.notes == "signal fault"


@pytest.mark.django_db(transaction=True)
async def test_duplicate_with_status_attaches_report_to_existing():
    user = await _make_user(9)
    line = await _make_line("FEED9")

    first = await services.submit_feed_link(
        user,
        url="https://example.com/feeddupstatus",
        title="First",
        line_ids=[line.id],
        station_ids=[],
        status=None,
        delay_minutes=None,
        notes="",
    )
    second = await services.submit_feed_link(
        user,
        url="https://example.com/feeddupstatus?utm_source=a",
        title="Second",
        line_ids=[line.id],
        station_ids=[],
        status=PassengerStatus.CROWDED,
        delay_minutes=None,
        notes="",
    )

    assert second.is_duplicate is True
    report = await LineStatusReport.objects.aget(link=first.link)
    assert report.status == PassengerStatus.CROWDED
    assert report.user_id == user.id
