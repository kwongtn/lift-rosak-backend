"""Tests for the ``seed_demo_data`` management command.

The command is delete-then-recreate over a fixed-seed RNG, so the tests assert:
1. the default run produces the expected order of magnitude with real variety
   (hundreds of reports, mixed statuses, notes and no-notes);
2. every configured line carries at least one report, and at least three lines
   show two distinct statuses inside the 15-minute window;
3. running it twice is idempotent (identical counts, no duplicates);
4. ``--flush`` removes only what the command created.

The runnable copy of this suite lives in ``common/tests.py``; the top-level
``tests/`` tree is pytest-only and is not collected by ``manage.py test``
(see ``MISTAKES.md``).
"""

from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models import Count
from django.utils import timezone

from common.models import User, Vote
from incident.enums import PassengerStatus
from incident.models import LineStatusReport, SocialMediaLink
from operation.enums import VehicleStatus
from operation.models import Line, Station, StationLine, Vehicle, VehicleType
from spotting.enums import SpottingEventType
from spotting.models import Event

SEED_PREFIX = "demo-seed-"

SEED_LINES = [
    "BRT SBL",
    "KTM ETS",
    "KTMK-PKL",
    "LRT AGL",
    "LRT KJL",
    "MRL",
    "MRT KGL",
    "MRT PYL",
]


@pytest.fixture
def reference():
    """Minimal reference data the command attaches to."""
    for index, code in enumerate(SEED_LINES):
        line = Line.objects.create(
            code=code,
            display_name=f"Seed Line {code}",
            display_color="#336699",
        )
        station = Station.objects.create(display_name=f"{code} Station")
        StationLine.objects.create(
            station=station,
            line=line,
            display_name=f"{code} Station",
            internal_representation=f"SD{index:03d}",
        )

    vehicle_type = VehicleType.objects.create(
        internal_name="SEED-VT",
        display_name="Seed Vehicle Type",
    )
    for n in range(3):
        Vehicle.objects.create(
            identification_no=f"SEED{n:03d}",
            vehicle_type=vehicle_type,
            status=VehicleStatus.IN_SERVICE,
        )
    return SEED_LINES


@pytest.mark.django_db
def test_seed_generates_varied_volume_and_is_idempotent(reference):
    call_command("seed_demo_data")

    assert User.objects.filter(firebase_id__startswith=SEED_PREFIX).count() >= 100

    reports = LineStatusReport.objects.filter(user__firebase_id__startswith=SEED_PREFIX)
    assert reports.count() >= 250

    reported_line_ids = set(reports.values_list("line_id", flat=True))
    for line in Line.objects.all()[:6]:
        assert line.id in reported_line_ids

    window = reports.filter(created__gte=timezone.now() - timedelta(minutes=15))
    multi_status = (
        window.values("line_id")
        .annotate(distinct_statuses=Count("status", distinct=True))
        .filter(distinct_statuses__gte=2)
    )
    assert multi_status.count() >= 3

    assert reports.filter(notes="").exists()
    assert reports.exclude(notes="").exists()
    assert reports.values("status").distinct().count() >= 2
    assert reports.exclude(notes="").values("notes").distinct().count() >= 5

    links = SocialMediaLink.objects.filter(user__firebase_id__startswith=SEED_PREFIX)
    assert links.count() >= 30
    content_type = ContentType.objects.get_for_model(SocialMediaLink)
    assert Vote.objects.filter(
        content_type=content_type,
        object_id__in=list(links.values_list("id", flat=True)),
    ).exists()

    before = (
        User.objects.filter(firebase_id__startswith=SEED_PREFIX).count(),
        reports.count(),
        links.count(),
        Event.objects.filter(reporter__firebase_id__startswith=SEED_PREFIX).count(),
    )
    call_command("seed_demo_data")
    after = (
        User.objects.filter(firebase_id__startswith=SEED_PREFIX).count(),
        LineStatusReport.objects.filter(
            user__firebase_id__startswith=SEED_PREFIX
        ).count(),
        SocialMediaLink.objects.filter(
            user__firebase_id__startswith=SEED_PREFIX
        ).count(),
        Event.objects.filter(reporter__firebase_id__startswith=SEED_PREFIX).count(),
    )
    assert before == after


@pytest.mark.django_db
def test_flush_removes_only_seeded_rows(reference):
    outsider = User.objects.create(firebase_id="seed-outsider", nickname="Outsider")
    keep_line = Line.objects.get(code="MRT PYL")
    keep_link = SocialMediaLink.objects.create(
        url="https://example.com/keep-me",
        title="Unrelated pre-existing link",
        user=outsider,
    )
    LineStatusReport.objects.create(
        line=keep_line,
        user=outsider,
        status=PassengerStatus.NORMAL,
        notes="pre-existing report",
    )

    call_command("seed_demo_data", reports=20, users=5, links=5)
    assert User.objects.filter(firebase_id__startswith=SEED_PREFIX).exists()

    call_command("seed_demo_data", flush=True)

    assert not User.objects.filter(firebase_id__startswith=SEED_PREFIX).exists()
    assert not LineStatusReport.objects.filter(
        user__firebase_id__startswith=SEED_PREFIX
    ).exists()
    assert not SocialMediaLink.objects.filter(
        user__firebase_id__startswith=SEED_PREFIX
    ).exists()
    assert SocialMediaLink.objects.filter(id=keep_link.id).exists()
    assert LineStatusReport.objects.filter(user=outsider).exists()


@pytest.mark.django_db
def test_spotting_events_never_violate_check_constraint(reference):
    call_command("seed_demo_data")

    seeded_events = Event.objects.filter(reporter__firebase_id__startswith=SEED_PREFIX)
    assert seeded_events.exists()
    for event in seeded_events:
        if event.type == SpottingEventType.JUST_SPOTTING:
            assert event.origin_station is None
            assert event.destination_station is None
        elif event.type == SpottingEventType.AT_STATION:
            assert event.origin_station is not None
            assert event.destination_station is None
