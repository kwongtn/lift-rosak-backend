import json

import httpx
import pytest
from django.test import override_settings

from incident import extraction

CONFIGURED = override_settings(
    EXTRACT_INCIDENT_DATA_URL="https://asia-southeast1-test.cloudfunctions.net/extractIncidentData"
)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@CONFIGURED
@pytest.mark.django_db
async def test_proxies_to_firebase_function_and_returns_result():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = request.read()
        return httpx.Response(
            200,
            json={
                "result": {
                    "requestId": "fn-request-id",
                    "data": {"title": "LRT delay", "severity": "minor"},
                }
            },
        )

    result = await extraction.extract_data_from_url(
        url="https://example.com/news",
        id_token="test-id-token",
        transport=_transport(handler),
    )

    assert captured["auth"] == "Bearer test-id-token"
    body = json.loads(captured["body"])
    assert body["data"]["url"] == "https://example.com/news"
    assert body["data"]["requestId"]
    assert result == {
        "requestId": "fn-request-id",
        "data": {"title": "LRT delay", "severity": "minor"},
    }


@CONFIGURED
@pytest.mark.django_db
async def test_function_error_envelope_raises_extraction_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "error": {
                    "code": 429,
                    "message": "Rate limit: 20 requests per hour",
                }
            },
        )

    with pytest.raises(extraction.ExtractionError, match="Rate limit"):
        await extraction.extract_data_from_url(
            url="https://example.com/news",
            id_token=None,
            transport=_transport(handler),
        )


@CONFIGURED
@pytest.mark.django_db
async def test_unreachable_service_raises_extraction_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(extraction.ExtractionError, match="unreachable"):
        await extraction.extract_data_from_url(
            url="https://example.com/news",
            id_token=None,
            transport=_transport(handler),
        )


@pytest.mark.django_db
async def test_unconfigured_endpoint_raises_extraction_error():
    with pytest.raises(extraction.ExtractionError, match="not configured"):
        await extraction.extract_data_from_url(
            url="https://example.com/news", id_token=None
        )
