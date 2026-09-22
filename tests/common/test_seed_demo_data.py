"""Tests for the ``seed_demo_data`` management command.

Covers the four contractual behaviours:
1. running it creates the expected demo rows (reports, links, votes, spotting);
2. running it TWICE is idempotent (counts unchanged);
3. ``--flush`` removes only what the command created, leaving unrelated rows;
4. no IntegrityError from the spotting ``Event`` check constraint.

The command attaches to EXISTING reference rows (it never creates lines,
stations, vehicles or vehicle types), so the tests seed a minimal reference set
first — mirroring the dev DB where those rows already exist.
"""

from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db.models import Sum
from django.utils import timezone

from common.management.commands import seed_demo_data as seeder
from common.models import User, Vote
from incident.enums import PassengerStatus, SocialMediaLinkStatus
from incident.models import LineStatusReport, SocialMediaLink
from operation.enums import VehicleStatus
from operation.models import Line, Station, StationLine, Vehicle, VehicleType
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event, LocationEvent

DEMO_FIREBASE_ID = "demo-seed-user"

LINE_CODES = [
    "LRT KJL",
    "MRT KGL",
    "MRT PYL",
    "MRL",
    "BRT SBL",
    "LRT AGL",
    "KTM ETS",
    "KTMK-PKL",
    "LRT SPL",
]

NICKNAMES = ["Vincenture", "Jun", "Chai Wai Lung", "mott", "Scoty"]

EXPECTED_REPORTS = 12
EXPECTED_LINKS = 10
EXPECTED_EVENTS = 12
EXPECTED_LOCATION_EVENTS = 2


@pytest.fixture
def reference(monkeypatch):
    """Minimal reference data the command attaches to, plus the voter ids."""
    lines: dict[str, Line] = {}
    for index, code in enumerate(LINE_CODES):
        lines[code] = Line.objects.create(
            code=code,
            display_name=f"Demo Line {code}",
            display_color="#123456",
        )
        station = Station.objects.create(display_name=f"{code} Central")
        StationLine.objects.create(
            station=station,
            line=lines[code],
            display_name=f"{code} Central",
            internal_representation=f"{code[:3]}{index}",
        )

    vehicle_type = VehicleType.objects.create(
        internal_name="DEMO-VT",
        display_name="Demo Vehicle Type",
    )
    for n in range(4):
        Vehicle.objects.create(
            identification_no=f"DEMO{n:03d}",
            vehicle_type=vehicle_type,
            status=VehicleStatus.IN_SERVICE,
        )

    voter_ids = tuple(
        User.objects.create(firebase_id=f"demo-voter-{n}", nickname=nickname).id
        for n, nickname in enumerate(NICKNAMES)
    )
    monkeypatch.setattr(seeder, "VOTER_IDS", voter_ids)
    return lines


def _demo_user() -> User:
    return User.objects.get(firebase_id=DEMO_FIREBASE_ID)


def _score(link: SocialMediaLink) -> int:
    ct = ContentType.objects.get_for_model(SocialMediaLink)
    total = Vote.objects.filter(content_type=ct, object_id=link.id).aggregate(
        total=Sum("value")
    )["total"]
    return total or 0


@pytest.mark.django_db
def test_seed_creates_expected_rows(reference):
    call_command("seed_demo_data")

    demo = _demo_user()
    assert demo.nickname == "Demo Seed"

    links = SocialMediaLink.objects.filter(user=demo)
    assert links.count() == EXPECTED_LINKS
    assert set(links.values_list("status", flat=True)) == {SocialMediaLinkStatus.LIVE}

    reports = LineStatusReport.objects.filter(user=demo)
    assert reports.count() == EXPECTED_REPORTS

    reported_codes = set(reports.values_list("line__code", flat=True))
    assert reported_codes == {
        "LRT KJL",
        "MRT KGL",
        "MRT PYL",
        "MRL",
        "BRT SBL",
        "LRT AGL",
    }
    assert "LRT SPL" not in reported_codes

    assert Event.objects.filter(reporter=demo).count() == EXPECTED_EVENTS
    assert LocationEvent.objects.filter(event__reporter=demo).count() == (
        EXPECTED_LOCATION_EVENTS
    )

    scores = sorted(_score(link) for link in links)
    assert 5 in scores
    assert 2 in scores
    assert 0 in scores
    assert -1 in scores


