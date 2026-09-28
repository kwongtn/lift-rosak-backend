"""X (Twitter) Activity API webhook receive primitives.

The **primary** ingestion path for official operator posts. Polling
(``OFFICIAL_POST_POLLING_ENABLED``) is the opt-in fallback; this module is what
X pushes to, and it is deliberately importable without an HTTP request object so
the signing, CRC and payload-parsing logic is unit-testable on its own.

Three responsibilities, no fourth:

* **CRC challenge** — ``GET /webhooks/x-api?crc_token=…``. X validates a
  registered webhook by asking us to sign its challenge; the answer is the same
  HMAC used for delivery signatures.
* **Delivery signature** — ``POST /webhooks/x-api`` carries the signature of the
  **raw request bytes** in ``X-Twitter-Webhooks-Signature-OAuth2`` (OAuth 2.0
  client secret) or the legacy ``X-Twitter-Webhooks-Signature`` (OAuth 1.0
  consumer secret). Verification therefore takes ``bytes``; re-serializing the
  parsed JSON to recompute a digest would silently break the moment X changes
  its key order, so it never happens.
* **Payload ingest** — ``post.create`` events (Activity API) and the deprecated
  ``tweet_create_events`` (AAA) shape, mapped through the *same*
  ``tweet_to_raw_post`` / ``ingest_posts`` path the polling task uses, so a post
  that arrives by webhook and one that arrives by poll produce byte-identical
  rows.

Two X platform facts shape the code. (a) The **App-only bearer token is never
used here** — it authorises outbound API calls, not webhook verification; the
signing secret is the OAuth 2.0 client secret or the OAuth 1.0 consumer secret.
(b) X retries and redelivers, so ingest is idempotent on ``(platform, post_id)``
and an unresolvable handle is counted and dropped rather than guessed at.
"""

import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Mapping

from django.conf import settings

from .errors import OfficialPostFetchError
from .official_posts import (
    get_system_author,
    ingest_posts,
    resolve_handle_for_user_id,
    tweet_to_raw_post,
)

logger = logging.getLogger(__name__)

#: The only signing algorithm X uses. Kept as a constant because it is part of
#: the wire contract (``sha256=<base64>``), not an implementation detail.
SIGNATURE_ALGORITHM = "sha256"

#: ``(header name, settings attribute)`` pairs tried in order. Both may be
#: configured at once: X signs with the OAuth 2.0 client secret by default and
#: falls back to the OAuth 1.0 consumer secret, so accepting either configured
#: one keeps delivery working across a half-migrated app. A candidate is only
#: tried when *both* its header is present and its secret is configured — an
#: unconfigured candidate can never authenticate anything, and comparing
#: against an empty secret would accept a signature anyone can compute.
SIGNATURE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("X-Twitter-Webhooks-Signature-OAuth2", "X_API_OAUTH2_CLIENT_SECRET"),
    ("X-Twitter-Webhooks-Signature", "X_API_SECRET_KEY"),
)

#: The one event type this app acts on. ``post.delete`` and every other
#: ``*.create`` / ``*.delete`` type is acknowledged and ignored: the endpoint
#: must 200 quickly, and an unknown event type is not an error worth a retry.
EVENT_POST_CREATE = "post.create"


@dataclass(frozen=True, slots=True)
class WebhookIngestResult:
    """Outcome of one webhook delivery.

    The counters satisfy ``ingested + skipped + unresolved == events``: every
    create event X delivered is accounted for exactly once, so a redelivery that
    creates nothing is visible as ``ingested=0`` rather than as silence.
    ``created_ids`` holds the pks of the newly created rows, which is what the
    view hands to the queued Telegram notification.
    """

    events: int
    # Rows actually created (the ``(platform, post_id)`` check found no twin).
    ingested: int
    # Already present, a duplicate URL, or too malformed to map.
    skipped: int
    # The author is not one of the tracked handles; dropped, never guessed at.
    unresolved: int
    created_ids: tuple[int, ...] = ()


