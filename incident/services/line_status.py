"""Deterministic consolidation of passenger line-status reports.

Pure, dependency-light: ``consolidate`` is a plain function over in-memory
values so it can be unit-tested without a database. ``load_line_pulses`` is the
batched async loader that feeds the GraphQL DataLoader; it issues a constant
number of queries regardless of how many line ids are requested.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone

from common.models import Vote
from incident.enums import PassengerStatus
from incident.models import LineStatusReport, SocialMediaLink
from incident.services.errors import LineStatusValidationError

# Calibration knobs.
# 15-minute rolling window. Crowd-sourced crowding displays use a ~10-minute
# window in industry practice (Moovit/Transit); with 2-8 minute metro headways
# anything near an hour is far too stale to describe the next train, so we keep
# a small margin above the 10-minute display window.
WINDOW_MINUTES = 15
MIN_REPORTS = 1
# Service day starts at 03:00 local: the metro day rolls over in the small hours,
# so a before-dawn report belongs to the service day that is still running.
DAY_START_HOUR = 3
_MAX_PULSE_LINKS = 5

# Ordinal = enum declaration order.
SEVERITY_RANK: dict[str, int] = {
    member.value: rank for rank, member in enumerate(PassengerStatus)
}
LABEL: dict[str, str] = {
    member.value: member.value.replace("_", " ").title() for member in PassengerStatus
}


@dataclass(frozen=True, slots=True)
class ReportEntry:
    """A single status report reduced to the fields consolidation needs."""

    status: str
    created: datetime
    link_id: int | None = None


@dataclass(frozen=True, slots=True)
class Consolidation:
    status: str
    count: int
    status_count: int
    # Per-status raw report counts; ``status_count`` is the winner's entry.
    status_counts: dict[str, int]
    message: str


@dataclass(frozen=True, slots=True)
class LinePulseData:
    status: str | None
    message: str | None
    count: int
    status_count: int
    status_counts: dict[str, int]
    window_minutes: int
    links: list[SocialMediaLink]


@dataclass(frozen=True, slots=True)
class HourBucket:
    hour_start: datetime
    hour_end: datetime
    count: int
    dominant_status: str | None


def consolidate(
    entries: Iterable[ReportEntry],
    scores: Mapping[int, int],
    *,
    now: datetime,
    window: timedelta = timedelta(minutes=WINDOW_MINUTES),
    min_reports: int = MIN_REPORTS,
) -> Consolidation | None:
    """Weighted majority over recent report entries, deterministically.

    A report linked to a social media entry is amplified by
    ``1 + max(score, 0)``: every report counts at least once (a freshly
    submitted, zero-vote tag must not be invisible), upvotes add influence,
    downvotes remove amplification but never erase the report.
    """
    recent = [entry for entry in entries if now - window <= entry.created <= now]
    if len(recent) < min_reports:
        return None

    weight: dict[str, int] = {}
    status_count: dict[str, int] = {}
    latest: dict[str, datetime] = {}
    contributing = 0
    for entry in recent:
        contribution = (
            1 + max(scores.get(entry.link_id, 0), 0) if entry.link_id is not None else 1
        )
        # Defensive no-op: contributions are always >= 1.
        if contribution <= 0:
            continue
        weight[entry.status] = weight.get(entry.status, 0) + contribution
        status_count[entry.status] = status_count.get(entry.status, 0) + 1
        latest[entry.status] = max(
            latest.get(entry.status, entry.created), entry.created
        )
        contributing += 1

    if not weight:
        return None

    best = max(
        weight,
        key=lambda status: (weight[status], latest[status], SEVERITY_RANK[status]),
    )
    noun = "entry" if contributing == 1 else "entries"
    message = (
        f"According to {contributing} social media {noun}, this line is {LABEL[best]}."
    )
    return Consolidation(
        status=best,
        count=contributing,
        status_count=status_count[best],
        status_counts=status_count,
        message=message,
    )


async def _content_type_for(model) -> ContentType:
    return await sync_to_async(ContentType.objects.get_for_model)(model)


async def _link_scores(link_ids: set[int]) -> dict[int, int]:
    """One aggregate across every requested link's votes."""
    content_type = await _content_type_for(SocialMediaLink)
    scores: dict[int, int] = {}
    rows = (
        Vote.objects.filter(content_type=content_type, object_id__in=link_ids)
        .values("object_id")
        .annotate(total=Sum("value"))
    )
    async for row in rows:
        scores[row["object_id"]] = row["total"] or 0
    return scores


async def _links_by_id(link_ids: set[int]) -> dict[int, SocialMediaLink]:
    if not link_ids:
        return {}
    links: dict[int, SocialMediaLink] = {}
    async for link in SocialMediaLink.objects.filter(pk__in=link_ids):
        links[link.pk] = link
    return links


