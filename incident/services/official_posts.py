"""Fetch and ingest official operator posts (X/Twitter) into the feed.

Phase 1 of OFFICIAL_POST_INGESTION.md. The rows land in the existing
``SocialMediaLink`` table so the moderation queue, votes, console UI and the
Phase 2 Telegram approval flow all key on one model — there is no separate post
table (decision D1).

Two halves, both plain synchronous functions because they run inside a Celery
worker rather than an async resolver:

* fetching — one call to the official X API v2 (``GET /2/users/by/username/
  {handle}`` for the id, then ``GET /2/users/{id}/tweets``). No public-scrape
  fallback and no adapter protocol (decision D2). ``load_fixture_posts`` parses
  a saved payload of the same shape so tests and offline dev never need a token.
* ingesting — ``ingest_posts`` is idempotent per ``(platform, post_id)``, backed
  by a partial unique constraint on the model plus a best-effort
  ``normalized_url`` check, and creates rows ``PENDING_APPROVAL`` because
  approval is the publish gate (decision D4).

Deliberate non-goals: no post classification, no cross-account content folding,
no retries (the 5-minute beat tick *is* the retry), and no bare ``assert`` —
every failure is an explicit exception in ``.errors``.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, models, transaction
from django.db.models import Max
from django.db.models.functions import Cast

from common.models import User
from incident.enums import IngestPlatform, SocialMediaLinkStatus
from incident.models import SocialMediaLink

from .errors import OfficialPostFetchError, OfficialPostIngestError
from .urls import canonicalize_url

logger = logging.getLogger(__name__)

X_API_BASE = "https://api.x.com/2"
X_USER_LOOKUP_URL = f"{X_API_BASE}/users/by/username"
X_TWEETS_URL = f"{X_API_BASE}/users"

#: Explicit request timeout. A hung socket must not pin a Celery worker.
HTTP_TIMEOUT_SECONDS = 10
#: Pagination follows ``next_token`` only while both this cap and the caller's
#: ``limit`` allow another page. Bounded work is a repo rule: a month of posts
#: is not one request, and "until exhausted" is not a budget either.
_MAX_PAGES = 10
#: X rejects ``max_results`` above 100 on the tweets endpoint.
_MAX_RESULTS_PER_REQUEST = 100
#: ``SocialMediaLink.title`` is a CharField(256); longer post text is truncated
#: there while ``description`` keeps the verbatim text.
TITLE_MAX_LENGTH = 256
#: Namespaced cache prefix for resolved user ids. The mapping is effectively
#: immutable, so the timeout is None (cache until evicted). Locally DEBUG swaps
#: in DummyCache, which simply re-resolves — correctness never depends on it.
_USER_ID_CACHE_PREFIX = "incident:official_posts:user_id"
#: Reverse direction of the above, for webhook payloads that only carry a numeric
#: ``author_id``. Same immutability argument, same "never cache a negative" rule.
_HANDLE_FOR_USER_ID_CACHE_PREFIX = "incident:official_posts:handle_for_user_id"
#: Author of every automatically ingested row; seeded by the data migration.
SYSTEM_AUTHOR_FIREBASE_ID = "system:official-ingest"


@dataclass(frozen=True, slots=True)
class RawPost:
    """One provider post, normalized but otherwise untouched.

    ``text`` is verbatim (never translated or normalized) and ``raw`` is the
    provider's own object, persisted as ``raw_payload`` for export fidelity.
    """

    platform: str
    post_id: str
    handle: str
    text: str
    posted_at: datetime
    url: str
    has_media: bool
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IngestSummary:
    """Outcome of one ``ingest_posts`` run.

    ``created_ids`` holds the pk of every newly created row so the Phase 2
    notification pass can re-query them instead of re-walking the queryset.
    """

    fetched: int
    created: int
    # Already present under the same (platform, post_id).
    skipped: int
    # Matched an existing normalized_url (e.g. a human submitted the same link).
    duplicate_urls: int
    created_ids: tuple[int, ...] = ()


def _auth_headers() -> dict[str, str]:
    """Bearer auth header for the X API.

    The token is only ever read here and never interpolated into a log line,
    an exception message or a GraphQL response.
    """
    return {"Authorization": f"Bearer {settings.X_API_BEARER_TOKEN}"}


def _get_json(
    url: str, *, params: dict[str, Any], headers: dict[str, str], context: str
) -> dict[str, Any]:
    """GET ``url`` and return the decoded JSON object.

    Every failure mode collapses into ``OfficialPostFetchError`` with a
    sanitized reason (status code or exception class only). The raw upstream
    body is never propagated: it can echo request details, and callers log
    these messages verbatim.
    """
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise OfficialPostFetchError(
            f"{context}: request timed out after {HTTP_TIMEOUT_SECONDS}s"
        ) from None
    except requests.RequestException as exc:
        raise OfficialPostFetchError(
            f"{context}: request failed ({type(exc).__name__})"
        ) from None

    status = response.status_code
    if not 200 <= status < 300:
        raise OfficialPostFetchError(f"{context}: HTTP {status}")

    try:
        payload = response.json()
    except ValueError:
        raise OfficialPostFetchError(
            f"{context}: response was not valid JSON"
        ) from None
    if not isinstance(payload, dict):
        raise OfficialPostFetchError(f"{context}: response JSON was not an object")
    return payload


def _parse_created_at(raw: str) -> datetime:
    """Parse an X ``created_at`` (``...Z``) into a timezone-aware datetime.

    The trailing ``Z`` is rewritten as an explicit UTC offset so the call works
    on any supported Python version rather than relying on 3.11+ ``fromisoformat``
    Z support. A missing or malformed value falls back to "now" (still
    timezone-aware) so one odd post cannot abort a whole ingest run.
    """
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        logger.warning("official post has an unparseable created_at; using now()")
        return datetime.now().astimezone()
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def _has_media(tweet: dict[str, Any]) -> bool:
    """True when the tweet object carries any media reference.

    The API only returns ``attachments`` when ``expansions=attachments.media_keys``
    is requested, so also treat a bare ``media_keys`` entry as media. Plain
    truthiness is intentional: an empty list means no media.
    """
    return bool(tweet.get("attachments")) or bool(tweet.get("media_keys"))


def tweet_to_raw_post(tweet: dict[str, Any], handle: str) -> RawPost:
    """Map one provider tweet object onto a :class:`RawPost`.

    Shared by the live fetch, the fixture loader **and** the webhook parser
    (``services/x_webhooks.py``) so all three produce identical rows from the
    same provider object; tweets without a usable id are skipped by the caller.
    """
    post_id = str(tweet.get("id") or "").strip()
    if not post_id:
        raise OfficialPostFetchError(
            f"handle={handle}: a tweet in the payload has no id"
        )
    return RawPost(
        platform=IngestPlatform.X,
        post_id=post_id,
        handle=handle,
        # Verbatim, byte for byte: BM post text is never translated or cleaned.
        text=str(tweet.get("text") or ""),
        posted_at=_parse_created_at(tweet.get("created_at") or ""),
        url=f"https://x.com/{handle}/status/{post_id}",
        has_media=_has_media(tweet),
        raw=tweet,
    )


def _resolve_user_id(handle: str) -> str:
    """Return the X user id for ``handle``, lazily and cached.

    Never hardcoded: the id is looked up once and cached under a namespaced key
    with no timeout, since a handle's numeric id is effectively immutable.
    """
    cache_key = f"{_USER_ID_CACHE_PREFIX}:{handle}"
    cached = cache.get(cache_key)
    if cached:
        return str(cached)

    context = f"X API error for handle={handle} (user lookup)"
    payload = _get_json(
        f"{X_USER_LOOKUP_URL}/{handle}",
        params={"user.fields": "id"},
        headers=_auth_headers(),
        context=context,
    )
    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("id"):
        raise OfficialPostFetchError(f"{context}: response carried no user id")

    user_id = str(data["id"])
    cache.set(cache_key, user_id, timeout=None)
    return user_id


def resolve_handle_for_user_id(user_id: str) -> str | None:
    """Map an X numeric user id back to one of our tracked handles, or ``None``.

    The webhook payload normally carries ``includes.users[].username``, which
    answers this with no network at all; this is the fallback for when it does
    not. It walks ``settings.OFFICIAL_POST_HANDLES`` and compares against
    ``_resolve_user_id(handle)``, so the bounded work is the number of tracked
    handles (two today) and the answers are already cached per handle.

    A lookup failure for one handle is caught and logged (a 429 or a transient
    5xx must not abort the remaining handles), and ``None`` is returned when no
    tracked handle matches — a post from an untracked account is not ingested
    with an invented handle, because that would write a wrong permalink and a
    wrong ``source_handle``. Only a positive match is cached, so widening
    ``OFFICIAL_POST_HANDLES`` later does not need a cache flush.
    """
    if not user_id:
        return None

    cache_key = f"{_HANDLE_FOR_USER_ID_CACHE_PREFIX}:{user_id}"
    cached = cache.get(cache_key)
    if cached:
        return str(cached)

    for handle in settings.OFFICIAL_POST_HANDLES:
        try:
            resolved = _resolve_user_id(handle)
        except OfficialPostFetchError as exc:
            logger.warning(
                "handle lookup failed for handle=%s while resolving user_id=%s: %s",
                handle,
                user_id,
                exc,
            )
            continue
        if resolved == str(user_id):
            cache.set(cache_key, handle, timeout=None)
            return handle
    return None


def fetch_user_posts(
    handle: str,
    *,
    since_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 10,
    # Retweets are KEPT by default: dropping them silently would hide posts the
    # operator actually published. Callers that want the "originals only" view
    # (e.g. a quiet-window query) opt in explicitly.
    exclude_retweets: bool = False,
) -> list[RawPost]:
    """Fetch up to ``limit`` most recent posts for ``handle`` from the X API.

    ``since_id`` is the cheap incremental filter (only genuinely new posts are
    billed); ``start_time`` / ``end_time`` are the backfill window. Both are
    applied inside the endpoint's ~3,200-post window, so an older ``start_time``
    cannot be honoured — the manual command says so rather than pretending.

    Raises ``OfficialPostFetchError`` on any transport, status or decode
    failure, with a sanitized reason.
    """
    if limit <= 0:
        return []

    user_id = _resolve_user_id(handle)
    collected: list[RawPost] = []
    pagination_token: str | None = None

    for _page in range(_MAX_PAGES):
        remaining = limit - len(collected)
        if remaining <= 0:
            break
        params: dict[str, Any] = {
            "tweet.fields": "created_at,public_metrics",
            "max_results": min(_MAX_RESULTS_PER_REQUEST, remaining),
        }
        if since_id:
            params["since_id"] = since_id
        if start_time is not None:
            params["start_time"] = start_time.isoformat()
        if end_time is not None:
            params["end_time"] = end_time.isoformat()
        if exclude_retweets:
            params["exclude"] = "retweets"
        if pagination_token:
            params["pagination_token"] = pagination_token

        context = f"X API error for handle={handle}"
        payload = _get_json(
            f"{X_TWEETS_URL}/{user_id}/tweets",
            params=params,
            headers=_auth_headers(),
            context=context,
        )
        data = payload.get("data")
        if data is None:
            break
        if not isinstance(data, list):
            raise OfficialPostFetchError(f"{context}: 'data' was not a list")

        for tweet in data:
            if not isinstance(tweet, dict):
                continue
            if len(collected) >= limit:
                break
            try:
                collected.append(tweet_to_raw_post(tweet, handle))
            except OfficialPostFetchError:
                # One malformed tweet must not discard the rest of the page.
                logger.warning("skipping a malformed tweet for handle=%s", handle)

        pagination_token = (payload.get("meta") or {}).get("next_token")
        if not pagination_token:
            break

    return collected


def load_fixture_posts(path: str, *, handle: str | None = None) -> list[RawPost]:
    """Parse a saved API-shaped payload (``{"data": [...], "meta": {...}}``).

    Used by the manual command's ``--fixture`` flag and by tests, so the ingest
    path can be exercised end to end with no token and no network. Raises
    ``OfficialPostFetchError`` on a missing file, unreadable file or unparseable
    JSON so a typo fails loudly instead of silently ingesting nothing.

    ``handle`` overrides the account the posts are attributed to. The X tweets
    response never echoes which account it came from, so a saved payload has to
    record it in a top-level ``handle`` (or ``username``/``source_handle``) key;
    when neither is present this raises rather than inventing a handle and
    producing wrong permalinks.
    """
    fixture_path = Path(path)
    try:
        raw_text = fixture_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OfficialPostFetchError(
            f"fixture {path} could not be read ({type(exc).__name__})"
        ) from None

    try:
        payload = json.loads(raw_text)
    except ValueError:
        raise OfficialPostFetchError(f"fixture {path} is not valid JSON") from None

    if not isinstance(payload, dict):
        raise OfficialPostFetchError(f"fixture {path} did not contain a JSON object")
    data = payload.get("data")
    if data is None:
        data = []
    if not isinstance(data, list):
        raise OfficialPostFetchError(f"fixture {path}: 'data' was not a list")

    resolved_handle = _resolve_fixture_handle(handle, payload, path)

    posts: list[RawPost] = []
    for tweet in data:
        if isinstance(tweet, dict):
            posts.append(tweet_to_raw_post(tweet, resolved_handle))
    return posts


def _resolve_fixture_handle(
    handle: str | None, payload: dict[str, Any], path: str
) -> str:
    """Pick the account handle for a saved payload: argument, then sidecar key.

    Failing loudly beats inventing a handle, which would silently write wrong
    permalinks and wrong ``source_handle`` values.
    """
    if handle and handle.strip():
        return handle.strip().lstrip("@")
    for key in ("handle", "username", "source_handle"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lstrip("@")
    raise OfficialPostFetchError(
        f"fixture {path} declares no handle; add a top-level 'handle' key or "
        "pass handle= explicitly"
    )


def ingest_posts(
    posts: list[RawPost],
    *,
    handle: str,
    author: User,
    dry_run: bool = False,
) -> IngestSummary:
    """Persist ``posts`` as ``SocialMediaLink`` rows, idempotently.

    Per post, in order: existing ``(platform, post_id)`` → skip; existing
    ``normalized_url`` → skip and count as a duplicate URL (the existing row is
    left alone and never upvoted by a system author); otherwise create. Each
    create runs in its own short ``transaction.atomic()`` so one bad post cannot
    roll back the batch, and an ``IntegrityError`` from the partial unique
    constraint is the race backstop.

    ``dry_run`` runs the same existence checks and counts what *would* be
    created (``created`` is therefore a projected count) but writes nothing, so a
    manual preview never has to create-then-delete. ``created_ids`` is empty in
    that mode, since no row exists to notify about.
    """
    created = 0
    skipped = 0
    duplicate_urls = 0
    created_ids: list[int] = []

    for post in posts:
        if SocialMediaLink.objects.filter(
            platform=post.platform, post_id=post.post_id
        ).first():
            skipped += 1
            continue

        normalized = canonicalize_url(post.url)
        if (
            normalized
            and SocialMediaLink.objects.filter(normalized_url=normalized).exists()
        ):
            # A human already submitted this link. Do not create a twin, do not
            # mutate the existing row, do not upvote from a system author.
            duplicate_urls += 1
            continue

        if dry_run:
            # Counted, not written — and deliberately before the transaction so
            # a preview touches no row at all.
            created += 1
            continue

        try:
            with transaction.atomic():
                link = SocialMediaLink.objects.create(
                    url=post.url,
                    # normalized_url is recomputed by the model's save().
                    title=post.text[:TITLE_MAX_LENGTH],
                    # Verbatim post text, never truncated.
                    description=post.text,
                    status=SocialMediaLinkStatus.PENDING_APPROVAL,
                    is_automated=True,
                    user=author,
                    platform=post.platform,
                    post_id=post.post_id,
                    posted_at=post.posted_at,
                    source_handle=handle,
                    raw_payload=post.raw,
                )
        except IntegrityError:
            # Lost a race against a concurrent tick: the other writer's row is
            # the real one, so count this post as skipped and move on.
            logger.info("post %s was ingested concurrently; skipping", post.post_id)
            skipped += 1
            continue

        created += 1
        created_ids.append(link.id)

    return IngestSummary(
        fetched=len(posts),
        created=created,
        skipped=skipped,
        duplicate_urls=duplicate_urls,
        created_ids=tuple(created_ids),
    )


def latest_post_id(handle: str) -> str | None:
    """Highest numeric post id stored for ``handle``, as a string.

    Feeds the X API's ``since_id`` so a 5-minute tick only bills genuinely new
    posts. ``post_id`` is a CharField, so a plain ``Max()`` would compare
    lexicographically ("9…" > "10…") — it is cast to a big integer first.
    Non-numeric ids (another platform, a manual row) cannot be cast, so they are
    filtered out rather than crashing the aggregate.
    """
    newest = (
        SocialMediaLink.objects.filter(
            source_handle=handle,
            platform=IngestPlatform.X,
            post_id__isnull=False,
        )
        # A non-numeric id would abort the whole aggregate on the cast. Rows
        # written by ingestion only ever hold snowflakes, but the column is
        # nullable CharField, so the guard is cheap on a handle's own rows.
        .filter(post_id__regex=r"^[0-9]+$")
        .aggregate(newest=Max(Cast("post_id", models.BigIntegerField())))["newest"]
    )
    return str(newest) if newest is not None else None


def get_system_author() -> User:
    """Return the seeded system ``common.User`` used as the post author.

    ``SocialMediaLink.user`` is non-null and automated ingestion has no human
    actor, so the row is created by the data migration in incident/migrations.
    Raises ``OfficialPostIngestError`` (not a fetch error — nothing upstream
    failed) when the seed is missing, e.g. a database migrated before it.
    """
    author = User.objects.filter(firebase_id=SYSTEM_AUTHOR_FIREBASE_ID).first()
    if author is None:
        raise OfficialPostIngestError(
            "system author "
            f"'{SYSTEM_AUTHOR_FIREBASE_ID}' is missing; run the incident "
            "migrations to seed it"
        )
    return author
