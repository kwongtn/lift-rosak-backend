"""Tests for incident.services.page_title.fetch_page_title."""

import httpx
import pytest

from incident.services import page_title


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.django_db
async def test_parses_unescapes_and_collapses_title():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><head><TITLE>  LRT &amp;  MRT\n  delays </TITLE></head></html>",
        )

    title = await page_title.fetch_page_title(
        "https://example.com/post", transport=_transport(handler)
    )

    assert title == "LRT & MRT delays"


@pytest.mark.django_db
async def test_sends_browser_user_agent():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("User-Agent")
        return httpx.Response(200, text="<title>ok</title>")

    await page_title.fetch_page_title(
        "https://example.com/post", transport=_transport(handler)
    )

    assert captured["ua"] is not None
    assert "Mozilla" in captured["ua"]


@pytest.mark.django_db
async def test_returns_empty_on_non_2xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<title>Not found</title>")

    title = await page_title.fetch_page_title(
        "https://example.com/missing", transport=_transport(handler)
    )

    assert title == ""


@pytest.mark.django_db
async def test_returns_empty_on_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    title = await page_title.fetch_page_title(
        "https://example.com/down", transport=_transport(handler)
    )

    assert title == ""


@pytest.mark.django_db
async def test_returns_empty_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    title = await page_title.fetch_page_title(
        "https://example.com/slow", transport=_transport(handler)
    )

    assert title == ""


@pytest.mark.django_db
async def test_returns_empty_when_title_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>no title here</body></html>")

    title = await page_title.fetch_page_title(
        "https://example.com/untitled", transport=_transport(handler)
    )

    assert title == ""


@pytest.mark.django_db
async def test_truncates_to_256_chars():
    long_title = "x" * 300

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"<title>{long_title}</title>")

    title = await page_title.fetch_page_title(
        "https://example.com/long", transport=_transport(handler)
    )

    assert len(title) == 256
    assert title == "x" * 256
