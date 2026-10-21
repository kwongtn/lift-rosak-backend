"""Deterministic consolidation of passenger line-status reports.

Pure, dependency-light: ``consolidate`` is a plain function over in-memory
values so it can be unit-tested without a database. ``load_line_pulses`` is the
batched async loader that feeds the GraphQL DataLoader; it issues a constant
number of queries regardless of how many line ids are requested.

The service-day **history** side is three read-only loaders over one shared
query (``_service_day_entries``): one line (``load_line_status_history``), the
whole network at once (``load_network_status_history``), and N lines in a
single query (``load_lines_status_history``). All three bucket through
``bucket_hourly`` and all three cost ONE query however many rows or lines they
cover. Each reads the current service day by default, or the one that started
``days_ago`` service days earlier.

The **typical-week** side is ``load_line_status_week_profile``: one query over a
rolling window of weeks, tallied by ``bucket_week_profile`` into 7 x 24
weekday-hour slots with the same tally and dominant-status rules as the hourly
buckets.
"""

from collections.abc import Iterable, Mapping, Sequence
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
# A service day is exactly 24 hourly buckets: 03:00 through 02:00 next morning.
HOURS_IN_SERVICE_DAY = 24
_MAX_PULSE_LINKS = 5
# Upper bound on the ids a single multi-line history read may name. The read is
# one ``line_id__in`` query whatever the count, so this is not a query-count
# guard — it bounds the rows a caller can pull into one response (the network
# has ~a dozen lines, so 64 is generous), and it keeps a client bug that sends
# the whole id space from turning into a full-table scan of the service day.
MAX_LINES_PER_HISTORY_REQUEST = 64
# How far back ``daysAgo`` may reach: eight whole weeks, so a client can still
# line up "the same weekday, N weeks ago" while each read stays one day's slice
# of the table.
MAX_HISTORY_DAYS_AGO = 56
# Look-back of the typical-week profile, in whole weeks. The cap bounds the rows
# the single read pulls (a quarter of a year of one line's reports).
DEFAULT_WEEK_PROFILE_WEEKS = 6
MAX_WEEK_PROFILE_WEEKS = 12

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
    # Per-status report counts; ``count`` is the sum of these values.
    status_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class WeekBucket:
    """One weekday-hour slot of the typical-week profile.

    ``weekday`` is Monday = 0 .. Sunday = 6 of the SERVICE day the reports belong
    to, ``hour`` the local clock hour 0-23. ``count`` / ``dominant_status`` /
    ``status_counts`` mean what they mean on ``HourBucket``, summed over every
    week in the window.
    """

    weekday: int
    hour: int
    count: int
    dominant_status: str | None
    status_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class LineHistory:
    """One line's hourly service-day history: ``buckets`` is ``[]`` when the
    line reported nothing that day (the client's "no data" state), otherwise
    the full 24-bucket series — exactly what ``bucket_hourly`` returns."""

    line_id: int
    buckets: list[HourBucket]


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
    # ``.order_by()`` clears the model default added by migration 0031
    # (``Meta.ordering = ["position"]``): this result is keyed by pk, so the sort
    # is pure overhead and the implicit sibling rank is not even meaningful
    # across a set of unrelated links.
    # ``select_related``/``prefetch_related`` cover the fields the GraphQL type
    # resolves per link (``user``, ``lines``); DjangoOptimizerExtension cannot see
    # loader-returned objects, so without these each link lazy-loads them.
    queryset = (
        SocialMediaLink.objects.filter(pk__in=link_ids)
        .select_related("user")
        .prefetch_related("lines")
        .order_by()
    )
    async for link in queryset:
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


def _dominant_status(statuses: Mapping[str, int]) -> str | None:
    """The most frequent status of one tally, or ``None`` for an empty tally.

    Ties go to the most severe per ``SEVERITY_RANK``. The single home of that
    rule, shared by every bucketing function so an hourly bucket and its
    typical-week sibling can never disagree about which status wins.
    """
    return (
        max(statuses, key=lambda status: (statuses[status], SEVERITY_RANK[status]))
        if statuses
        else None
    )


