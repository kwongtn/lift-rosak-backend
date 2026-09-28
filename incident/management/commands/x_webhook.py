"""Register and manage the X (Twitter) Activity API webhook.

X does not push to a URL you merely have running — you must register it, and X
then proves you own it by sending a CRC challenge that has to be answered
correctly. This command is the operator's lever for that lifecycle::

    python manage.py x_webhook register https://api.example.org/webhooks/x-api
    python manage.py x_webhook list
    python manage.py x_webhook revalidate 18923...            # re-run the CRC
    python manage.py x_webhook subscribe askrapidkl myrapidkl
    python manage.py x_webhook delete 18923...

``register`` alone is not enough: a registered webhook receives nothing until
each account you care about has an **activity subscription** pointing at it
(``subscribe``), which is what the ``webhook_id`` is needed for.

Rules X enforces on the URL, worth reading before the first ``register``:

* it must be a **public HTTPS** URL — reachable from X's servers, and with **no
  port** in it (``https://host:8443/…`` is rejected).
* X validates it by issuing ``GET <url>?crc_token=…`` and expecting
  ``{"response_token": "sha256=…"}`` **within 10 seconds**, so
  ``incident.views.x_api_webhook`` must be deployed and reachable first.
* A failure to validate or to fetch comes back as ``CrcValidationFailed`` or
  ``UrlValidationFailed`` in the API's error ``title``, which is what the
  sanitized error message reports.

``X_API_BEARER_TOKEN`` must be an **App-only** bearer token: it authorizes this
registration API, and it is unrelated to the webhook signing secrets
(``X_API_OAUTH2_CLIENT_SECRET`` / ``X_API_SECRET_KEY``), which live server-side
and are never sent to X from here. The token is read from settings, used only
in an ``Authorization`` header, and never printed — neither on success nor in an
error message.
"""

from __future__ import annotations

from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from incident.services.errors import OfficialPostFetchError

#: The registration and subscription API shares the v2 host.
X_API_BASE = "https://api.x.com/2"
X_WEBHOOKS_URL = f"{X_API_BASE}/webhooks"
X_SUBSCRIPTIONS_URL = f"{X_API_BASE}/activity/subscriptions"

#: A hung socket must not leave an operator staring at a prompt forever.
HTTP_TIMEOUT_SECONDS = 30

#: The only event type this app subscribes to; the receiver ignores every other
#: event type with a 200, so subscribing to more would only add volume.
SUBSCRIPTION_EVENT_TYPE = "post.create"
#: Free-form label X stores with the subscription. Purely for the operator's own
#: benefit when listing subscriptions in the portal.
SUBSCRIPTION_TAG = "official-posts"

#: The public subscription endpoint, and the error titles X uses when a
#: registration cannot be validated. Only these two are surfaced, so a failure
#: message never quotes an upstream body that could echo the request.
REGISTRATION_ERROR_TITLES = ("CrcValidationFailed", "UrlValidationFailed")

ACTIONS = ("register", "list", "delete", "revalidate", "subscribe")


