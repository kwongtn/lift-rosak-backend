"""Tests for incident.services.page_title.fetch_page_title."""

import ipaddress
import socket

import httpx
import pytest

from incident.services import page_title


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch):
    """Resolve offline: numeric hosts to themselves, names to a public IP.

    Keeps every test deterministic and network-free; the SSRF guard must never
    reach real DNS.
    """

    def fake_getaddrinfo(host, *args, **kwargs):
        try:
            ipaddress.ip_address(host.split("%")[0])
        except ValueError:
            address = "93.184.216.34"  # example.com, a global address
        else:
            address = host
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(page_title.socket, "getaddrinfo", fake_getaddrinfo)


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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/",
        "http://10.0.0.5/x",
        "http://192.168.1.1/",
        "http://localhost/x",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ],
)
async def test_blocks_ssrf_targets_without_any_request(url):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="<title>must not be reached</title>")

    title = await page_title.fetch_page_title(url, transport=_transport(handler))

    assert title == ""
    assert calls == []


@pytest.mark.django_db
async def test_does_not_follow_redirects():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            302, headers={"Location": "http://169.254.169.254/"}, text=""
        )

    title = await page_title.fetch_page_title(
        "https://example.com/redirect", transport=_transport(handler)
    )

    assert title == ""
    assert len(calls) == 1


@pytest.mark.django_db
async def test_unresolvable_host_returns_empty(monkeypatch):
    def boom(host, *args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(page_title.socket, "getaddrinfo", boom)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="<title>must not be reached</title>")

    title = await page_title.fetch_page_title(
        "https://does-not-exist.invalid/x", transport=_transport(handler)
    )

    assert title == ""
    assert calls == []


@pytest.mark.django_db
async def test_public_url_still_fetches_title():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<title>  MRT &amp; LRT  </title>")

    title = await page_title.fetch_page_title(
        "https://example.com/story", transport=_transport(handler)
    )

    assert title == "MRT & LRT"