def bucket_hourly(
    entries: Iterable[ReportEntry], *, day_start: datetime, now: datetime
) -> list[HourBucket]:
    """Bucket entries into the 24 hourly slots of the service day.

    Pure (no DB). ``day_start`` must be hour-aligned. A line with no report in
    ``[day_start, now]`` yields an empty list, which callers render as "no
    data"; once it has one, all ``HOURS_IN_SERVICE_DAY`` hours from ``day_start``
    through 02:00 are emitted — empty hours with ``count=0`` and
    ``dominant_status=None`` so a chart always gets its full set of labels.
    Entries outside ``[day_start, now]`` are ignored, and so is one at or after
    ``day_start`` + 24h: that instant opens the NEXT service day, which matters
    for a past day, where ``now`` lies beyond the day's end.
    ``dominant_status`` is the most frequent status in the hour, ties going to
    the most severe (``_dominant_status``). ``status_counts`` carries the hour's
    per-status tallies (raw status values) so callers can render a segmented bar;
    it is ``{}`` for an empty hour and always sums to ``count``.
    """
    day_end = day_start + timedelta(hours=HOURS_IN_SERVICE_DAY)
    per_hour: dict[datetime, dict[str, int]] = {}
    for entry in entries:
        if not day_start <= entry.created <= now or entry.created >= day_end:
            continue
        hour = entry.created.replace(minute=0, second=0, microsecond=0)
        statuses = per_hour.setdefault(hour, {})
        statuses[entry.status] = statuses.get(entry.status, 0) + 1

    if not per_hour:
        return []

    buckets: list[HourBucket] = []
    for offset in range(HOURS_IN_SERVICE_DAY):
        hour = day_start + timedelta(hours=offset)
        statuses = per_hour.get(hour, {})
        buckets.append(
            HourBucket(
                hour_start=hour,
                hour_end=hour + timedelta(hours=1),
                count=sum(statuses.values()),
                dominant_status=_dominant_status(statuses),
                status_counts=dict(statuses),
            )
        )
    return buckets


def bucket_week_profile(
    entries: Iterable[ReportEntry],
    *,
    now: datetime,
    weeks: int,
    day_start_hour: int = DAY_START_HOUR,
) -> list[WeekBucket]:
    """Tally the last ``weeks`` weeks of entries into 7 x 24 weekday-hour slots.

    Pure (no DB). The window is ``[now - weeks * 7 days, now]``; entries outside
    it are ignored. An entry lands in the slot of its local clock hour and of the
    weekday of its SERVICE day: it is shifted back by ``day_start_hour`` before
    the weekday is read, so with the default 03:00 start a 01:30 Tuesday report
    counts toward Monday's late night, exactly where ``bucket_hourly`` files it
    (``day_start_hour=0`` gives plain calendar weekdays). ``created`` is naive
    local time (``USE_TZ = False``, ``Asia/Kuala_Lumpur``), so no zone conversion
    is involved.

    No entry in the window yields ``[]`` (the client's "no data" state);
    otherwise ALL 168 slots are emitted, Monday first and, within a weekday, in
    service-day order (``day_start_hour`` .. 23, then 0 ..), empty slots with
    ``count=0`` and ``dominant_status=None``. ``dominant_status`` and
    ``status_counts`` follow ``bucket_hourly`` (``_dominant_status``; the counts
    sum to ``count``). ``count`` is the raw total over the window's weeks, not an
    average, so a client can apply its own minimum-report threshold.
    """
    window_start = now - timedelta(weeks=weeks)
    per_slot: dict[tuple[int, int], dict[str, int]] = {}
    for entry in entries:
        if not window_start <= entry.created <= now:
            continue
        weekday = (entry.created - timedelta(hours=day_start_hour)).weekday()
        statuses = per_slot.setdefault((weekday, entry.created.hour), {})
        statuses[entry.status] = statuses.get(entry.status, 0) + 1

    if not per_slot:
        return []

    buckets: list[WeekBucket] = []
    for weekday in range(7):
        for offset in range(HOURS_IN_SERVICE_DAY):
            hour = (day_start_hour + offset) % HOURS_IN_SERVICE_DAY
            statuses = per_slot.get((weekday, hour), {})
            buckets.append(
                WeekBucket(
                    weekday=weekday,
                    hour=hour,
                    count=sum(statuses.values()),
                    dominant_status=_dominant_status(statuses),
                    status_counts=dict(statuses),
                )
            )
    return buckets


