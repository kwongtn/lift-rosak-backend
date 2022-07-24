import json
import logging
import urllib

import requests
from django.http import HttpRequest, HttpResponse

sentry_host = "o1331817.ingest.sentry.io"
known_project_ids = ["6596136"]


def main(request: HttpRequest):
    try:
        envelope = request.body.decode("utf-8")

        piece = envelope.split("\n")[0]
        header = json.loads(piece)
        dsn = urllib.parse.urlparse(header.get("dsn"))

        if dsn.hostname != sentry_host:
            raise Exception(f"Invalid Sentry host: {dsn.hostname}")

        project_id = dsn.path.strip("/")
        if project_id not in known_project_ids:
            raise Exception(f"Invalid Project ID: {project_id}")

        url = f"https://{sentry_host}/api/{project_id}/envelope/"

        requests.post(url=url, data=envelope)

    except Exception as e:
        # handle exception in your preferred style,
        # e.g. by logging or forwarding to Sentry
        logging.exception(e)

    return HttpResponse({})