async def load_line_pulses(
    line_ids: list[int], *, now: datetime | None = None
) -> dict[int, LinePulseData]:
    """Consolidated pulse per line id in a constant number of queries.

    Returns an entry for every requested line: a line without a recent report
    maps to ``LinePulseData(status=None, message=None, count=0, status_count=0,
    status_counts={}, window_minutes=WINDOW_MINUTES, links=[])``.
    """
    now = now or timezone.now()
    window = timedelta(minutes=WINDOW_MINUTES)

    reports = [
        report
        async for report in LineStatusReport.objects.filter(
            line_id__in=line_ids,
            created__gte=now - window,
        )
        .select_related("link")
        .order_by("-created")
    ]

    entries_by_line: dict[int, list[ReportEntry]] = {}
    link_order_by_line: dict[int, list[int]] = {}
    for report in reports:
        entries_by_line.setdefault(report.line_id, []).append(
            ReportEntry(
                status=report.status,
                created=report.created,
                link_id=report.link_id,
            )
        )
        if report.link_id is not None:
            line_link_order = link_order_by_line.setdefault(report.line_id, [])
            if report.link_id not in line_link_order:
                line_link_order.append(report.link_id)

    all_link_ids: set[int] = set()
    for linked_ids in link_order_by_line.values():
        all_link_ids.update(linked_ids)
    scores = await _link_scores(all_link_ids)
    links_by_id = await _links_by_id(all_link_ids)

    pulses: dict[int, LinePulseData] = {}
    for line_id in line_ids:
        consolidation = consolidate(
            entries_by_line.get(line_id, []), scores, now=now, window=window
        )
        if consolidation is None:
            pulses[line_id] = LinePulseData(
                status=None,
                message=None,
                count=0,
                status_count=0,
                status_counts={},
                window_minutes=WINDOW_MINUTES,
                links=[],
            )
            continue
        order = link_order_by_line.get(line_id, [])[:_MAX_PULSE_LINKS]
        pulses[line_id] = LinePulseData(
            status=consolidation.status,
            message=consolidation.message,
            count=consolidation.count,
            status_count=consolidation.status_count,
            status_counts=consolidation.status_counts,
            window_minutes=WINDOW_MINUTES,
            links=[links_by_id[link_id] for link_id in order if link_id in links_by_id],
        )
    return pulses


def service_day_start(now: datetime, day_start_hour: int = DAY_START_HOUR) -> datetime:
    """Start of the service day containing ``now``: that day at ``day_start_hour``.

    Before ``day_start_hour`` the current service day began the previous day
    (e.g. a 02:30 report belongs to yesterday's 03:00 service day).
    """
    candidate = now.replace(hour=day_start_hour, minute=0, second=0, microsecond=0)
    if now < candidate:
        candidate -= timedelta(days=1)
    return candidate


def bucket_hourly(
    entries: Iterable[ReportEntry], *, day_start: datetime, now: datetime
) -> list[HourBucket]:
    """Bucket entries into hourly slots from ``day_start`` to ``now`` inclusive.

    Pure (no DB). ``day_start`` must be hour-aligned. Empty hours are emitted
    with ``count=0`` and ``dominant_status=None`` so a chart gets a continuous
    series. Entries outside ``[day_start, now]`` are ignored. ``dominant_status``
    is the most frequent status in the hour; ties go to the most severe per
    ``SEVERITY_RANK``.
    """
    per_hour: dict[datetime, dict[str, int]] = {}
    for entry in entries:
        if not day_start <= entry.created <= now:
            continue
        hour = entry.created.replace(minute=0, second=0, microsecond=0)
        statuses = per_hour.setdefault(hour, {})
        statuses[entry.status] = statuses.get(entry.status, 0) + 1

    last_hour = now.replace(minute=0, second=0, microsecond=0)
    buckets: list[HourBucket] = []
    hour = day_start
    while hour <= last_hour:
        statuses = per_hour.get(hour, {})
        dominant = (
            max(statuses, key=lambda status: (statuses[status], SEVERITY_RANK[status]))
            if statuses
            else None
        )
        buckets.append(
            HourBucket(
                hour_start=hour,
                hour_end=hour + timedelta(hours=1),
                count=sum(statuses.values()),
                dominant_status=dominant,
            )
        )
        hour += timedelta(hours=1)
    return buckets


async def load_line_status_history(
    line_id: int,
    *,
    day_start_hour: int = DAY_START_HOUR,
    now: datetime | None = None,
) -> list[HourBucket]:
    """Hourly history for one line over its current service day (one query)."""
    if not 0 <= day_start_hour <= 23:
        raise LineStatusValidationError(
            f"dayStartHour must be between 0 and 23, got {day_start_hour}."
        )
    now = now or timezone.now()
    day_start = service_day_start(now, day_start_hour)
    entries = [
        ReportEntry(
            status=report.status,
            created=report.created,
            link_id=report.link_id,
        )
        async for report in LineStatusReport.objects.filter(
            line_id=line_id,
            created__gte=day_start,
            created__lte=now,
        ).order_by("created")
    ]
    return bucket_hourly(entries, day_start=day_start, now=now)
