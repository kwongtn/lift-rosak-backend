"""Feed link submission: global canonical-URL dedup plus an auto-upvote.

The feed path is deliberately different from ``submit_social_media_link``: any
logged-in user's submission goes straight to LIVE. A URL that canonicalizes to
an existing row is never inserted twice — the existing row is returned with a
duplicate indicator and the submitter is upvoted instead.
"""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from common.models import User
from incident.enums import SocialMediaLinkStatus
from incident.models import LineStatusReport, SocialMediaLink
from operation.models import Line

from .errors import FeedLinkValidationError, IncidentServiceError
from .page_title import fetch_page_title
from .urls import canonicalize_url
from .votes import set_social_media_link_vote


@dataclass(frozen=True)
class FeedLinkResult:
    link: SocialMediaLink
    is_duplicate: bool
    duplicate_of_id: int | None
    user_vote: int


def _find_existing(canonical: str) -> SocialMediaLink | None:
    """Newest row sharing ``canonical``, locked for update. Sync (needs atomic)."""
    return (
        SocialMediaLink.objects.select_for_update()
        .filter(normalized_url=canonical)
        .order_by("-created")
        .first()
    )


def _create_line_status_report(
    user: User,
    *,
    line_id: int,
    status: str,
    station_ids: list[int],
    delay_minutes: int | None,
    notes: str,
    link: SocialMediaLink | None = None,
) -> LineStatusReport:
    """Create one report and attach its stations. Sync — used by all three paths."""
    report = LineStatusReport.objects.create(
        line_id=line_id,
        status=status,
        delay_minutes=delay_minutes,
        notes=notes or "",
        user=user,
        link=link,
    )
    if station_ids:
        report.stations.set(station_ids)
    return report


def _attach_line_reports(
    user: User,
    *,
    link: SocialMediaLink,
    line_ids: list[int],
    status: str,
    station_ids: list[int],
    delay_minutes: int | None,
    notes: str,
) -> None:
    for line_id in line_ids:
        _create_line_status_report(
            user,
            line_id=line_id,
            status=status,
            station_ids=station_ids,
            delay_minutes=delay_minutes,
            notes=notes,
            link=link,
        )


async def _canonical_exists(canonical: str) -> bool:
    return await SocialMediaLink.objects.filter(normalized_url=canonical).aexists()


async def submit_feed_link(
    user: User,
    *,
    url: str,
    title: str | None,
    line_ids: list[int],
    station_ids: list[int],
    status: str | None,
    delay_minutes: int | None,
    notes: str,
) -> FeedLinkResult:
    canonical = canonicalize_url(url)
    if status is not None and not line_ids:
        raise FeedLinkValidationError(
            "A line status report requires at least one line."
        )

    provided_title = (title or "").strip()
    if provided_title:
        final_title = provided_title
    elif canonical and await _canonical_exists(canonical):
        # Duplicate: it already has a title, so skip the network round-trip.
        final_title = ""
    else:
        final_title = await fetch_page_title(url)

    def _sync() -> FeedLinkResult:
        with transaction.atomic():
            existing = _find_existing(canonical) if canonical else None
            if existing is not None:
                if status is not None:
                    _attach_line_reports(
                        user,
                        link=existing,
                        line_ids=line_ids,
                        status=status,
                        station_ids=station_ids,
                        delay_minutes=delay_minutes,
                        notes=notes,
                    )
                return FeedLinkResult(
                    link=existing,
                    is_duplicate=True,
                    duplicate_of_id=existing.id,
                    user_vote=1,
                )

            try:
                link = SocialMediaLink.objects.create(
                    url=url,
                    normalized_url=canonical or None,
                    title=final_title[:256],
                    user=user,
                    status=SocialMediaLinkStatus.LIVE,
                )
            except IntegrityError:
                # ponytail: normalized_url has no unique constraint (deliberate —
                # legacy rows may already share a canonical URL), so this branch
                # is unreachable today. It is kept so that when the duplicates
                # are cleaned and a partial unique index is added, a first-submit
                # race degrades to dedup instead of a 500.
                raced = _find_existing(canonical)
                if raced is None:
                    raise
                if status is not None:
                    _attach_line_reports(
                        user,
                        link=raced,
                        line_ids=line_ids,
                        status=status,
                        station_ids=station_ids,
                        delay_minutes=delay_minutes,
                        notes=notes,
                    )
                return FeedLinkResult(
                    link=raced,
                    is_duplicate=True,
                    duplicate_of_id=raced.id,
                    user_vote=1,
                )

            if line_ids:
                link.lines.set(line_ids)
            if station_ids:
                link.stations.set(station_ids)
            if status is not None:
                _attach_line_reports(
                    user,
                    link=link,
                    line_ids=line_ids,
                    status=status,
                    station_ids=station_ids,
                    delay_minutes=delay_minutes,
                    notes=notes,
                )
            return FeedLinkResult(
                link=link,
                is_duplicate=False,
                duplicate_of_id=None,
                user_vote=0,
            )

    result = await sync_to_async(_sync)()
    if result.is_duplicate:
        # ``Vote`` is unique per (user, content_type, object_id) and
        # ``_apply_vote`` upserts, so re-submitting never doubles the vote.
        # Applied here because Django transactions are sync-only while this
        # helper is async.
        await set_social_media_link_vote(user, link_id=result.link.id, value=1)
    return result


async def submit_line_status_report(
    user: User,
    *,
    line_id: int,
    status: str,
    station_ids: list[int],
    delay_minutes: int | None,
    notes: str,
) -> LineStatusReport:
    if not await Line.objects.filter(pk=line_id).aexists():
        raise IncidentServiceError(f"Line {line_id} does not exist.")

    return await sync_to_async(_create_line_status_report)(
        user,
        line_id=line_id,
        status=status,
        station_ids=station_ids,
        delay_minutes=delay_minutes,
        notes=notes,
    )
