"""Rate-limit integration: the extractDataFromUrl chain against a simulated
extractIncidentData Firebase Function enforcing its 20 req/hour/user limit.

The real limit lives function-side (Firestore counter keyed by uid + UTC hour,
see rosak_firebase functions/src/index.ts). No emulator is available in CI, so
the mock transport replays the function's documented wire contract: success
envelope for calls 1-20 within the hour bucket, then the callable-protocol
error envelope {error: {code: 429, message: "Rate limit: 20 requests per
hour"}}. What this pins on the backend side: every proxied call carries the
caller's own Bearer token (so per-user limiting stays authoritative) and the
exhaustion error surfaces through the GraphQL mutation as a GraphQLError.
"""

import json

import httpx
import pytest
from graphql.error import GraphQLError

from incident import extraction
from incident.schema.inputs import ExtractDataInput
from incident.schema.mutations.interactions import ExtractionMutations

RATE_LIMIT = 20


class _SimulatedFirebaseFunction(httpx.MockTransport):
    """Stateful stand-in for extractIncidentData's rate limiter."""

    def __init__(self):
        self.counts_by_token: dict[str, int] = {}
        self.bearer_tokens: list[str | None] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization")
        token = auth.removeprefix("Bearer ").strip() if auth else None
        self.bearer_tokens.append(token)

        count = self.counts_by_token.get(token or "anonymous", 0)
        if count >= RATE_LIMIT:
            return httpx.Response(
                200,
                json={
                    "error": {
                        "code": 429,
                        "message": f"Rate limit: {RATE_LIMIT} requests per hour",
                    }
                },
            )
        self.counts_by_token[token or "anonymous"] = count + 1
        body = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "result": {
                    "requestId": body["data"]["requestId"],
                    "data": {"title": "ok"},
                }
            },
        )


@pytest.fixture
def configured(settings):
    settings.EXTRACT_INCIDENT_DATA_URL = (
        "https://asia-southeast1-test.cloudfunctions.net/extractIncidentData"
    )
    return settings


@pytest.mark.django_db
async def test_twenty_calls_per_user_pass_then_exhaustion_raises(configured):
    fn = _SimulatedFirebaseFunction()

    for _ in range(RATE_LIMIT):
        result = await extraction.extract_data_from_url(
            url="https://example.com/news", id_token="user-a-token", transport=fn
        )
        assert result["data"] == {"title": "ok"}

    with pytest.raises(extraction.ExtractionError, match="Rate limit: 20"):
        await extraction.extract_data_from_url(
            url="https://example.com/news", id_token="user-a-token", transport=fn
        )


@pytest.mark.django_db
async def test_limit_is_per_user_not_global(configured):
    fn = _SimulatedFirebaseFunction()

    for _ in range(RATE_LIMIT):
        await extraction.extract_data_from_url(
            url="https://example.com/news", id_token="user-a-token", transport=fn
        )

    result = await extraction.extract_data_from_url(
        url="https://example.com/news", id_token="user-b-token", transport=fn
    )
    assert result["data"] == {"title": "ok"}


@pytest.mark.django_db
async def test_every_proxied_call_forwards_the_callers_token(configured):
    fn = _SimulatedFirebaseFunction()

    for _ in range(3):
        await extraction.extract_data_from_url(
            url="https://example.com/news", id_token="same-user-token", transport=fn
        )

    assert fn.bearer_tokens == ["same-user-token"] * 3


@pytest.mark.django_db
async def test_mutation_surfaces_rate_limit_as_graphql_error(configured, monkeypatch):
    from functools import partial

    fn = _SimulatedFirebaseFunction()
    monkeypatch.setattr(
        "incident.extraction.extract_data_from_url",
        partial(extraction.extract_data_from_url, transport=fn),
    )

    class _Request:
        headers = {"Authorization": "Bearer mutation-user"}

    class _Context:
        request = _Request()
        user = None

    class _Info:
        context = _Context()

    mutations = ExtractionMutations()
    info = _Info()

    for _ in range(RATE_LIMIT):
        result = await mutations.extract_data_from_url(
            info, input=ExtractDataInput(url="https://example.com/news")
        )
        assert result.data == {"title": "ok"}

    with pytest.raises(GraphQLError, match="Rate limit: 20"):
        await mutations.extract_data_from_url(
            info, input=ExtractDataInput(url="https://example.com/news")
        )
