"""URL canonicalization for social links.

Pure stdlib helpers (``urllib.parse`` only) used to normalize social media URLs
so that the same post shared with different tracking parameters collapses to one
identity. This module must stay import-light and synchronous: it is imported by
model code and data migrations.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only identify the referrer/campaign, never the content.
# Matched case-insensitively.
TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "gbraid",
        "wbraid",
        "msclkid",
        "twclid",
        "igshid",
        "si",
        "yclid",
        "ref",
        "ref_src",
        "ref_url",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_name",
        "utm_reader",
        "utm_referrer",
        "utm_social",
        "utm_social-type",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "vero_conv",
        "vero_id",
        "oly_enc_id",
        "oly_anon_id",
    }
)


def canonicalize_url(raw: str) -> str:
    """Return a tracking-free, lowercased-host canonical form of ``raw``.

    Returns the input unchanged (as given, after no normalization) when it uses
    a non-http(s) scheme or cannot be parsed. An empty/whitespace-only input
    yields ``""``.
    """
    stripped = raw.strip()
    if not stripped:
        return ""

    try:
        parts = urlsplit(stripped)
        if not parts.scheme:
            parts = urlsplit(f"https://{stripped}")
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            return raw

        host = parts.hostname or ""
        port = parts.port
        netloc = host
        if port is not None and not (
            (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        ):
            netloc = f"{host}:{port}"

        params = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMS
        ]

        path = parts.path
        if path.endswith("/"):
            path = path[:-1]

        return urlunsplit((scheme, netloc, path, urlencode(params), ""))
    except ValueError:
        return raw
