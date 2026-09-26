import logging
import time
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils.timezone import now
from safedelete.models import HARD_DELETE

from common.models import User
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident
from incident.services.errors import OfficialPostFetchError
from incident.services.official_posts import (
    fetch_user_posts,
    get_system_author,
    ingest_posts,
    latest_post_id,
)
from rosak.celery import app as celery_app

logger = logging.getLogger(__name__)

SOFT_DELETED_RETENTION = timedelta(days=90)
REJECTED_RETENTION = timedelta(days=30)

#: Per-handle counters reported by ``ingest_official_posts``; also the keys
#: summed into the task's totals dict.
INGEST_COUNTERS = ("fetched", "created", "skipped", "duplicate_urls")


@celery_app.task()
def purge_soft_deleted_incidents() -> int:
    """Hard-delete incidents soft-deleted more than 90 days ago."""
    cutoff = now() - SOFT_DELETED_RETENTION
    expired = CalendarIncident.deleted_objects.filter(deleted__lt=cutoff)

    count = 0
    for incident in expired:
        incident.delete(force_policy=HARD_DELETE)
        count += 1

    logger.info("Purged %d soft-deleted incidents past retention", count)
    return count


@celery_app.task()
def purge_rejected_incidents() -> int:
    """Hard-delete visible REJECTED incidents unchanged for over 30 days.

    Soft-deleted rows are intentionally out of scope here — they belong to
    purge_soft_deleted_incidents regardless of status.
    """
    cutoff = now() - REJECTED_RETENTION
    expired = CalendarIncident.objects.filter(
        status=CalendarIncidentStatus.REJECTED,
        modified__lt=cutoff,
    )

    count = 0
    for incident in expired:
        incident.delete(force_policy=HARD_DELETE)
        count += 1

    logger.info("Purged %d rejected incidents past retention", count)
    return count


def _ingest_handle(handle: str, *, author: User) -> dict[str, Any]:
    """Fetch and ingest one tracked handle, then report its counters.

    Isolated per handle so a fetch failure for one account cannot abort the
    others: the sanitized reason (``OfficialPostFetchError`` never carries the
    upstream body or the bearer token) is recorded on the handle's own entry and
    the remaining handles still run. No retry and no sleep — the 5-minute beat
    tick is the retry, and a sleep here would pin a worker.
    """
    started = time.monotonic()
    stats: dict[str, Any] = dict.fromkeys(INGEST_COUNTERS, 0)

    try:
        # since_id keeps the read cheap: only genuinely new posts are billed.
        posts = fetch_user_posts(
            handle,
            since_id=latest_post_id(handle),
            limit=settings.OFFICIAL_POST_FETCH_LIMIT,
        )
    except OfficialPostFetchError as exc:
        logger.warning("Official post fetch failed for handle=%s: %s", handle, exc)
        stats["error"] = str(exc)
    else:
        summary = ingest_posts(posts, handle=handle, author=author)
        stats.update(
            fetched=summary.fetched,
            created=summary.created,
            skipped=summary.skipped,
            duplicate_urls=summary.duplicate_urls,
        )
        # Phase 2 hooks one Telegram notification per entry in
        # summary.created_ids here, after the rows exist.

    stats["duration_ms"] = int((time.monotonic() - started) * 1000)
    logger.info(
        "Official post ingest handle=%s fetched=%s created=%s skipped=%s "
        "duplicate_urls=%s duration_ms=%s",
        handle,
        stats["fetched"],
        stats["created"],
        stats["skipped"],
        stats["duplicate_urls"],
        stats["duration_ms"],
    )
    return stats


@celery_app.task(name="incident.tasks.ingest_official_posts")
def ingest_official_posts() -> dict[str, Any]:
    """Ingest new official X posts for every tracked handle.

    Two env guards come first and both no-op without writing anything or making
    a request: ``OFFICIAL_POST_INGESTION_ENABLED`` (the kill switch — flipping it
    is the only thing needed to stop or start ingestion) and
    ``X_API_BEARER_TOKEN`` (the X API's free tier cannot read, so a paid token is
    required; there is deliberately no fallback source). A missing system author
    is *not* swallowed — a misconfigured database should be loud.

    Returns a totals dict, ``{"skipped": ...}`` when a guard tripped.
    """
    if not settings.OFFICIAL_POST_INGESTION_ENABLED:
        logger.info(
            "Official post ingestion is disabled "
            "(OFFICIAL_POST_INGESTION_ENABLED=false); nothing fetched or written"
        )
        return {"skipped": "disabled"}

    if not settings.X_API_BEARER_TOKEN:
        logger.warning(
            "X_API_BEARER_TOKEN is not configured; official post ingestion is idle. "
            "Configure a read-capable (Basic or higher) token and set "
            "OFFICIAL_POST_INGESTION_ENABLED=true to start."
        )
        return {"skipped": "no_token"}

    author = get_system_author()
    handles = list(settings.OFFICIAL_POST_HANDLES)
    per_handle = {handle: _ingest_handle(handle, author=author) for handle in handles}

    totals: dict[str, int] = {
        counter: sum(int(entry[counter]) for entry in per_handle.values())
        for counter in INGEST_COUNTERS
    }
    return {"handles": per_handle, **totals}
