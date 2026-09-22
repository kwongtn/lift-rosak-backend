"""Best-effort page-title fetcher for feed link submissions.

Titles are decorative: a failure here must never fail the submission, so every
transport, protocol, and parse error collapses to an empty string.

The URL is user-supplied, so the fetch is gated to ``http``/``https`` and only
runs when every resolved address is a public one — this is the SSRF guard.
"""

import html
import ipaddress
import re
import socket
from urllib.parse import urlsplit

import httpx
from asgiref.sync import sync_to_async

TITLE_MAX_LENGTH = 256

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Names that resolve to loopback on most systems but may be missed by a DNS
# lookup shortcut, so reject them outright.
_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})

# A normal browser UA — some hosts serve a challenge page to default clients.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_PATTERN = re.compile(r"\s+")


def _is_public_host(host: str) -> bool:
    """True only when ``host`` resolves and every address is global.

    Sync and blocking — callers must wrap it in ``sync_to_async``.
    """
    name = host.lower()
    if name in _BLOCKED_HOSTNAMES or name.endswith(".localhost"):
        return False

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False

    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False

    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            return False
        if not parsed.is_global:
            return False
    return True


async def fetch_page_title(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """Return the page's ``<title>``, or ``""`` on any failure.

    ``transport`` mirrors ``incident.extraction`` so tests can inject an
    ``httpx.MockTransport``.
    """
    try:
        parsed_url = urlsplit(url)
        host = parsed_url.hostname
    except ValueError:
        return ""

    if parsed_url.scheme not in _ALLOWED_SCHEMES or not host:
        return ""
    if not await sync_to_async(_is_public_host)(host):
        return ""

    try:
        async with httpx.AsyncClient(
            timeout=3.0,
            headers={"User-Agent": _USER_AGENT},
            transport=transport,
            # ponytail: no redirects — this title is decorative. Following one
            # would re-open the SSRF hole on the hops, so a 3xx yields "". If
            # redirect-aware title fetching is ever needed, re-validate the
            # target host on every hop instead of relaxing this.
            follow_redirects=False,
        ) as client:
            response = await client.get(url)
            if response.status_code // 100 != 2:
                return ""
            body = response.text
    except Exception:
        return ""

    match = _TITLE_PATTERN.search(body)
    if match is None:
        return ""

    title = html.unescape(match.group(1))
    title = _WHITESPACE_PATTERN.sub(" ", title).strip()
    return title[:TITLE_MAX_LENGTH]
