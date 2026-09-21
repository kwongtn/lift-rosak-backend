"""Model-level tests for LineStatusReport and SocialMediaLink.normalized_url."""

import importlib

import pytest
from django.apps import apps as django_apps

from common.models import User
from incident.enums import PassengerStatus
from incident.models import LineStatusReport, SocialMediaLink
from operation.models import Line

migration_0024 = importlib.import_module(
    "incident.migrations.0024_socialmedialink_normalized_url_linestatusreport"
)


def _make_user(n: int) -> User:
    return User.objects.create(firebase_id=f"test-user-lsr-{n}")


def _make_line(code: str = "1") -> Line:
    return Line.objects.create(
        code=code,
        display_name=f"Line {code}",
        display_color="#FF0000",
    )


def _make_link(user: User, url: str) -> SocialMediaLink:
    return SocialMediaLink.objects.create(url=url, user=user)


@pytest.mark.django_db
def test_line_status_report_creation():
    user = _make_user(1)
    line = _make_line()

    report = LineStatusReport.objects.create(
        line=line,
        status=PassengerStatus.NORMAL,
        user=user,
    )

    assert report.pk is not None
    assert report.status == PassengerStatus.NORMAL
    assert str(report)


@pytest.mark.django_db
def test_line_status_report_link_related_name():
    user = _make_user(2)
    line = _make_line()
    link = _make_link(user, "https://example.com/post")

    report = LineStatusReport.objects.create(
        line=line,
        status=PassengerStatus.DELAYED,
        user=user,
        link=link,
    )

    assert list(link.status_reports.all()) == [report]


@pytest.mark.django_db
def test_social_media_link_save_populates_normalized_url():
    user = _make_user(3)
    link = _make_link(user, "https://Example.com/Path?fbclid=abc")

    assert link.normalized_url == "https://example.com/Path"


@pytest.mark.django_db
def test_tracking_params_share_normalized_url():
    user = _make_user(4)
    first = _make_link(user, "https://example.com/post?utm_source=a")
    second = _make_link(user, "https://example.com/post?fbclid=b")

    assert first.normalized_url == second.normalized_url == "https://example.com/post"


@pytest.mark.django_db
def test_non_http_url_still_saves():
    user = _make_user(5)
    link = _make_link(user, "mailto:test@example.com")

    assert link.pk is not None
    assert link.normalized_url == "mailto:test@example.com"


@pytest.mark.django_db
def test_backfill_populates_normalized_url():
    user = _make_user(6)
    link = _make_link(user, "https://example.com/post?fbclid=x")
    SocialMediaLink.objects.filter(pk=link.pk).update(normalized_url=None)

    migration_0024.backfill_normalized_urls(django_apps, None)

    link.refresh_from_db()
    assert link.normalized_url == "https://example.com/post"
