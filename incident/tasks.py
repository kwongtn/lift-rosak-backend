import html
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from asgiref.sync import async_to_sync
from django.conf import settings
from django.utils.timezone import now
from safedelete.models import HARD_DELETE

from common.models import User
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident, SocialMediaLink
from incident.services.errors import OfficialPostFetchError
from incident.services.official_posts import (
    fetch_user_posts,
    get_system_author,
    ingest_posts,
    latest_post_id,
)
from rosak.celery import app as celery_app
from telegram_provider.models import TelegramSocialMediaLinkLog
from telegram_provider.utils import send_message

logger = logging.getLogger(__name__)

SOFT_DELETED_RETENTION = timedelta(days=90)
REJECTED_RETENTION = timedelta(days=30)

#: Per-handle counters reported by ``ingest_official_posts``; also the keys
#: summed into the task's totals dict.
INGEST_COUNTERS = ("fetched", "created", "skipped", "duplicate_urls")

#: Telegram's hard limit on the text of one message. The notification is built
#: against it rather than against some safety margin, because a rejected
#: message is never retried — the 5-minute beat only re-runs the *fetch*.
TELEGRAM_MAX_TEXT_LENGTH = 4096
#: Appended when the post text had to be cut. Counted against the budget, so a
#: truncated body always states that it is truncated.
TRUNCATION_MARKER = "\n\n…[truncated]"
#: The console moderation queue the notification links to for approval.
CONSOLE_LINKS_PATH = "/console/insiden/links"
#: Pseudo-handle reported by ``notify_official_post_links`` when no admin chat is
#: configured. The webhook is not account-scoped, so there is no real handle to
#: name; this keeps that one log line honest instead of fabricating an account.
WEBHOOK_HANDLE_LABEL = "webhook"


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


def _telegram_escape(value: str) -> str:
    """HTML-escape a value destined for a ``parse_mode="HTML"`` message.

    ``quote=False`` is deliberate: the Bot API documents only ``&lt;`` ``&gt;``
    and ``&amp;`` as the entities that must be produced, so escaping the quote
    characters as well would add entities Telegram never asked for, in a
    message whose whole job is to be delivered. Every value here is either
    element text or a double-quoted ``href`` we generated, and none of them
    can contain a raw ``"``. Post text is third-party content and the handle
    comes from an env var, so neither is trusted to be free of markup.
    """
    return html.escape(value, quote=False)


def _format_posted_at(posted_at: datetime | None) -> str:
    """Render a post's own time for humans.

    ``USE_TZ`` is off, so ``posted_at`` is naive local time; the time-zone name
    is spelled out rather than left ambiguous. A null ``posted_at`` (possible
    on the column, though ingestion always fills it) degrades to ``unknown``
    instead of raising.
    """
    if posted_at is None:
        return "unknown"
    return f"{posted_at:%Y-%m-%d %H:%M} {settings.TIME_ZONE}"


def _build_notification_text(link: SocialMediaLink) -> str:
    """Compose the admin notification for one newly ingested ``link``.

    Carries the handle, the post time, the **verbatim** post text, the
    permalink and the console queue URL — never ``raw_payload``, whose blob
    shape is the provider's business. The text body is truncated so the whole
    message stays inside Telegram's 4096-character limit *after* escaping, so
    a post full of ``&`` cannot push the message over the edge.
    """
    head = (
        "<b>New official post — awaiting approval</b>\n"
        f"<b>Handle:</b> @{_telegram_escape(link.source_handle)}\n"
        f"<b>Posted:</b> {_telegram_escape(_format_posted_at(link.posted_at))}\n\n"
    )
    tail = (
        f'\n\n<a href="{_telegram_escape(link.url)}">Open the post on X</a>\n'
        f'<a href="{_telegram_escape(settings.FRONTEND_BASE_URL + CONSOLE_LINKS_PATH)}">'
        "Approve in the console</a>\n\n"
        "Reply to this message with <code>/approve</code> to publish it."
    )

    body = _telegram_escape(link.description or "")
    budget = TELEGRAM_MAX_TEXT_LENGTH - len(head) - len(tail) - len(TRUNCATION_MARKER)
    if budget < 0:
        # Pathological (a multi-kilobyte base URL): keep the actionable parts
        # and drop the body rather than emitting an unsendable message.
        body = ""
    elif len(body) > budget:
        body = body[:budget] + TRUNCATION_MARKER
    return f"{head}{body}{tail}"


