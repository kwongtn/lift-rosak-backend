"""Seed realistic demo data for the community front page.

Generates a *large*, *varied* dataset so the front page can be reviewed under
something resembling real load: hundreds of status reports from a pool of
seeded users, dozens of feed links with real votes, and the spotting events.

Idempotency is achieved by **delete-then-recreate**: every run first removes
the rows owned by the seeded demo users (``firebase_id`` prefixed with
``SEED_USER_PREFIX``) and then regenerates them from a fixed-seed RNG
(``SEED``), so re-running the command yields the same rows and identical
counts. Real user data is never touched — the deletion is strictly scoped to
the seeded prefix.

It attaches to the EXISTING reference data (lines, stations, vehicles) and never
creates any of them. ``--flush`` removes only the rows this command owns.

The generated timestamps are back-dated through a queryset ``update()`` because
``created`` is ``auto_now_add``. Reports land both inside the rolling
``WINDOW_MINUTES`` pulse window (so a line shows multiple passenger-status
counts) and spread across the service day (so the hourly chart has shape).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from common.models import User, Vote
from incident.enums import PassengerStatus, SocialMediaLinkStatus
from incident.models import LineStatusReport, SocialMediaLink
from incident.services.line_status import WINDOW_MINUTES, service_day_start
from operation.enums import VehicleStatus
from operation.models import Line, Station, Vehicle
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event, LocationEvent

# Fixed seed: the whole dataset is reproducible run to run. Never use bare
# ``random`` — a shared global would make the output order-dependent.
SEED = 1337

# Primary demo identity; every seeded row hangs off a firebase id carrying this
# prefix, which is what scopes deletion to seeded data only.
DEMO_FIREBASE_ID = "demo-seed-user"
DEMO_NICKNAME = "Demo Seed"
SEED_USER_PREFIX = "demo-seed-"

DEFAULT_LINES = 6
DEFAULT_USERS = 150
DEFAULT_REPORTS = 300
DEFAULT_LINKS = 40

# Guarantee: this many lines get >= 2 distinct statuses inside the pulse window
# so the line-card hover breakdown ("Normal 3 / Busy 2") is never invisible.
HOT_LINE_COUNT = 3
# Same-hour variety: this many lines get 2-4 distinct statuses packed into a
# single clock hour, repeated over a few recent hours, so the hourly chart
# shows mixed statuses within one hour rather than one status per hour.
SAME_HOUR_LINE_COUNT = 4
SAME_HOUR_HOURS = 3
# Fraction of the bulk reports that land inside the rolling window.
INSIDE_WINDOW_CHANCE = 0.25
# Fraction of reports that carry a note (the rest are blank).
NOTE_CHANCE = 0.5
# Probability a report is tagged with one of its line's stations. A clear
# majority carry a station (the frontend only renders one when it exists) while
# a meaningful minority stay station-less for variety.
STATION_BIAS = 0.8

_STATUS_WEIGHTS: dict[str, int] = {
    PassengerStatus.NORMAL: 6,
    PassengerStatus.BUSY: 5,
    PassengerStatus.CROWDED: 5,
    PassengerStatus.EXTREMELY_CROWDED: 2,
    PassengerStatus.BACKLOGGED: 2,
    PassengerStatus.DELAYED: 3,
    PassengerStatus.DISRUPTED: 1,
}
_DELAY_CHOICES = (5, 8, 10, 12, 15, 20, 25, 30)

NICKNAMES = [
    "Aiman",
    "Bella",
    "Chong Wei",
    "Devi",
    "Farah",
    "Ganesh",
    "Hafiz",
    "Izzah",
    "Jia Hui",
    "Kavitha",
    "Ling",
    "Maya",
    "Nadia",
    "Ong",
    "Priya",
    "Qistina",
    "Rizal",
    "Siti",
    "Tan",
    "Uma",
    "Vijay",
    "Wan",
    "Xin Yi",
    "Yusof",
    "Zara",
    "Amir",
    "Boon",
    "Cheryl",
    "Danish",
    "Elena",
    "Fauzan",
    "Grace",
    "Hana",
    "Imran",
    "Joanne",
    "Kumar",
    "Liew",
    "Mira",
    "Nabil",
    "Suhaila",
]

# Short natural notes; ``{station}`` is filled from the report's station (or the
# line name when no station was attached).
_NOTES = [
    "Packed but moving, {station} is manageable",
    "Standing room only at {station}",
    "Trains every few minutes, no real wait",
    "Crowd cleared after {station}",
    "Quiet carriage past {station}",
    "Held at {station} for a bit",
    "Slow crawl into {station}",
    "Surprisingly empty for the hour",
    "Loud and packed, hard to board",
    "Seats available near {station}",
    "Delay announced at {station}",
    "Aircon weak, getting stuffy",
    "Something wrong at {station}, moving slowly",
    "Smooth ride, no complaints",
    "Long queue on the platform",
    "Busy but staff managing the flow",
    "Just missed one, next in 3 min",
    "Everyone squeezed in at the doors",
    "Signalling hiccup near {station}",
    "Back to normal after earlier delay",
]

_DOMAINS = [
    "facebook.com",
    "x.com",
    "reddit.com",
    "thestar.com.my",
    "malaymail.com",
    "paultan.org",
    "malaysiakini.com",
    "theedgemalaysia.com",
    "bharian.com.my",
    "astroawani.com",
]
# Empty strings keep most URLs clean; the rest exercise canonicalisation
# (tracking junk, and the same params in two different orders).
_TRACKING = (
    "",
    "",
    "",
    "?fbclid=IwAR0demo",
    "?utm_source=demo&utm_medium=social",
    "?utm_medium=social&utm_source=demo",
    "?s=20&utm_source=demo",
)
_SLUGS = [
    "morning-rush",
    "service-update",
    "crowd-report",
    "delay-watch",
    "commuter-voice",
    "peak-hour",
    "line-status",
    "station-notes",
]
_TITLE_TEMPLATES = [
    "{line} commuters report crowding this morning",
    "{line} delays spark complaints",
    "{line} back to normal after repairs",
    "Crowd control in place on {line}",
    "{line} platform filling up at peak",
    "Signal issue affecting {line}",
    "{line} adds extra services",
    "What is happening on {line} today?",
    "{line} carriage temperatures rising",
    "Commuters share their {line} experience",
]

# (line_code, type, days_ago, notes, coords) — the map signals/dots.
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
            default=DEFAULT_LINES,
            help=f"How many configured lines to give status reports (default {DEFAULT_LINES}).",
        )
        parser.add_argument(
            "--users",
            type=int,
            default=DEFAULT_USERS,
            help=f"Size of the seeded user pool (default {DEFAULT_USERS}).",
        )
        parser.add_argument(
            "--reports",
            type=int,
            default=DEFAULT_REPORTS,
            help=f"Number of status reports to generate (default {DEFAULT_REPORTS}).",
        )
        parser.add_argument(
            "--links",
            type=int,
            default=DEFAULT_LINKS,
            help=f"Number of feed links to generate (default {DEFAULT_LINKS}).",
        )

    def handle(self, *args: Any, **options: Any):
        if options["flush"]:
            self._flush()
            return

        # One RNG per invocation: re-running the command replays the same
        # sequence, so the regenerated dataset is byte-for-byte identical.
        self.rng = random.Random(SEED)

        all_lines = list(Line.objects.all())  # Meta ordering = ["code"]
        if not all_lines:
            self.stdout.write(
                self.style.WARNING("No Lines found — nothing to attach demo data to.")
            )
            return
        lines_by_code = {line.code: line for line in all_lines}
        report_lines = all_lines[: max(options["lines"], 0)]

        with transaction.atomic():
            removed = self._purge_seeded()
            users = self._seed_users(max(options["users"], 1))
            links = self._seed_links(users, all_lines, max(options["links"], 0))
            report_count, inside = self._seed_reports(
                users, report_lines, max(options["reports"], 0)
            )
            votes = self._seed_votes(users, links)
            events = self._seed_spotting(users[0], lines_by_code)

        summary = (
            "seed_demo_data complete: "
            f"purged {removed['links']} links / {removed['reports']} reports / "
            f"{removed['votes']} votes / {removed['events']} events; "
            f"users {len(users)}, links {len(links)}, "
            f"reports {report_count} ({inside} inside the {WINDOW_MINUTES}-min window), "
            f"votes {votes}, spotting events {events['created']}."
        )
        self.stdout.write(self.style.SUCCESS(summary))

    # ------------------------------------------------------------------ users

    def _seed_users(self, count: int) -> list[User]:
        primary, _ = User.objects.get_or_create(
            firebase_id=DEMO_FIREBASE_ID,
            defaults={"nickname": DEMO_NICKNAME},
        )
        users = [primary]
        for index in range(max(count - 1, 0)):
            firebase_id = f"{DEMO_FIREBASE_ID}-{index:04d}"
            user, _ = User.objects.get_or_create(
                firebase_id=firebase_id,
                defaults={"nickname": NICKNAMES[index % len(NICKNAMES)]},
            )
            users.append(user)
        return users

    # ------------------------------------------------------------------ links

    def _seed_links(
        self, users: list[User], all_lines: list[Line], total: int
    ) -> list[SocialMediaLink]:
        if total <= 0 or not all_lines:
            return []
        rng = self.rng
        now = timezone.now()
        links: list[SocialMediaLink] = []
        for index in range(total):
            line_count = min(3, len(all_lines))
            chosen = rng.sample(all_lines, k=rng.randint(1, line_count))
            title = rng.choice(_TITLE_TEMPLATES).format(
                line=chosen[0].display_name if chosen else "the network"
            )
            link = SocialMediaLink.objects.create(
                url=self._link_url(index),
                title=title,
                user=rng.choice(users),
                status=SocialMediaLinkStatus.LIVE,
            )
            link.lines.set(chosen)
            if chosen and rng.random() < 0.5:
                link.stations.set(
                    list(Station.objects.filter(lines__in=chosen).distinct()[:3])
                )
            if chosen and rng.random() < 0.25:
                link.vehicles.set(
                    list(Vehicle.objects.filter(lines__in=chosen).distinct()[:3])
                )
            # Spread the feed over the last three days for a varied "Load More".
            SocialMediaLink.objects.filter(pk=link.pk).update(
                created=now - timedelta(minutes=rng.randint(0, 3 * 24 * 60))
            )
            links.append(link)
        return links

    def _link_url(self, index: int) -> str:
        rng = self.rng
        host = rng.choice(_DOMAINS)
        www = "www." if rng.random() < 0.4 else ""
        tracking = rng.choice(_TRACKING)
        if tracking == "?fbclid=IwAR0demo":
            tracking = f"?fbclid=IwAR0demo{index}"
        return f"https://{www}{host}/demo/{rng.choice(_SLUGS)}-{index}{tracking}"

    # ---------------------------------------------------------------- reports

    def _seed_reports(
        self, users: list[User], lines: list[Line], total: int
    ) -> tuple[int, int]:
        if not lines or total <= 0:
            return 0, 0
        rng = self.rng
        now = timezone.now()
        day_start = service_day_start(now)
        span = max(int((now - day_start).total_seconds() // 60), WINDOW_MINUTES + 1)
        stations_by_line = {
            line.id: list(Station.objects.filter(lines=line)[:5]) for line in lines
        }
        statuses = list(_STATUS_WEIGHTS)
        weights = list(_STATUS_WEIGHTS.values())

        def random_status() -> str:
            return rng.choices(statuses, weights=weights, k=1)[0]

        plans: list[dict[str, Any]] = []

        def add(
            line: Line,
            status: str,
            inside: bool,
            station_bias: float,
            minutes_ago: int | None = None,
        ) -> None:
            if minutes_ago is None:
                if inside:
                    minutes_ago = rng.randint(1, max(WINDOW_MINUTES - 2, 1))
                else:
                    minutes_ago = rng.randint(WINDOW_MINUTES, span)
            delay = (
                rng.choice(_DELAY_CHOICES)
                if status in (PassengerStatus.DELAYED, PassengerStatus.BACKLOGGED)
                else None
            )
            stations = stations_by_line.get(line.id) or []
            station = (
                rng.choice(stations)
                if stations and rng.random() < station_bias
                else None
            )
            plans.append(
                {
                    "line": line,
                    "status": status,
                    "delay": delay,
                    "minutes_ago": minutes_ago,
                    "station": station,
                }
            )

        # 1) Guaranteed multi-status cluster inside the window.
        if total >= HOT_LINE_COUNT * 2:
            for line in lines[:HOT_LINE_COUNT]:
                for status in rng.sample(statuses, 2):
                    add(line, status, inside=True, station_bias=STATION_BIAS)

        # 1b) Same-hour variety: 2-4 distinct statuses for a line inside ONE
        # clock hour, repeated over a few recent hours, so the hourly chart
        # shows mixed statuses per hour. Only whole past clock hours are used,
        # so every report in a group really shares the same hour.
        coverage_budget = min(len(lines), total)
        same_hour_budget = max(total - coverage_budget - HOT_LINE_COUNT * 2, 0)
        hour_floor = now.replace(minute=0, second=0, microsecond=0)
        for line, status, offset in self._same_hour_slots(
            lines, statuses, now, span, same_hour_budget
        ):
            minute = rng.randint(0, now.minute if offset == 0 else 59)
            report_time = (
                hour_floor - timedelta(hours=offset) + timedelta(minutes=minute)
            )
            add(
                line,
                status,
                inside=False,
                station_bias=STATION_BIAS,
                minutes_ago=int((now - report_time).total_seconds() // 60),
            )

        # 2) Coverage: at least one report per configured line.
        for line in lines:
            if len(plans) >= total:
                break
            add(
                line, random_status(), rng.random() < INSIDE_WINDOW_CHANCE, STATION_BIAS
            )

        # 3) Fill the rest round-robin so every line stays represented.
        index = 0
        while len(plans) < total:
            line = lines[index % len(lines)]
            add(
                line, random_status(), rng.random() < INSIDE_WINDOW_CHANCE, STATION_BIAS
            )
            index += 1

        for plan in plans:
            report = LineStatusReport.objects.create(
                line=plan["line"],
                user=rng.choice(users),
                status=plan["status"],
                delay_minutes=plan["delay"],
                notes=self._note(plan["station"], plan["line"]),
            )
            # `created` is auto_now_add; a queryset update bypasses it so the
            # report lands where the plan wants it (inside or outside window).
            LineStatusReport.objects.filter(pk=report.pk).update(
                created=now - timedelta(minutes=plan["minutes_ago"])
            )
            if plan["station"] is not None:
                report.stations.set([plan["station"]])

        inside_count = sum(1 for p in plans if p["minutes_ago"] < WINDOW_MINUTES)
        return len(plans), inside_count

    def _same_hour_slots(
        self,
        lines: list[Line],
        statuses: list[str],
        now: datetime,
        span: int,
        budget: int,
    ) -> list[tuple[Line, str, int]]:
        """(line, status, hour_offset) slots grouping distinct statuses per hour.

        The current hour is always partly elapsed, so it is always usable; older
        hours only if the service day has run that long. Truncated to ``budget``
        so the caller's report total stays exact.
        """
        if budget <= 0:
            return []
        hours_available = span // 60
        offsets = [0, *range(1, min(hours_available, SAME_HOUR_HOURS) + 1)]
        slots: list[tuple[Line, str, int]] = []
        for offset in offsets:
            for line in lines[:SAME_HOUR_LINE_COUNT]:
                sample = self.rng.sample(statuses, self.rng.randint(2, 4))
                slots.extend((line, status, offset) for status in sample)
        return slots[:budget]

    def _note(self, station: Station | None, line: Line) -> str:
        if self.rng.random() >= NOTE_CHANCE:
            return ""
        place = station.display_name if station is not None else line.display_name
        return self.rng.choice(_NOTES).format(station=place)

    # ----------------------------------------------------------------- votes

    def _seed_votes(self, users: list[User], links: list[SocialMediaLink]) -> int:
        if not links:
            return 0
        rng = self.rng
        content_type = ContentType.objects.get_for_model(SocialMediaLink)
        votes = []
        for link in links:
            voter_count = rng.randint(1, min(10, len(users)))
            for voter in rng.sample(users, voter_count):
                votes.append(
                    Vote(
                        user=voter,
                        content_type=content_type,
                        object_id=link.id,
                        value=-1 if rng.random() < 0.15 else 1,
                    )
                )
        Vote.objects.bulk_create(votes)
        return len(votes)

    # --------------------------------------------------------------- spotting

    def _seed_spotting(
        self, demo_user: User, lines_by_code: dict[str, Line]
    ) -> dict[str, int]:
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

    # ------------------------------------------------------- delete helpers

    def _purge_seeded(self) -> dict[str, int]:
        """Delete every row owned by the seeded users. Scoped by id prefix."""
        user_ids = list(
            User.objects.filter(firebase_id__startswith=SEED_USER_PREFIX).values_list(
                "id", flat=True
            )
        )
        link_qs = SocialMediaLink.objects.filter(user_id__in=user_ids)
        link_ids = list(link_qs.values_list("id", flat=True))
        content_type = ContentType.objects.get_for_model(SocialMediaLink)
        vote_qs = Vote.objects.filter(
            user_id__in=user_ids, content_type=content_type, object_id__in=link_ids
        )
        location_qs = LocationEvent.objects.filter(event__reporter_id__in=user_ids)
        event_qs = Event.objects.filter(reporter_id__in=user_ids)
        report_qs = LineStatusReport.objects.filter(user_id__in=user_ids)
        counts = {
            "votes": vote_qs.count(),
            "location_events": location_qs.count(),
            "events": event_qs.count(),
            "reports": report_qs.count(),
            "links": link_qs.count(),
        }
        vote_qs.delete()
        location_qs.delete()
        event_qs.delete()
        report_qs.delete()
        # Deleting the links also clears any remaining vote targeting them.
        link_qs.delete()
        return counts

    def _flush(self) -> None:
        removed = self._purge_seeded()
        users_deleted, _ = User.objects.filter(
            firebase_id__startswith=SEED_USER_PREFIX
        ).delete()
        self.stdout.write(
            self.style.SUCCESS(
                "seed_demo_data --flush complete: "
                f"votes {removed['votes']}, location events "
                f"{removed['location_events']}, spotting events {removed['events']}, "
                f"status reports {removed['reports']}, "
                f"social links {removed['links']}, users {users_deleted} deleted."
            )
        )
