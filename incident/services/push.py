"""Web push: FCM token subscriptions per line, and MAJOR-incident alerts."""

import logging
from collections import Counter
from collections.abc import Iterable

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from firebase_admin import messaging

from common.models import User
from incident.enums import CalendarIncidentSeverity, CalendarIncidentStatus
from incident.models import CalendarIncident, PushSubscription
from operation.models import Line

from .errors import PushSubscriptionValidationError

logger = logging.getLogger(__name__)

#: Not FCM's limit: the unique btree index on ``token`` refuses a row over
#: 2704 bytes with a raw OperationalError, so the cap sits safely below it.
#: ASCII-only keeps characters equal to bytes (FCM tokens are ASCII).
MAX_TOKEN_LENGTH = 2048
#: At most one push per line per this many seconds (``notify_major_incident``).
COOLDOWN_SECONDS = 30 * 60
#: ``send_each_for_multicast`` refuses more tokens than this in one call.
FCM_MULTICAST_LIMIT = 500
#: FCM's verdicts that mean "this token will never work again".
STALE_TOKEN_ERRORS = (messaging.UnregisteredError, messaging.SenderIdMismatchError)


def _clean_token(token: str) -> str:
    token = token.strip()
    if not token or len(token) > MAX_TOKEN_LENGTH or not token.isascii():
        raise PushSubscriptionValidationError(
            f"token must be 1 to {MAX_TOKEN_LENGTH} ASCII characters."
        )
    return token


def _clean_line_ids(line_ids: Iterable[int | str]) -> set[int]:
    try:
        return {int(line_id) for line_id in line_ids}
    except (TypeError, ValueError) as exc:
        raise PushSubscriptionValidationError(
            "lineIds must be numeric line ids."
        ) from exc


async def register(
    user: User, token: str, line_ids: Iterable[int | str]
) -> PushSubscription:
    """Upsert ``token`` for ``user`` and replace its lines.

    A token already registered by another account is re-owned by the caller:
    the browser that holds it is the caller's now, and FCM would deliver
    pushes for the old account's lines to it otherwise.
    """
    token = _clean_token(token)
    ids = _clean_line_ids(line_ids)

    def _sync() -> PushSubscription:
        with transaction.atomic():
            known = set(Line.objects.filter(pk__in=ids).values_list("pk", flat=True))
            if missing := sorted(ids - known):
                raise PushSubscriptionValidationError(
                    f"Unknown line ids: {', '.join(map(str, missing))}."
                )
            subscription, _ = PushSubscription.objects.update_or_create(
                token=token, defaults={"user": user}
            )
            subscription.lines.set(ids)
            return subscription

    return await sync_to_async(_sync)()


async def unregister(user: User, token: str) -> None:
    """Delete the caller's row for ``token``; another account's row is untouched."""
    await PushSubscription.objects.filter(user=user, token=token.strip()).adelete()


async def get_subscription(user: User, token: str) -> PushSubscription | None:
    """The caller's own subscription for ``token`` (lines prefetched), or None."""
    return (
        await PushSubscription.objects.filter(user=user, token=token.strip())
        .prefetch_related("lines")
        .afirst()
    )


def _cooldown_key(line_id: int) -> str:
    return f"push:line:{line_id}:cooldown"


def notify_major_incident(incident_id: int) -> int:
    """Push a LIVE MAJOR incident to its lines' subscribers; return messages sent.

    Anything else (missing, soft-deleted, not LIVE, not MAJOR) sends nothing.
    Each line pushes at most once per ``COOLDOWN_SECONDS``: ``cache.add`` is an
    atomic claim, so two concurrent approvals on one line send once. A line in
    its cooldown is skipped, and a subscriber of several affected lines gets one
    message. Local ``DEBUG=True`` swaps the cache for ``DummyCache``, whose
    ``add`` always succeeds, so the cooldown never limits there.

    Tokens FCM reports as unregistered or bound to another sender are deleted.
    Other per-token failures are logged and kept. A raised error (the whole call
    failed) releases this run's claims, so the task's retry can send again.
    """
    incident = CalendarIncident.objects.filter(pk=incident_id).first()
    if (
        incident is None
        or incident.status != CalendarIncidentStatus.LIVE
        or incident.severity != CalendarIncidentSeverity.MAJOR
    ):
        return 0

    lines = list(incident.lines.all())
    claimed = [
        line.pk
        for line in lines
        if cache.add(_cooldown_key(line.pk), 1, timeout=COOLDOWN_SECONDS)
    ]
    if not claimed:
        return 0

    tokens = list(
        PushSubscription.objects.filter(lines__in=claimed)
        .values_list("token", flat=True)
        .distinct()
    )
    codes = ", ".join(line.code for line in lines)
    notification = messaging.Notification(
        title=f"{codes}: {incident.title}"[:100],
        body=incident.brief[:150],
    )
    webpush = messaging.WebpushConfig(
        fcm_options=messaging.WebpushFCMOptions(
            # FCM rejects a link that is not https://.
            link=f"{settings.FRONTEND_BASE_URL}/insiden/{incident.start_datetime:%Y-%m-%d}"
        )
    )

    sent = 0
    failures: Counter[str] = Counter()
    try:
        for start in range(0, len(tokens), FCM_MULTICAST_LIMIT):
            # shortcut: a failure after an earlier chunk went out re-sends that
            # chunk on retry; track sent tokens if one incident exceeds 500.
            chunk = tokens[start : start + FCM_MULTICAST_LIMIT]
            batch = messaging.send_each_for_multicast(
                messaging.MulticastMessage(
                    tokens=chunk, notification=notification, webpush=webpush
                )
            )
            sent += batch.success_count
            stale = []
            for token, response in zip(chunk, batch.responses):
                if response.success:
                    continue
                if isinstance(response.exception, STALE_TOKEN_ERRORS):
                    stale.append(token)
                else:
                    failures[type(response.exception).__name__] += 1
            if stale:
                PushSubscription.objects.filter(token__in=stale).delete()
    except Exception:
        cache.delete_many([_cooldown_key(line_id) for line_id in claimed])
        raise

    if failures:
        logger.warning(
            "Push for incident %s: %d deliveries failed and were kept (%s)",
            incident_id,
            sum(failures.values()),
            dict(failures),
        )
    return sent
