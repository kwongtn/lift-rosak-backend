"""Seed realistic demo data for the community front page.

Idempotent: running it repeatedly reuses the same rows, keyed on stable natural
identifiers (URL + user for links, line/user/status/notes for reports,
reporter/vehicle/date/type for spotting events, user/content/object for votes).

It attaches to the EXISTING reference data (lines, stations, vehicles) and never
creates any of them. ``--flush`` removes only the rows this command owns.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from common.models import User, Vote
from incident.enums import PassengerStatus, SocialMediaLinkStatus
from incident.models import LineStatusReport, SocialMediaLink
from operation.enums import VehicleStatus
from operation.models import Line, Station, Vehicle
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event, LocationEvent

DEMO_FIREBASE_ID = "demo-seed-user"
DEMO_NICKNAME = "Demo Seed"

# Platform identities with real nicknames so the UI shows names, not ids.
VOTER_IDS = (1, 7, 75, 80, 85)

# Front-page line pulses. Ordered; --lines N takes the first N entries.
# (status, minutes_ago, delay_minutes, notes, attach_station)
REPORT_PLAN: list[tuple[str, list[tuple[Any, int, int | None, str, bool]]]] = [
    (
        "LRT KJL",
        [
            (
                PassengerStatus.EXTREMELY_CROWDED,
                18,
                None,
                "Train packed at Masjid Jamek, no space to board",
                True,
            ),
            (
                PassengerStatus.EXTREMELY_CROWDED,
                47,
                None,
                "Standing room only from KLCC to Gombak",
                False,
            ),
            (
                PassengerStatus.EXTREMELY_CROWDED,
                96,
                None,
                "Evening peak crush load at KL Sentral",
                True,
            ),
        ],
    ),
    (
        "MRT KGL",
        [
            (
                PassengerStatus.CROWDED,
                12,
                None,
                "Platform filling up at Pasar Seni",
                True,
            ),
            (
                PassengerStatus.CROWDED,
                53,
                None,
                "Packed but trains arriving every four minutes",
                False,
            ),
            (
                PassengerStatus.BUSY,
                104,
                None,
                "Steady stream of commuters at Bukit Bintang",
                False,
            ),
        ],
    ),
    (
        "MRT PYL",
        [
            (
                PassengerStatus.DELAYED,
                22,
                12,
                "Signal fault causing 10-15 minute delays",
                True,
            ),
            (
                PassengerStatus.DELAYED,
                78,
                8,
                "Trains held at Kwasa Damansara",
                False,
            ),
        ],
    ),
    (
        "MRL",
        [
            (
                PassengerStatus.BACKLOGGED,
                33,
                20,
                "Single-track section backing up at Tun Razak Exchange",
                True,
            ),
        ],
    ),
    (
        "BRT SBL",
        [
            (
                PassengerStatus.NORMAL,
                41,
                None,
                "Buses running smoothly with plenty of seats",
                False,
            ),
        ],
    ),
    (
        "LRT AGL",
        [
            (
                PassengerStatus.DISRUPTED,
                9,
                None,
                "Service suspended between Chan Sow Lin and Masjid Jamek",
                True,
            ),
            (
                PassengerStatus.DISRUPTED,
                66,
                None,
                "Replacement buses struggling to cope with demand",
                False,
            ),
        ],
    ),
]

# ~10 LIVE feed rows. Tracking junk on two of them exercises canonicalisation.
LINK_PLAN: list[dict[str, Any]] = [
    {
        "url": (
            "https://www.facebook.com/groups/komuter/posts/1015987654321/"
            "?fbclid=IwAR0demotrackingjunk"
        ),
        "title": "KTM Komuter delays at KL Sentral this morning",
        "lines": ["KTMK-PKL", "KTMK-SRL"],
        "stations": True,
    },
    {
        "url": (
            "https://x.com/mlptf_my/status/1790000000000000001?s=20&utm_source=demo"
        ),
        "title": "MRT Putrajaya Line signal fault — trains held",
        "lines": ["MRT PYL"],
        "stations": True,
    },
    {
        "url": (
            "https://www.reddit.com/r/malaysia/comments/1demo01/"
            "lrt_kelana_jaya_morning_rush/"
        ),
        "title": "LRT Kelana Jaya is absolutely packed today",
        "lines": ["LRT KJL"],
    },
    {
        "url": (
            "https://www.thestar.com.my/news/nation/2026/09/22/mrt-kajang-crowd-control"
        ),
        "title": "Crowd control at MRT Kajang Line stations during peak hour",
        "lines": ["MRT KGL"],
        "vehicles": True,
    },
    {
        "url": (
            "https://www.malaymail.com/news/malaysia/2026/09/22/"
            "brt-sunway-line-adds-buses/123456"
        ),
        "title": "BRT Sunway Line adds buses to cope with commuter demand",
        "lines": ["BRT SBL"],
    },
    {
        "url": "https://paultan.org/2026/09/22/ampang-lrt-line-disruption/",
        "title": "Ampang LRT line disruption enters its second day",
        "lines": ["LRT AGL"],
        "stations": True,
    },
    {
        "url": "https://www.facebook.com/groups/rapidkl/posts/202600001/",
        "title": "Rapid KL responds to Ampang Line commuter complaints",
        "lines": ["LRT AGL"],
    },
    {
        "url": (
            "https://www.reddit.com/r/malaysia/comments/1demo02/"
            "monorail_backlog_tun_razak_exchange/"
        ),
        "title": "Monorail backlog at Tun Razak Exchange station",
        "lines": ["MRL"],
    },
    {
        "url": "https://x.com/ktmkomuter/status/1790000000000000002",
        "title": "KTM ETS on time today with a smooth journey to Ipoh",
        "lines": ["KTM ETS"],
        "vehicles": True,
    },
    {
        "url": (
            "https://www.thestar.com.my/metro/metro-news/2026/09/22/"
            "mrt-putrajaya-back-to-normal"
        ),
        "title": "MRT Putrajaya Line back to normal after overnight repairs",
        "lines": ["MRT PYL"],
    },
]

# Vote plan keyed by LINK_PLAN index. Tuples are (voter_slot, value): slots
# 0..4 map to the nickname users ordered by id, and -1 is the demo marker user.
# Yields scores: +5, +2, 0, -1 among others.
VOTE_PLAN: dict[int, list[tuple[int, int]]] = {
    0: [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1)],
    1: [(0, 1), (1, 1)],
    2: [(3, 1), (4, -1)],
    3: [(2, -1)],
    4: [(0, 1)],
    5: [(1, 1), (2, 1), (3, 1)],
    6: [(4, -1)],
    7: [(0, 1), (3, -1)],
    8: [(-1, 1)],
    9: [(1, 1), (2, 1)],
}

# (line_code, type, days_ago, notes, coords)
SPOTTING_PLAN: list[tuple[str, Any, int, str, tuple[float, float] | None]] = [
    (
        "LRT KJL",
        SpottingEventType.JUST_SPOTTING,
        0,
        "Spotted leaving KLCC heading towards Gombak",
        (101.7120, 3.1590),
    ),
    (
        "MRT KGL",
        SpottingEventType.JUST_SPOTTING,
        0,
        "Spotted at Bukit Bintang during morning peak",
        None,
    ),
    (
        "MRT PYL",
        SpottingEventType.JUST_SPOTTING,
        1,
        "Spotted approaching Pasar Seni",
        (101.6869, 3.1390),
    ),
    ("MRL", SpottingEventType.JUST_SPOTTING, 1, "Spotted at Tun Razak Exchange", None),
    (
        "BRT SBL",
        SpottingEventType.JUST_SPOTTING,
        2,
        "Spotted on the Sunway elevated busway",
        None,
    ),
    (
        "LRT AGL",
        SpottingEventType.JUST_SPOTTING,
        2,
        "Spotted near Chan Sow Lin depot",
        None,
    ),
    (
        "KTM ETS",
        SpottingEventType.JUST_SPOTTING,
        3,
        "Spotted passing Batang Kali on the way north",
        None,
    ),
    (
        "KTMK-PKL",
        SpottingEventType.JUST_SPOTTING,
        3,
        "Spotted at Subang Jaya heading to Port Klang",
        None,
    ),
    (
        "LRT KJL",
        SpottingEventType.JUST_SPOTTING,
        4,
        "Spotted at Bangsar in the evening",
        None,
    ),
    ("MRT KGL", SpottingEventType.JUST_SPOTTING, 5, "Spotted at Maluri station", None),
    (
        "LRT AGL",
        SpottingEventType.AT_STATION,
        2,
        "At the Ampang Line platform, Sentul Timur",
        None,
    ),
    (
        "LRT KJL",
        SpottingEventType.AT_STATION,
        6,
        "At KLCC platform, waiting for departure",
        None,
    ),
]


class Command(BaseCommand):
    help = "Seed (idempotently) realistic demo data for the community front page."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete only the rows this command created, then exit.",
        )
        parser.add_argument(
            "--lines",
            type=int,
            default=6,
            help="How many configured lines to give status reports (default 6).",
        )

    def handle(self, *args: Any, **options: Any):
        if options["flush"]:
            self._flush()
            return

        lines_by_code = {line.code: line for line in Line.objects.all()}
        existing_codes = sorted(lines_by_code)
        if not existing_codes:
            self.stdout.write(
                self.style.WARNING("No Lines found — nothing to attach demo data to.")
            )
            return

        with transaction.atomic():
            demo_user = self._get_demo_user()
            counts = {
                "links": self._seed_links(demo_user, lines_by_code),
                "reports": self._seed_reports(
                    demo_user, lines_by_code, options["lines"]
                ),
                "events": self._seed_spotting(demo_user, lines_by_code),
            }
            votes = self._seed_votes(demo_user)

        summary = (
            "seed_demo_data complete: "
            f"links {counts['links']['created']} created / "
            f"{counts['links']['reused']} reused, "
            f"reports {counts['reports']['created']} created / "
            f"{counts['reports']['reused']} reused, "
            f"spotting events {counts['events']['created']} created / "
            f"{counts['events']['reused']} reused, "
            f"votes {votes['created']} cast / {votes['reused']} updated."
        )
        self.stdout.write(self.style.SUCCESS(summary))

    def _get_demo_user(self) -> User:
        user, _ = User.objects.get_or_create(
            firebase_id=DEMO_FIREBASE_ID,
            defaults={"nickname": DEMO_NICKNAME},
        )
        return user

    def _seed_links(self, demo_user: User, lines_by_code: dict[str, Line]) -> dict:
        created = reused = 0
        for spec in LINK_PLAN:
            link, was_created = SocialMediaLink.objects.update_or_create(
                url=spec["url"],
                user=demo_user,
                defaults={
                    "title": spec["title"],
                    "status": SocialMediaLinkStatus.LIVE,
                },
            )
            if was_created:
                created += 1
            else:
                reused += 1

            link_lines = [
                lines_by_code[code]
                for code in spec.get("lines", [])
                if code in lines_by_code
            ]
            link.lines.set(link_lines)
            if spec.get("stations") and link_lines:
                link.stations.set(
                    list(Station.objects.filter(lines__in=link_lines).distinct()[:3])
                )
            if spec.get("vehicles") and link_lines:
                link.vehicles.set(
                    list(Vehicle.objects.filter(lines__in=link_lines).distinct()[:3])
                )
        return {"created": created, "reused": reused}

    def _seed_reports(
        self, demo_user: User, lines_by_code: dict[str, Line], limit: int
    ) -> dict:
        created = reused = 0
        now = timezone.now()
        for code, specs in REPORT_PLAN[: max(limit, 0)]:
            line = lines_by_code.get(code)
            if line is None:
                continue
            line_stations = list(Station.objects.filter(lines=line)[:2])
            for status, minutes_ago, delay, notes, attach_station in specs:
                report, was_created = LineStatusReport.objects.update_or_create(
                    line=line,
                    user=demo_user,
                    status=status,
                    notes=notes,
                    defaults={"delay_minutes": delay},
                )
                # `created` is auto_now_add; a queryset update bypasses it so the
                # report lands inside the 6-hour consolidation window.
                LineStatusReport.objects.filter(pk=report.pk).update(
                    created=now - timedelta(minutes=minutes_ago)
                )
                if attach_station and line_stations:
                    report.stations.set(line_stations)
                if was_created:
                    created += 1
                else:
                    reused += 1
        return {"created": created, "reused": reused}

    def _seed_votes(self, demo_user: User) -> dict:
        content_type = ContentType.objects.get_for_model(SocialMediaLink)
        voters = list(User.objects.filter(id__in=VOTER_IDS).order_by("id"))

        links = list(SocialMediaLink.objects.filter(user=demo_user).order_by("id"))
        created = reused = 0
        for index, votes in VOTE_PLAN.items():
            if index >= len(links):
                continue
            link = links[index]
            for slot, value in votes:
                if slot == -1:
                    voter = demo_user
                elif 0 <= slot < len(voters):
                    voter = voters[slot]
                else:
                    continue
                _, was_created = Vote.objects.update_or_create(
                    user=voter,
                    content_type=content_type,
                    object_id=link.id,
                    defaults={"value": value},
                )
                if was_created:
                    created += 1
                else:
                    reused += 1
        return {"created": created, "reused": reused}

    def _seed_spotting(self, demo_user: User, lines_by_code: dict[str, Line]) -> dict:
        vehicles = list(
            Vehicle.objects.filter(status=VehicleStatus.IN_SERVICE).order_by("id")
        )
        if not vehicles:
            self.stdout.write(
                self.style.WARNING("No IN_SERVICE vehicles — skipping spotting seeds.")
            )
            return {"created": 0, "reused": 0}

        created = reused = 0
        today = timezone.now().date()
        for index, (code, event_type, days_ago, notes, coords) in enumerate(
            SPOTTING_PLAN
        ):
            vehicle = vehicles[index % len(vehicles)]
            origin = None
            if event_type == SpottingEventType.AT_STATION:
                line = lines_by_code.get(code)
                origin = (
                    Station.objects.filter(lines=line).first() if line else None
                ) or Station.objects.first()
                if origin is None:
                    continue
            event, was_created = Event.objects.update_or_create(
                reporter=demo_user,
                vehicle=vehicle,
                spotting_date=today - timedelta(days=days_ago),
                type=event_type,
                defaults={
                    "status": SpottingVehicleStatus.IN_SERVICE,
                    "notes": notes,
                    "origin_station": origin,
                    "destination_station": None,
                },
            )
            if coords is not None:
                LocationEvent.objects.update_or_create(
                    event=event,
                    defaults={"location": Point(coords[0], coords[1])},
                )
            if was_created:
                created += 1
            else:
                reused += 1
        return {"created": created, "reused": reused}

    def _flush(self) -> None:
        content_type = ContentType.objects.get_for_model(SocialMediaLink)
        link_ids = list(
            SocialMediaLink.objects.filter(
                user__firebase_id=DEMO_FIREBASE_ID
            ).values_list("id", flat=True)
        )
        votes_deleted, _ = Vote.objects.filter(
            content_type=content_type, object_id__in=link_ids
        ).delete()
        location_events_deleted, _ = LocationEvent.objects.filter(
            event__reporter__firebase_id=DEMO_FIREBASE_ID
        ).delete()
        events_deleted, _ = Event.objects.filter(
            reporter__firebase_id=DEMO_FIREBASE_ID
        ).delete()
        reports_deleted, _ = LineStatusReport.objects.filter(
            user__firebase_id=DEMO_FIREBASE_ID
        ).delete()
        links_deleted, _ = SocialMediaLink.objects.filter(
            user__firebase_id=DEMO_FIREBASE_ID
        ).delete()
        users_deleted, _ = User.objects.filter(firebase_id=DEMO_FIREBASE_ID).delete()

        self.stdout.write(
            self.style.SUCCESS(
                "seed_demo_data --flush complete: "
                f"votes {votes_deleted}, location events {location_events_deleted}, "
                f"spotting events {events_deleted}, status reports {reports_deleted}, "
                f"social links {links_deleted}, users {users_deleted} deleted."
            )
        )