class Command(BaseCommand):
    help = (
        "Register, inspect, re-validate and delete the X (Twitter) Activity API "
        "webhook, and create the per-account post.create subscriptions that "
        "actually deliver events. Actions: register URL | list | delete "
        "WEBHOOK_ID | revalidate WEBHOOK_ID | subscribe HANDLE [HANDLE ...]. "
        "The URL must be a public HTTPS endpoint with no port; X validates it by "
        "CRC within 10 seconds and reports CrcValidationFailed / "
        "UrlValidationFailed when it cannot. Requires settings.X_API_BEARER_TOKEN "
        "(App-only); the webhook signing secrets stay server-side and are never "
        "sent to X from here."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "action",
            choices=ACTIONS,
            help=(
                "register: POST /2/webhooks with URL. list: GET /2/webhooks. "
                "delete: DELETE /2/webhooks/{id}. revalidate: PUT /2/webhooks/{id} "
                "to re-trigger CRC. subscribe: one activity subscription per "
                "HANDLE."
            ),
        )
        parser.add_argument(
            "target",
            nargs="*",
            metavar="TARGET",
            help=(
                "URL for register; WEBHOOK_ID for delete/revalidate; one or more "
                "HANDLEs (without '@') for subscribe. Unused by list."
            ),
        )
        parser.add_argument(
            "--webhook-id",
            dest="webhook_id",
            default=None,
            help=(
                "Subscription target for subscribe. Optional: when omitted the "
                "registered webhooks are listed and there must be exactly one."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        action: str = options["action"]
        targets: list[str] = [
            str(item).strip() for item in (options.get("target") or [])
        ]

        if action == "register":
            self._register(self._single_target(action, targets))
        elif action == "list":
            self._list()
        elif action == "delete":
            self._delete(self._single_target(action, targets))
        elif action == "revalidate":
            self._revalidate(self._single_target(action, targets))
        else:
            self._subscribe(targets, options.get("webhook_id"))

    # --- argument handling --------------------------------------------

    @staticmethod
    def _single_target(action: str, targets: list[str]) -> str:
        if len(targets) != 1:
            raise CommandError(
                f"'{action}' takes exactly one argument "
                f"(got {len(targets)}): see the command help for the per-action form"
            )
        return targets[0]

    def _bearer_token(self) -> str:
        token = (settings.X_API_BEARER_TOKEN or "").strip()
        if not token:
            raise CommandError(
                "X_API_BEARER_TOKEN is not configured; an App-only bearer token is "
                "required to manage webhooks (it is separate from the webhook "
                "signing secrets)"
            )
        return token

    # --- HTTP ----------------------------------------------------------

    def _request(
        self, method: str, url: str, *, description: str, json_body: dict | None = None
    ) -> dict[str, Any]:
        """Call the X API, returning the decoded object or raising CommandError.

        Every failure — transport, non-2xx, unparseable, unexpected shape —
        collapses into a ``CommandError`` carrying the status code and at most
        the API's short error ``title``. The upstream body is never quoted
        verbatim and the bearer token never appears, because a CommandError
        message is exactly the kind of thing an operator pastes into a chat.
        """
        headers = {"Authorization": f"Bearer {self._bearer_token()}"}
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except requests.Timeout:
            raise CommandError(
                f"{description}: request to X timed out after {HTTP_TIMEOUT_SECONDS}s"
            ) from None
        except requests.RequestException as exc:
            raise CommandError(
                f"{description}: request to X failed ({type(exc).__name__})"
            ) from None

        status = response.status_code
        if not 200 <= status < 300:
            raise CommandError(
                f"{description}: X returned HTTP {status} ({self._api_title(response)})"
            )
        try:
            payload = response.json()
        except ValueError:
            raise CommandError(
                f"{description}: X returned a body that was not valid JSON"
            ) from None
        if not isinstance(payload, dict):
            raise CommandError(f"{description}: X returned JSON that was not an object")
        return payload

    @staticmethod
    def _api_title(response: requests.Response) -> str:
        """The upstream error ``title``, or a fixed placeholder.

        X reports webhook problems as ``CrcValidationFailed`` /
        ``UrlValidationFailed``, and those two words are the whole diagnostic
        value here — everything else in the body is either noise or an echo of
        the request.
        """
        try:
            detail = response.json().get("errors")
        except ValueError:
            return "no error detail"
        if not isinstance(detail, list):
            return "no error detail"
        for error in detail:
            if not isinstance(error, dict):
                continue
            title = str(error.get("title") or "").strip()
            if title in REGISTRATION_ERROR_TITLES:
                return title
        for error in detail:
            if isinstance(error, dict):
                title = str(error.get("title") or "").strip()
                if title:
                    return title
        return "no error detail"

    # --- actions -------------------------------------------------------

    def _register(self, url: str) -> None:
        if not url:
            raise CommandError("'register' needs the public HTTPS URL to register")
        if not url.lower().startswith("https://"):
            raise CommandError(
                f"the webhook URL must be HTTPS (X rejects plain http); got {url!r}"
            )
        payload = self._request(
            "POST",
            X_WEBHOOKS_URL,
            description="registering the webhook",
            json_body={"url": url},
        )
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise CommandError(
                "registering the webhook: X accepted the call but returned no "
                "webhook id"
            )
        self.stdout.write(
            f"registered webhook id={data['id']} url={data.get('url', url)} "
            f"valid={data.get('valid')}"
        )
        if not data.get("valid"):
            self.stderr.write(
                self.style.WARNING(
                    "the webhook is not valid yet: confirm the URL is public HTTPS "
                    "with no port, and that it answers the CRC challenge "
                    "(GET ?crc_token=… returning {'response_token': 'sha256=…'}) "
                    "within 10 seconds"
                )
            )

    def _list(self) -> None:
        payload = self._request("GET", X_WEBHOOKS_URL, description="listing webhooks")
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            self.stdout.write("no webhooks are registered for this app")
            return
        for entry in data:
            if not isinstance(entry, dict):
                continue
            self.stdout.write(
                f"id={entry.get('id')} valid={entry.get('valid')} "
                f"url={entry.get('url')}"
            )

    def _delete(self, webhook_id: str) -> None:
        self._request(
            "DELETE",
            f"{X_WEBHOOKS_URL}/{webhook_id}",
            description=f"deleting webhook {webhook_id}",
        )
        self.stdout.write(f"deleted webhook id={webhook_id}")

    def _revalidate(self, webhook_id: str) -> None:
        payload = self._request(
            "PUT",
            f"{X_WEBHOOKS_URL}/{webhook_id}",
            description=f"re-validating webhook {webhook_id}",
        )
        data = payload.get("data")
        valid = data.get("valid") if isinstance(data, dict) else None
        self.stdout.write(f"revalidated webhook id={webhook_id} valid={valid}")

    def _subscribe(self, handles: list[str], webhook_id: str | None) -> None:
        handles = [handle.lstrip("@") for handle in handles if handle]
        if not handles:
            raise CommandError(
                "'subscribe' needs at least one HANDLE (without '@'); pass them "
                "positionally, e.g. subscribe askrapidkl myrapidkl"
            )

        target = webhook_id.strip() if webhook_id and webhook_id.strip() else None
        if target is None:
            target = self._sole_webhook_id()
        self.stdout.write(f"subscribing to webhook id={target}")

        for handle in handles:
            user_id = self._user_id(handle)
            payload = self._request(
                "POST",
                X_SUBSCRIPTIONS_URL,
                description=f"subscribing @{handle}",
                json_body={
                    "event_type": SUBSCRIPTION_EVENT_TYPE,
                    "filter": {"user_id": user_id},
                    "webhook_id": target,
                    "tag": SUBSCRIPTION_TAG,
                },
            )
            data = payload.get("data")
            subscription_id = data.get("id") if isinstance(data, dict) else None
            self.stdout.write(
                f"subscribed handle={handle} user_id={user_id} "
                f"event_type={SUBSCRIPTION_EVENT_TYPE} tag={SUBSCRIPTION_TAG} "
                f"subscription_id={subscription_id}"
            )

    def _sole_webhook_id(self) -> str:
        """The only registered webhook, or a CommandError naming every id.

        Guessing here would attach subscriptions to the wrong endpoint, which
        is silent until the events stop arriving — so ambiguity is refused.
        """
        payload = self._request("GET", X_WEBHOOKS_URL, description="listing webhooks")
        data = payload.get("data")
        ids = [
            str(entry["id"])
            for entry in (data if isinstance(data, list) else [])
            if isinstance(entry, dict) and entry.get("id")
        ]
        if not ids:
            raise CommandError(
                "no webhooks are registered for this app; run "
                "'x_webhook register <https-url>' first"
            )
        if len(ids) > 1:
            raise CommandError(
                f"{len(ids)} webhooks are registered ({', '.join(ids)}); pass "
                "--webhook-id to choose one"
            )
        return ids[0]

    def _user_id(self, handle: str) -> str:
        """Resolve ``handle`` to its X user id through the shared lookup.

        Reuses the ingestion service's own (cached) resolution rather than a
        second one, so a subscription can never be created against a different
        id than the one ingestion polls for.

        The import is function-local on purpose: a module-level binding is
        frozen at import time, which makes the lookup impossible to stub at its
        source and lets a test reach the real X API with a fake token.
        """
        from incident.services.official_posts import _resolve_user_id

        try:
            return _resolve_user_id(handle)
        except OfficialPostFetchError as exc:
            # Already sanitized by the service layer: status + reason only.
            raise CommandError(f"could not resolve @{handle}: {exc}") from None
