"""Unit tests for incident.services.urls.canonicalize_url (pure, no DB)."""

from incident.services.urls import canonicalize_url


def test_empty_string_returns_empty():
    assert canonicalize_url("") == ""


def test_whitespace_only_returns_empty():
    assert canonicalize_url("   ") == ""


def test_fbclid_stripped():
    assert (
        canonicalize_url("https://example.com/post?fbclid=abc123")
        == "https://example.com/post"
    )


def test_utm_params_stripped():
    url = "https://example.com/post?utm_source=news&utm_medium=email&utm_campaign=x"
    assert canonicalize_url(url) == "https://example.com/post"


def test_igshid_and_si_stripped():
    url = "https://example.com/post?igshid=xyz&si=share"
    assert canonicalize_url(url) == "https://example.com/post"


def test_host_is_lowercased():
    assert canonicalize_url("https://EXAMPLE.COM/Path") == "https://example.com/Path"


def test_scheme_is_lowercased():
    assert canonicalize_url("HTTPS://example.com/Path") == "https://example.com/Path"


def test_fragment_is_dropped():
    assert (
        canonicalize_url("https://example.com/post#comments")
        == "https://example.com/post"
    )


def test_trailing_slash_dropped():
    assert canonicalize_url("https://example.com/post/") == "https://example.com/post"


def test_root_path_becomes_empty():
    assert canonicalize_url("https://example.com/") == "https://example.com"


def test_param_removal_is_case_insensitive():
    assert (
        canonicalize_url("https://example.com/post?FBclid=1")
        == "https://example.com/post"
    )


def test_default_port_stripped():
    assert (
        canonicalize_url("https://example.com:443/post") == "https://example.com/post"
    )
    assert canonicalize_url("http://example.com:80/post") == "http://example.com/post"


def test_non_http_scheme_returned_unchanged():
    raw = "mailto:test@example.com"
    assert canonicalize_url(raw) == raw


def test_ftp_scheme_returned_unchanged():
    raw = "ftp://example.com/file"
    assert canonicalize_url(raw) == raw


def test_missing_scheme_assumed_https():
    assert canonicalize_url("example.com/post") == "https://example.com/post"


def test_query_order_preserved_for_survivors():
    assert (
        canonicalize_url("https://example.com/post?b=2&a=1&utm_source=x")
        == "https://example.com/post?b=2&a=1"
    )


def test_malformed_string_returned_unchanged():
    raw = "https://example.com:notaport/path"
    assert canonicalize_url(raw) == raw
