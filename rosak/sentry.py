from urllib.parse import urlparse


def filter_transactions(event, hint):
    url_string = event["request"]["url"]
    parsed_url = urlparse(url_string)

    if parsed_url.path in ["/health-check", "/health-check/"]:
        return None

    return event