def sign_body(secret: str, body: bytes) -> str:
    """Return ``sha256=<base64(HMAC-SHA256(secret, body))>``.

    Used for both the CRC challenge response and delivery-signature
    verification, because X specifies the same construction for each. ``body``
    is bytes on purpose: the digest covers the exact octets X sent.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return f"{SIGNATURE_ALGORITHM}={base64.b64encode(digest).decode('ascii')}"


def has_signing_secret() -> bool:
    """True when at least one webhook signing secret is configured.

    Lets the view answer 503 (misconfiguration) instead of raising, which keeps
    the operator-facing error honest and specific.
    """
    return any(
        (getattr(settings, attribute, "") or "").strip()
        for _header, attribute in SIGNATURE_CANDIDATES
    )


def _preferred_signing_secret() -> str:
    """The secret X itself signs with: OAuth 2.0 client secret, else legacy.

    Raises ``OfficialPostFetchError`` when neither is configured — the CRC
    challenge cannot be answered without one, and returning a token signed with
    an empty key would just produce a confusing ``CrcValidationFailed`` upstream.
    """
    for _header, attribute in SIGNATURE_CANDIDATES:
        secret = (getattr(settings, attribute, "") or "").strip()
        if secret:
            return secret
    raise OfficialPostFetchError(
        "no X webhook signing secret is configured; set "
        "X_API_OAUTH2_CLIENT_SECRET (preferred) or X_API_SECRET_KEY"
    )


def crc_response_token(crc_token: str) -> str:
    """Sign X's CRC challenge, answering the webhook-validation ``GET``.

    The challenge is signed with the *configured preferred* secret, which is why
    the OAuth 2.0 client secret must be set when the app has one: that is the
    secret X verifies the answer against.
    """
    return sign_body(_preferred_signing_secret(), crc_token.encode("utf-8"))


def verify_webhook_signature(headers: Mapping[str, str], raw_body: bytes) -> bool:
    """True when any *configured* signature candidate matches ``raw_body``.

    Header lookup is case-insensitive (HTTP header names are). The comparison is
    constant-time and is made over the raw bytes — never over a re-serialized
    copy of the parsed JSON. Returns ``False`` when nothing is configured or no
    known header is present: an unverifiable delivery is refused, and the caller
    decides whether that is a 403.

    Header *values* are never logged, not even on failure: the signature is a
    credential-adjacent artefact and this repo's rule is that secrets stay out of
    logs entirely.
    """
    provided = {str(name).lower(): str(value) for name, value in headers.items()}
    for header, attribute in SIGNATURE_CANDIDATES:
        secret = (getattr(settings, attribute, "") or "").strip()
        if not secret:
            continue
        candidate = provided.get(header.lower(), "").strip()
        if not candidate:
            continue
        # Both sides as UTF-8 bytes: compare_digest rejects str containing
        # non-ASCII, and a hostile header must not turn a 403 into a 500.
        expected = sign_body(secret, raw_body).encode("utf-8")
        if hmac.compare_digest(expected, candidate.encode("utf-8")):
            return True
    return False


def _create_items(payload: Mapping[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Pull the ``post.create`` (or legacy ``tweet_create_events``) posts out.

    Returns ``(post object, user-id hint)`` pairs. The hint is the subscription
    filter's ``user_id`` (Activity API) or ``for_user_id`` (AAA) and is only a
    *fallback* for resolving the handle — ``payload.author_id`` wins, because a
    reply by another account carries the tracked account in the filter but a
    different author, and attributing that reply to the tracked handle would
    write a wrong permalink.

    Non-``post.create`` event types yield an empty list and are debug-logged:
    the caller still answers 200 so X does not retry an event we will never act
    on.
    """
    data = payload.get("data")
    if isinstance(data, dict):
        event_type = str(data.get("event_type") or "")
        if event_type != EVENT_POST_CREATE:
            logger.debug("ignoring X webhook event_type=%r", event_type)
            return []
        post = data.get("payload")
        if not isinstance(post, dict):
            logger.warning("a post.create webhook event carried no post payload")
            return []
        event_filter = data.get("filter")
        hint = ""
        if isinstance(event_filter, dict):
            hint = str(event_filter.get("user_id") or "").strip()
        return [(post, hint)]

    # Deprecated AAA shape: no "data" envelope at all.
    events = payload.get("tweet_create_events")
    if isinstance(events, list):
        hint = str(payload.get("for_user_id") or "").strip()
        return [(event, hint) for event in events if isinstance(event, dict)]
    return []