def _notify_new_link(link: SocialMediaLink) -> bool:
    """Send one admin notification for ``link``; True when it went out.

    The ``TelegramSocialMediaLinkLog`` join row is what lets an admin resolve
    this *outbound* message back to the link by replying ``/approve`` — the
    handler matches on ``payload["message"]``, which ``send_message`` now
    stamps when asked for the log. A dead-lettered send returns ``None`` and
    writes no join row, so an un-notified post is **not** retried by a later
    tick: ingestion is idempotent, so the post is skipped, never re-announced.
    The row still lands `PENDING_APPROVAL` and can be approved from the console,
    which is why a raise is contained here rather than allowed to abort the run.
    """
    try:
        sent = async_to_sync(send_message)(
            chat_id=settings.TELEGRAM_ADMIN_CHAT_ID,
            text=_build_notification_text(link),
            parse_mode="HTML",
            return_log=True,
        )
    except Exception as exc:  # boundary: a notify failure is not a tick failure
        logger.warning(
            "Official post notification raised for link=%s (%s: %s)",
            link.id,
            type(exc).__name__,
            exc,
        )
        return False

    if sent is None:
        logger.warning(
            "Official post notification was dead-lettered for link=%s; the row "
            "stays PENDING_APPROVAL and can still be approved from the console",
            link.id,
        )
        return False

    message, log = sent
    TelegramSocialMediaLinkLog.objects.create(
        social_media_link=link,
        telegram_log=log,
    )
    logger.info(
        "Notified admin of official post link=%s telegram_message_id=%s",
        link.id,
        getattr(message, "message_id", None),
    )
    return True


def _notify_created_links(handle: str, created_ids: tuple[int, ...]) -> int:
    """Notify the admin chat once per newly created row; returns the count sent.

    Skipped/duplicate posts have no id in ``created_ids`` and are therefore
    never notified, so a re-scrape is silent. The whole pass is skipped when
    no admin chat is configured — nothing is constructed and nothing is sent.
    """
    if not created_ids:
        return 0

    if not settings.TELEGRAM_ADMIN_CHAT_ID:
        logger.info(
            "TELEGRAM_ADMIN_CHAT_ID is not configured; %d official post(s) for "
            "handle=%s ingested without notification",
            len(created_ids),
            handle,
        )
        return 0

    sent = 0
    for link in SocialMediaLink.objects.filter(id__in=created_ids).order_by("id"):
        if _notify_new_link(link):
            sent += 1
    return sent


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
        # Phase 2: one notification per *newly created* row, after the rows
        # exist. Isolated inside _notify_created_links, so a Telegram failure
        # never costs us the ingest.
        stats["notified"] = _notify_created_links(handle, summary.created_ids)

    stats["duration_ms"] = int((time.monotonic() - started) * 1000)
    logger.info(
        "Official post ingest handle=%s fetched=%s created=%s skipped=%s "
        "duplicate_urls=%s notified=%s duration_ms=%s",
        handle,
        stats["fetched"],
        stats["created"],
        stats["skipped"],
        stats["duplicate_urls"],
        stats.get("notified", 0),
        stats["duration_ms"],
    )
    return stats


@celery_app.task(name="incident.tasks.notify_official_post_links")
def notify_official_post_links(link_ids: list[int]) -> int:
    """Telegram the admin about links created off the request path.

    The polling task notifies inline (it *is* a background job). The webhook
    receiver cannot: X requires a 200 within 10 seconds, and a Telegram round
    trip with bounded retries is exactly the kind of stall that turns into a
    redelivery. So the view persists the row, answers, and hands the ids to this
    task — which reuses ``_notify_created_links`` rather than re-implementing a
    single line of it, so both paths format the message and write the
    ``TelegramSocialMediaLinkLog`` join row identically.

    ``handle`` is only used for the log line when the admin chat is unconfigured,
    so it is passed as the generic "webhook" label. Returns how many
    notifications actually went out; a failure on one link never aborts the rest.
    """
    return _notify_created_links(WEBHOOK_HANDLE_LABEL, tuple(link_ids))


@celery_app.task(name="incident.tasks.ingest_official_posts")
def ingest_official_posts() -> dict[str, Any]:
    """Ingest new official X posts for every tracked handle.

    Three env guards come first and all no-op without writing anything or making
    a request: ``OFFICIAL_POST_INGESTION_ENABLED`` (the kill switch — flipping it
    is the only thing needed to stop or start ingestion),
    ``OFFICIAL_POST_POLLING_ENABLED`` (polling is opt-in; the webhook path is
    primary, so this task additionally refuses to run unless polling is enabled)
    and ``X_API_BEARER_TOKEN`` (the X API's free tier cannot read, so a paid
    token is required; there is deliberately no fallback source). A missing
    system author is *not* swallowed — a misconfigured database should be loud.

    Returns a totals dict, ``{"skipped": ...}`` when a guard tripped.
    """
    if not settings.OFFICIAL_POST_INGESTION_ENABLED:
        logger.info(
            "Official post ingestion is disabled "
            "(OFFICIAL_POST_INGESTION_ENABLED=false); nothing fetched or written"
        )
        return {"skipped": "disabled"}

    if not settings.OFFICIAL_POST_POLLING_ENABLED:
        logger.info(
            "Official post polling is disabled "
            "(OFFICIAL_POST_POLLING_ENABLED=false); nothing fetched or written"
        )
        return {"skipped": "polling_disabled"}

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
