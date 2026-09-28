"""HTTP surfaces owned by ``incident``.

One view today: the X (Twitter) Activity API webhook receiver at
``/webhooks/x-api`` (registered in ``rosak/urls.py``). It is a plain synchronous
Django view, not DRF, because there is no authentication, no serializer and no
content negotiation to speak of — the two contracts X cares about are an HMAC
over the raw bytes and a fast 200.

Everything cryptographic and everything that touches the database lives in
``incident.services.x_webhooks`` / ``incident.services.official_posts``; this
module is only the transport: validate, delegate, acknowledge.

Status-code contract (X retries anything outside 2xx, and expects an answer
inside 10 seconds):

======  ======================================================================
GET     200 ``{"response_token": "sha256=…"}`` — the CRC challenge answer
        400 when ``crc_token`` is missing or empty
        503 when no signing secret is configured (an operator-fixable fault, not
             something X should retry)
POST    200 with per-event counts
        400 when the body is not a JSON object
        403 when the delivery signature is absent, unverifiable or wrong
        503 when ingestion is misconfigured (no signing secret / no system author)
405     any other method
======  ======================================================================

Two deliberate choices: the **ingestion master switch**
(``OFFICIAL_POST_INGESTION_ENABLED``) acknowledges with ``{"status": "ignored"}``
rather than erroring, because a switch that is *off* is not X's fault and a
retry storm would not help; and a **queued-notification failure still returns
200**, because the row is already committed and approvable from the console.
"""

import json
import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse

from incident.services.errors import (
    OfficialPostFetchError,
    OfficialPostIngestError,
)
from incident.services.x_webhooks import (
    crc_response_token,
    has_signing_secret,
    ingest_webhook_payload,
    verify_webhook_signature,
)
from incident.tasks import notify_official_post_links

logger = logging.getLogger(__name__)

#: Why the endpoint is refusing service, when it is. Actionable and free of any
#: secret, body or upstream detail.
_NO_SIGNING_SECRET_MESSAGE = (
    "X webhook signing is not configured; set X_API_OAUTH2_CLIENT_SECRET "
    "(preferred) or X_API_SECRET_KEY and restart the API"
)


def x_api_webhook(request: HttpRequest) -> JsonResponse:
    """Receive X webhooks: CRC validation on ``GET``, delivery on ``POST``."""
    if request.method == "GET":
        return _crc_challenge(request)
    if request.method == "POST":
        return _delivery(request)
    return JsonResponse(
        {"status": "error", "reason": "method not allowed"},
        status=405,
        # Without this, Django answers a 405 with an HTML body.
        headers={"Allow": "GET, POST"},
    )


def _crc_challenge(request: HttpRequest) -> JsonResponse:
    """Answer X's webhook-validation ``GET?crc_token=…``."""
    if not has_signing_secret():
        logger.error("%s", _NO_SIGNING_SECRET_MESSAGE)
        return JsonResponse(
            {"status": "error", "reason": "signing secret not configured"},
            status=503,
        )

    crc_token = (request.GET.get("crc_token") or "").strip()
    if not crc_token:
        return JsonResponse(
            {"status": "error", "reason": "crc_token is required"}, status=400
        )

    try:
        token = crc_response_token(crc_token)
    except OfficialPostFetchError as exc:
        # Only reachable if the secret was cleared between the check above and
        # the sign; a settings change under a live request.
        logger.error("X webhook CRC challenge could not be signed: %s", exc)
        return JsonResponse(
            {"status": "error", "reason": "signing secret not configured"},
            status=503,
        )

    return JsonResponse({"response_token": token})


def _delivery(request: HttpRequest) -> JsonResponse:
    """Verify and ingest one signed delivery, then acknowledge quickly."""
    if not has_signing_secret():
        logger.error("%s", _NO_SIGNING_SECRET_MESSAGE)
        return JsonResponse(
            {"status": "error", "reason": "signing secret not configured"},
            status=503,
        )

    # request.body is read exactly once and is the raw octets X signed. It is
    # never logged and never echoed.
    raw_body = request.body
    if not verify_webhook_signature(request.headers, raw_body):
        # One line, no detail: which header was wrong is not something a
        # prober learns from us.
        logger.warning(
            "rejected an X webhook delivery with a missing or invalid signature "
            "(body of %d bytes)",
            len(raw_body),
        )
        return JsonResponse(
            {"status": "error", "reason": "invalid signature"}, status=403
        )

    try:
        payload = json.loads(raw_body)
    except ValueError:
        logger.warning("rejected an X webhook delivery that was not valid JSON")
        return JsonResponse(
            {"status": "error", "reason": "body is not valid JSON"}, status=400
        )
    if not isinstance(payload, dict):
        logger.warning("rejected an X webhook delivery whose JSON was not an object")
        return JsonResponse(
            {"status": "error", "reason": "body is not a JSON object"}, status=400
        )

    if not settings.OFFICIAL_POST_INGESTION_ENABLED:
        # Acknowledged, not errored: ingestion being off is an operator
        # decision, and a non-2xx would only earn a retry storm.
        logger.info(
            "X webhook delivery acknowledged without ingesting: official post "
            "ingestion is disabled (OFFICIAL_POST_INGESTION_ENABLED=false)"
        )
        return JsonResponse(
            {"status": "ignored", "reason": "ingestion disabled"}, status=200
        )

    try:
        result = ingest_webhook_payload(payload)
    except OfficialPostFetchError as exc:
        logger.warning("X webhook payload was rejected: %s", exc)
        return JsonResponse(
            {"status": "error", "reason": "payload rejected"}, status=400
        )
    except OfficialPostIngestError as exc:
        # A missing system author is a deployment fault, so it is a 503 (X may
        # redeliver) rather than a silent 200 that drops the post.
        logger.error("X webhook delivery could not be ingested: %s", exc)
        return JsonResponse(
            {"status": "error", "reason": "ingest unavailable"}, status=503
        )

    if result.events == 0:
        logger.debug("X webhook delivery held no supported event; nothing to do")
        return JsonResponse(
            {
                "status": "ignored",
                "reason": "no supported event in payload",
                "events": 0,
            },
            status=200,
        )

    _enqueue_notification(result.created_ids)

    logger.info(
        "X webhook delivery ingested events=%s created=%s skipped=%s unresolved=%s",
        result.events,
        result.ingested,
        result.skipped,
        result.unresolved,
    )
    return JsonResponse(
        {
            "status": "ok",
            "events": result.events,
            "ingested": result.ingested,
            "skipped": result.skipped,
            "unresolved": result.unresolved,
        },
        status=200,
    )


def _enqueue_notification(created_ids: tuple[int, ...]) -> None:
    """Queue the Telegram admin notification; never send inline, never fail.

    X requires a 200 within 10 seconds, so the send is a Celery task. A broker
    outage must not cost us the post — the row is already committed and
    approvable from the console — so this is contained and logged, and the
    response is still a plain 200.
    """
    if not created_ids:
        return
    try:
        notify_official_post_links.delay(list(created_ids))
    except Exception as exc:  # boundary: broker down is not a delivery failure
        logger.error(
            "could not enqueue the official-post notification for links %s "
            "(%s: %s); the rows are stored and can still be approved from the "
            "console",
            list(created_ids),
            type(exc).__name__,
            exc,
        )