def _usernames_by_id(payload: Mapping[str, Any]) -> dict[str, str]:
    """``includes.users`` flattened to ``{user id: username}``.

    This is the zero-network path to the post author's handle, and it is the
    only source trusted for attribution: an expansion is delivered inside the
    signed body, so it cannot be forged without the signing secret.
    """
    includes = payload.get("includes")
    users = includes.get("users") if isinstance(includes, dict) else None
    if not isinstance(users, list):
        return {}
    mapping: dict[str, str] = {}
    for user in users:
        if not isinstance(user, dict):
            continue
        user_id = str(user.get("id") or "").strip()
        username = str(user.get("username") or "").strip().lstrip("@")
        if user_id and username:
            mapping[user_id] = username
    return mapping


def _resolve_handle(
    post: Mapping[str, Any], usernames: Mapping[str, str], hint: str
) -> str | None:
    """The tracked handle that authored ``post``, or ``None`` if untracked.

    ``includes.users`` first (no network), then a bounded reverse lookup over
    ``OFFICIAL_POST_HANDLES``. An untracked author is never attributed to some
    other handle: a permalink built from the wrong account is worse than a
    dropped post, and the post is still retrievable by the polling fallback.
    """
    author_id = str(post.get("author_id") or post.get("user_id") or "").strip()
    handle = usernames.get(author_id) if author_id else None
    if handle:
        return handle
    target = author_id or hint
    if not target:
        return None
    return resolve_handle_for_user_id(target)


def ingest_webhook_payload(payload: dict[str, Any]) -> WebhookIngestResult:
    """Ingest one webhook delivery; returns the per-event accounting.

    Reads both the current Activity API shape and the deprecated AAA shape, maps
    each post through the shared ``tweet_to_raw_post`` and hands the posts to the
    shared ``ingest_posts`` — so idempotency on ``(platform, post_id)`` is
    structural, not re-implemented. A redelivery therefore creates nothing and
    contributes only to ``skipped``.

    Raises ``OfficialPostFetchError`` when the payload is not a JSON object and
    ``OfficialPostIngestError`` (from ``get_system_author``) when the system
    author row is missing — a deployment fault, which the caller surfaces rather
    than swallowing.
    """
    if not isinstance(payload, dict):
        raise OfficialPostFetchError("webhook payload was not a JSON object")

    items = _create_items(payload)
    events = len(items)
    if not events:
        return WebhookIngestResult(
            events=0, ingested=0, skipped=0, unresolved=0, created_ids=()
        )

    usernames = _usernames_by_id(payload)
    grouped: dict[str, list[dict[str, Any]]] = {}
    unresolved = 0
    skipped = 0

    for post, hint in items:
        handle = _resolve_handle(post, usernames, hint)
        if not handle:
            unresolved += 1
            logger.warning(
                "X webhook post %s has no tracked handle; dropping it rather than "
                "attributing it to the wrong account",
                post.get("id"),
            )
            continue
        if not str(post.get("id") or "").strip():
            # Same rule as the live fetch: one malformed post must not discard
            # the rest of the delivery.
            skipped += 1
            logger.warning("skipping a webhook post with no usable id")
            continue
        grouped.setdefault(handle, []).append(post)

    if not grouped:
        return WebhookIngestResult(
            events=events, ingested=0, skipped=skipped, unresolved=unresolved
        )

    author = get_system_author()
    ingested = 0
    created_ids: list[int] = []
    for handle, posts in grouped.items():
        raw_posts = [tweet_to_raw_post(post, handle) for post in posts]
        summary = ingest_posts(raw_posts, handle=handle, author=author)
        ingested += summary.created
        skipped += summary.skipped + summary.duplicate_urls
        created_ids.extend(summary.created_ids)

    return WebhookIngestResult(
        events=events,
        ingested=ingested,
        skipped=skipped,
        unresolved=unresolved,
        created_ids=tuple(created_ids),
    )
