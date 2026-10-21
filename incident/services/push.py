"""Web push: FCM token subscriptions per line, and MAJOR-incident alerts."""

import logging
from collections import Counter
from collections.abc import Iterable

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from firebase_admin import exceptions, messaging

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
#: Tokens one account may hold; ``register`` evicts the least recently
#: registered beyond it, so a script cannot grow the table (or every fan-out).
MAX_TOKENS_PER_USER = 20
#: Distinct ``lineIds`` one registration may carry (the network has ~16 lines).
MAX_LINE_IDS = 100
#: At most one push per line per this many seconds (``notify_major_incident``).
COOLDOWN_SECONDS = 30 * 60
#: ``send_each_for_multicast`` refuses more tokens than this in one call.
FCM_MULTICAST_LIMIT = 500
#: FCM's verdicts that mean "this token will never work again".
STALE_TOKEN_ERRORS = (messaging.UnregisteredError, messaging.SenderIdMismatchError)
#: FCM's "try again later" verdicts (503 or no connection, 500, 429, timeout).
#: ``QuotaExceededError`` is a ``ResourceExhaustedError``.
TRANSIENT_ERRORS = (
    exceptions.UnavailableError,
    exceptions.InternalError,
    exceptions.ResourceExhaustedError,
    exceptions.DeadlineExceededError,
)


def _clean_token(token: str) -> str:
    token = token.strip()
    if not token or len(token) > MAX_TOKEN_LENGTH or not token.isascii():
        raise PushSubscriptionValidationError(
            f"token must be 1 to {MAX_TOKEN_LENGTH} ASCII characters."
        )
    return token


def _clean_line_ids(line_ids: Iterable[int | str]) -> set[int]:
    try:
        ids = {int(line_id) for line_id in line_ids}
    except (TypeError, ValueError) as exc:
        raise PushSubscriptionValidationError(
            "lineIds must be numeric line ids."
        ) from exc
    if len(ids) > MAX_LINE_IDS:
        raise PushSubscriptionValidationError(
            f"lineIds must hold at most {MAX_LINE_IDS} distinct ids."
        )
    return ids


async def register(
    user: User, token: str, line_ids: Iterable[int | str]
) -> PushSubscription:
    """Upsert ``token`` for ``user`` and replace its lines.

    A token already registered by another account is re-owned by the caller:
    the browser that holds it is the caller's now, and FCM would deliver
    pushes for the old account's lines to it otherwise. Past
    ``MAX_TOKENS_PER_USER`` the caller's least recently registered tokens are
    deleted: browsers it no longer uses, since a live one re-registers.
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
            evicted = (
                PushSubscription.objects.filter(user=user)
                .exclude(pk=subscription.pk)
                .order_by("-modified", "-pk")
                .values_list("pk", flat=True)[MAX_TOKENS_PER_USER - 1 :]
            )
            PushSubscription.objects.filter(pk__in=list(evicted)).delete()
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
    atomic claim, so two concurrent approvals on one line send once. Only lines
    with subscribers are claimed. A line in its cooldown is skipped, and a
    subscriber of several affected lines gets one message. Local ``DEBUG=True``
    swaps the cache for ``DummyCache``, whose ``add`` always succeeds, so the
    cooldown never limits there.

    Tokens FCM reports as unregistered or bound to another sender are deleted,
    and so is one it calls an invalid argument while another message in the
    same chunk was delivered. Other per-token failures are logged and kept.
    ``send_each_for_multicast`` returns an FCM outage per token instead of
    raising it, so a chunk that delivered nothing and saw a transient error
    raises ``UnavailableError``. Any raise releases this run's claims, so the
    task's retry can send again.
    """
    incident = CalendarIncident.objects.filter(pk=incident_id).first()
    if (
        incident is None
        or incident.status != CalendarIncidentStatus.LIVE
        or incident.severity != CalendarIncidentSeverity.MAJOR
    ):
        return 0

    lines = list(incident.lines.all())
    # A claim on a line nobody follows would mute it for a new subscriber.
    subscribed = (
        incident.lines.filter(push_subscriptions__isnull=False)
        .values_list("pk", flat=True)
        .distinct()
    )
    claimed = [
        line_id
        for line_id in subscribed
        if cache.add(_cooldown_key(line_id), 1, timeout=COOLDOWN_SECONDS)
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
                error = response.exception
                # One payload per chunk: INVALID_ARGUMENT beside a delivered
                # message blames the token; with none delivered it may be ours.
                if isinstance(error, STALE_TOKEN_ERRORS) or (
                    batch.success_count
                    and isinstance(error, exceptions.InvalidArgumentError)
                ):
                    stale.append(token)
                else:
                    failures[type(error).__name__] += 1
            if stale:
                PushSubscription.objects.filter(token__in=stale).delete()
            # shortcut: transient failures beside a delivered message are only
            # logged; retry just those tokens if the logs show partial throttling.
            if not batch.success_count and any(
                isinstance(r.exception, TRANSIENT_ERRORS) for r in batch.responses
            ):
                raise exceptions.UnavailableError(
                    f"FCM delivered none of {len(chunk)} messages: {dict(failures)}"
                )
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
