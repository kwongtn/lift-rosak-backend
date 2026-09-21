"""Best-effort page-title fetcher for feed link submissions.

Titles are decorative: a failure here must never fail the submission, so every
transport, protocol, and parse error collapses to an empty string.
"""

import html
import re

import httpx

TITLE_MAX_LENGTH = 256

# A normal browser UA — some hosts serve a challenge page to default clients.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_PATTERN = re.compile(r"\s+")


async def fetch_page_title(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """Return the page's ``<title>``, or ``""`` on any failure.

    ``transport`` mirrors ``incident.extraction`` so tests can inject an
    ``httpx.MockTransport``.
    """
    try:
        async with httpx.AsyncClient(
            timeout=3.0,
            headers={"User-Agent": _USER_AGENT},
            transport=transport,
            follow_redirects=True,
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