def _check_day_start_hour(day_start_hour: int) -> None:
    if not 0 <= day_start_hour <= 23:
        raise LineStatusValidationError(
            f"dayStartHour must be between 0 and 23, got {day_start_hour}."
        )


async def _service_day_entries(
    line_ids: Sequence[int] | None,
    *,
    day_start_hour: int = DAY_START_HOUR,
    days_ago: int = 0,
    now: datetime | None = None,
) -> tuple[datetime, datetime, list[tuple[int, ReportEntry]]]:
    """Resolve the service-day window and read the rows inside it: ONE query.

    The single place the ``day_start_hour`` / ``days_ago`` validation, the
    ``service_day_start`` arithmetic and the ``LineStatusReport`` read live, so
    the three history loaders cannot drift apart on any of them.

    ``days_ago`` picks the service day: ``0`` is the current one (window
    ``[day_start, now]``), ``N > 0`` the one that started N service days before
    it (the whole day, ``[day_start, day_start + 24h)``, never capped at
    ``now``). The client sends a literal integer and all the date arithmetic is
    done here.

    ``line_ids`` selects the scope:

    * ``None`` — every line's reports (the network-wide read). It filters on
      ``created`` alone, and the table's index is ``(line, created)``, so this
      is a sequential scan of the service day's rows; fine at current volume,
      and the reason a network read is a *single* grouped query rather than a
      loop over lines.
    * a non-empty sequence — only those lines (``line_id__in``).
    * an empty sequence — nothing. Answered from the window alone, so an empty
      request costs ZERO queries.

    Returns ``(now, day_start, rows)`` where ``rows`` pairs each report with its
    ``line_id``, in ``created`` order, for the caller to bucket (``bucket_hourly``
    caps a past day at its own end, so ``now`` is passed on unchanged).
    """
    _check_day_start_hour(day_start_hour)
    if not 0 <= days_ago <= MAX_HISTORY_DAYS_AGO:
        raise LineStatusValidationError(
            f"daysAgo must be between 0 and {MAX_HISTORY_DAYS_AGO}, got {days_ago}."
        )
    resolved_now = now or timezone.now()
    day_start = service_day_start(resolved_now, day_start_hour) - timedelta(
        days=days_ago
    )
    if line_ids is not None and not line_ids:
        return resolved_now, day_start, []

    queryset = LineStatusReport.objects.filter(
        created__gte=day_start,
        # Exclusive: a report stamped at the next service day's first instant
        # belongs to that day. For the current day this bound lies beyond
        # ``now``, so ``created__lte`` is the one that decides.
        created__lt=day_start + timedelta(hours=HOURS_IN_SERVICE_DAY),
        created__lte=resolved_now,
    )
    if line_ids is not None:
        queryset = queryset.filter(line_id__in=line_ids)
    rows = [
        (
            report.line_id,
            ReportEntry(
                status=report.status,
                created=report.created,
                link_id=report.link_id,
            ),
        )
        async for report in queryset.order_by("created")
    ]
    return resolved_now, day_start, rows


async def load_line_status_history(
    line_id: int,
    *,
    day_start_hour: int = DAY_START_HOUR,
    days_ago: int = 0,
    now: datetime | None = None,
) -> list[HourBucket]:
    """Hourly history for one line over one service day (one query).

    The current service day, or the one that started ``days_ago`` service days
    earlier. Returns an empty list when the line has no report in that day,
    otherwise the full 24-bucket series (see ``bucket_hourly``).
    """
    resolved_now, day_start, rows = await _service_day_entries(
        [line_id], day_start_hour=day_start_hour, days_ago=days_ago, now=now
    )
    return bucket_hourly(
        (entry for _, entry in rows), day_start=day_start, now=resolved_now
    )