@pytest.mark.django_db
def test_report_created_timestamps_are_inside_the_window(reference):
    call_command("seed_demo_data")

    now = timezone.now()
    created = list(
        LineStatusReport.objects.filter(user__firebase_id=DEMO_FIREBASE_ID).values_list(
            "created", flat=True
        )
    )
    assert created
    for when in created:
        assert now - when < timedelta(hours=6)
        assert now - when > timedelta(seconds=-60)
    # auto_now_add would have pinned every row to "now" — prove the update landed.
    assert any(now - when > timedelta(minutes=5) for when in created)


@pytest.mark.django_db
def test_seed_is_idempotent(reference):
    call_command("seed_demo_data")
    call_command("seed_demo_data")

    demo = _demo_user()
    assert SocialMediaLink.objects.filter(user=demo).count() == EXPECTED_LINKS
    assert LineStatusReport.objects.filter(user=demo).count() == EXPECTED_REPORTS
    assert Event.objects.filter(reporter=demo).count() == EXPECTED_EVENTS
    assert LocationEvent.objects.filter(event__reporter=demo).count() == (
        EXPECTED_LOCATION_EVENTS
    )


@pytest.mark.django_db
def test_flush_removes_only_created_rows(reference):
    outsider = User.objects.create(firebase_id="outsider", nickname="Outsider")
    unrelated_line = reference["LRT SPL"]
    unrelated_link = SocialMediaLink.objects.create(
        url="https://example.com/pre-existing",
        title="Unrelated pre-existing link",
        user=outsider,
    )
    unrelated_ct = ContentType.objects.get_for_model(SocialMediaLink)
    Vote.objects.create(
        user=outsider, content_type=unrelated_ct, object_id=unrelated_link.id, value=1
    )
    LineStatusReport.objects.create(
        line=unrelated_line,
        user=outsider,
        status=PassengerStatus.NORMAL,
        notes="pre-existing report",
    )
    vehicle = Vehicle.objects.filter(status=VehicleStatus.IN_SERVICE).first()
    unrelated_event = Event.objects.create(
        spotting_date=timezone.now().date(),
        reporter=outsider,
        vehicle=vehicle,
        status=SpottingVehicleStatus.IN_SERVICE,
        type=SpottingEventType.JUST_SPOTTING,
        notes="pre-existing event",
    )

    call_command("seed_demo_data")
    assert User.objects.filter(firebase_id=DEMO_FIREBASE_ID).exists()
    demo_link_ids = list(
        SocialMediaLink.objects.filter(user__firebase_id=DEMO_FIREBASE_ID).values_list(
            "id", flat=True
        )
    )
    assert demo_link_ids
    assert Vote.objects.filter(
        content_type=unrelated_ct, object_id__in=demo_link_ids
    ).exists()

    call_command("seed_demo_data", flush=True)

    assert not User.objects.filter(firebase_id=DEMO_FIREBASE_ID).exists()
    assert not SocialMediaLink.objects.filter(
        user__firebase_id=DEMO_FIREBASE_ID
    ).exists()
    assert not LineStatusReport.objects.filter(
        user__firebase_id=DEMO_FIREBASE_ID
    ).exists()
    assert not Event.objects.filter(reporter__firebase_id=DEMO_FIREBASE_ID).exists()
    # Votes the command cast on its own links are gone (by content type + object).
    assert not Vote.objects.filter(
        content_type=unrelated_ct, object_id__in=demo_link_ids
    ).exists()

    assert SocialMediaLink.objects.filter(id=unrelated_link.id).exists()
    assert Vote.objects.filter(
        user=outsider, content_type=unrelated_ct, object_id=unrelated_link.id
    ).exists()
    assert LineStatusReport.objects.filter(user=outsider).exists()
    assert Event.objects.filter(id=unrelated_event.id).exists()


@pytest.mark.django_db
def test_spotting_events_never_violate_check_constraint(reference):
    call_command("seed_demo_data")

    demos = Event.objects.filter(reporter__firebase_id=DEMO_FIREBASE_ID)
    assert demos.count() == EXPECTED_EVENTS
    for event in demos:
        if event.type == SpottingEventType.JUST_SPOTTING:
            assert event.origin_station is None
            assert event.destination_station is None
        elif event.type == SpottingEventType.AT_STATION:
            assert event.origin_station is not None
            assert event.destination_station is None
