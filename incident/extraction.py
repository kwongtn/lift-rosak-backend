"""Proxy to the extractIncidentData Firebase callable function.

The function speaks the Firebase callable protocol: JSON body wrapped in a
top-level "data" key, the caller's Firebase ID token as a Bearer header, and
a "{result}" / "{error}" response envelope. Forwarding the caller's own token
keeps the function-side auth and per-user rate limiting authoritative.
"""

import uuid

import httpx
from django.conf import settings


class ExtractionError(Exception):
    """The extraction call failed at the transport, protocol, or function level."""


async def extract_data_from_url(
    *, url: str, id_token: str | None, transport: httpx.AsyncBaseTransport | None = None
) -> dict:
    if not settings.EXTRACT_INCIDENT_DATA_URL:
        raise ExtractionError("Extraction endpoint is not configured.")

    request_id = uuid.uuid4().hex
    headers = {"Content-Type": "application/json"}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"

    try:
        async with httpx.AsyncClient(timeout=25.0, transport=transport) as client:
            response = await client.post(
                settings.EXTRACT_INCIDENT_DATA_URL,
                json={"data": {"url": url, "requestId": request_id}},
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise ExtractionError(f"Extraction service unreachable: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise ExtractionError(
            f"Extraction service returned non-JSON response (HTTP {response.status_code})."
        ) from exc

    if response.status_code != 200 or "error" in body:
        message = None
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            message = body["error"].get("message")
        raise ExtractionError(
            message or f"Extraction failed with HTTP {response.status_code}."
        )

    result = body.get("result") or {}
    return {
        "requestId": result.get("requestId", request_id),
        "data": result.get("data"),
    }