async def load_network_status_history(
    day_start_hour: int = DAY_START_HOUR,
    *,
    days_ago: int = 0,
    now: datetime | None = None,
) -> list[HourBucket]:
    """Network-wide hourly history over one service day (one query).

    The current service day, or the one ``days_ago`` service days earlier.

    The same series ``load_line_status_history`` builds, with **no line
    filter**: ONE read of every ``LineStatusReport`` in the service day, then
    one bucket pass over the combined stream. So a line's hour is not its own
    bucket — the buckets describe the network, and ``dominant_status`` /
    ``status_counts`` are tallies over every line's reports in that hour.

    Returns ``[]`` when NOTHING was reported all day; otherwise the full
    24-bucket series (see ``bucket_hourly``).
    """
    resolved_now, day_start, rows = await _service_day_entries(
        None, day_start_hour=day_start_hour, days_ago=days_ago, now=now
    )
    return bucket_hourly(
        (entry for _, entry in rows), day_start=day_start, now=resolved_now
    )


async def load_lines_status_history(
    line_ids: Sequence[int],
    day_start_hour: int = DAY_START_HOUR,
    *,
    days_ago: int = 0,
    now: datetime | None = None,
) -> list[LineHistory]:
    """Per-line hourly history for many lines at once (ONE query for N lines).

    The current service day, or the one ``days_ago`` service days earlier.

    Returns one ``LineHistory`` per requested line, in the order requested; a
    line with no report that service day carries ``buckets == []``, which the
    client renders as its per-line "no data" state. Duplicate ids collapse to a
    single entry (first occurrence wins).

    An empty ``line_ids`` returns ``[]`` without touching the database.
    ``line_ids`` is length-capped at ``MAX_LINES_PER_HISTORY_REQUEST`` so one
    request cannot ask for an unbounded scan.
    """
    if len(line_ids) > MAX_LINES_PER_HISTORY_REQUEST:
        raise LineStatusValidationError(
            f"linesStatusHistory accepts at most "
            f"{MAX_LINES_PER_HISTORY_REQUEST} line ids per call, got "
            f"{len(line_ids)}."
        )
    unique_ids = list(dict.fromkeys(line_ids))
    resolved_now, day_start, rows = await _service_day_entries(
        unique_ids, day_start_hour=day_start_hour, days_ago=days_ago, now=now
    )

    entries_by_line: dict[int, list[ReportEntry]] = {
        line_id: [] for line_id in unique_ids
    }
    for row_line_id, entry in rows:
        entries_by_line[row_line_id].append(entry)

    return [
        LineHistory(
            line_id=line_id,
            buckets=bucket_hourly(
                entries_by_line[line_id], day_start=day_start, now=resolved_now
            ),
        )
        for line_id in unique_ids
    ]


async def load_line_status_week_profile(
    line_id: int,
    *,
    weeks: int = DEFAULT_WEEK_PROFILE_WEEKS,
    day_start_hour: int = DAY_START_HOUR,
    now: datetime | None = None,
) -> list[WeekBucket]:
    """Typical-week profile of one line over the last ``weeks`` weeks (ONE query).

    Reads the line's reports in ``[now - weeks * 7 days, now]`` and tallies them
    per weekday-hour slot (see ``bucket_week_profile``): ``[]`` when the line has
    no report in the window, otherwise all 168 slots. ``weeks`` must be in
    ``1..MAX_WEEK_PROFILE_WEEKS`` and ``day_start_hour`` in ``0..23``
    (``LineStatusValidationError``).
    """
    if not 1 <= weeks <= MAX_WEEK_PROFILE_WEEKS:
        raise LineStatusValidationError(
            f"weeks must be between 1 and {MAX_WEEK_PROFILE_WEEKS}, got {weeks}."
        )
    _check_day_start_hour(day_start_hour)
    resolved_now = now or timezone.now()
    # ``.order_by()`` clears the model's ``-created`` default: a tally ignores
    # order. ``values_list`` skips hydrating each row's notes text.
    rows = (
        LineStatusReport.objects.filter(
            line_id=line_id,
            created__gte=resolved_now - timedelta(weeks=weeks),
            created__lte=resolved_now,
        )
        .order_by()
        .values_list("status", "created")
    )
    return bucket_week_profile(
        [ReportEntry(status=status, created=created) async for status, created in rows],
        now=resolved_now,
        weeks=weeks,
        day_start_hour=day_start_hour,
    )
