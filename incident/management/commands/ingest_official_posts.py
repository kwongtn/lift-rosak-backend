"""Manual backfill for official operator posts (Phase 1 of OFFICIAL_POST_INGESTION.md).

The scheduled task (``incident.tasks.ingest_official_posts``) is the incremental
path: every 5 minutes, ``since_id=latest_post_id(account)``, no window. This
command is the *manual* lever for "scrape by date, range or a number of posts"::

    python manage.py ingest_official_posts [--handle askrapidkl] [--since YYYY-MM-DD]
                                            [--until YYYY-MM-DD] [--limit N]
                                            [--fixture PATH] [--dry-run]

Semantics worth knowing before running it:

* Without ``--handle`` the command polls every enabled X account in the
  ``SocMedAccount`` registry (``platform=x``, ``is_enabled=True``) — the same
  set the scheduled task polls, and the one source of truth for what is
  tracked. A ``--handle`` is resolved through the shared ``resolve_account``
  (auto-registering an unknown handle under the ``Unassigned`` agency), so a
  manual run can ingest an account the registry does not know yet.
* ``--since`` / ``--until`` are **inclusive calendar dates in UTC** and become
  the X API's ``start_time`` / ``end_time``. ``--since D`` is ``D 00:00:00Z``;
  ``--until D`` is ``D 23:59:59.999999Z``, i.e. the whole of that day (the
  alternative — a midnight bound — would silently drop the final day of a
  backfill, which is the shape of bug this command exists to avoid).
* They are mutually exclusive with ``since_id``: a windowed run fetches by date
  only, and an unwindowed run uses ``since_id`` (the cheap incremental filter).
  Passing both is refused rather than silently resolved.
* ``--fixture`` ingests a saved API-shaped payload through the **same**
  ``ingest_posts`` path with no network access. That is how the pipeline is
  exercised before a paid X token exists, and how the tests build data. The
  account is taken from a single ``--handle`` if given, otherwise from the
  payload's top-level ``handle`` key, and resolved/auto-registered through
  ``resolve_account`` (a dry run may only preview an account the registry
  already has, because auto-registration is itself a write); more than one
  ``--handle`` with a fixture is ambiguous and refused. ``--since``/``--until``
  are meaningless for a fixture and are refused with it.
* ``--dry-run`` runs the same existence checks and prints what *would* be
  written, creating nothing (no link rows, no account rows).
* ``OFFICIAL_POST_INGESTION_ENABLED`` gates the **scheduled** task only; a
  manual run is an explicit act and always executes. The live path still needs a
  read-capable ``X_API_BEARER_TOKEN`` — a fetch failure raises ``CommandError``
  so a manual run fails loudly instead of pretending it worked.
* Honest limit: ``GET /2/users/{id}/tweets`` only serves an account's most
  recent ~3,200 posts, and ``start_time``/``end_time`` filter *within* that
  window. "Backfill by year" is therefore not achievable through this API, and
  the command says so whenever the window looks out of reach instead of
  under-fetching quietly.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from common.models import User
from incident.enums import IngestPlatform
from incident.models import SocMedAccount
from incident.services.errors import OfficialPostFetchError, OfficialPostIngestError
from incident.services.official_posts import (
    SYSTEM_AUTHOR_FIREBASE_ID,
    IngestSummary,
    RawPost,
    get_system_author,
    ingest_posts,
    latest_post_id,
    load_fixture_posts,
    resolve_account,
)

#: "GET /2/users/{id}/tweets only serves the most recent ~3,200 posts for an
#: account", so a window older than the account's own reachable history cannot be
#: backfilled through this endpoint no matter what is requested.
API_WINDOW_POST_LIMIT = 3200


class Command(BaseCommand):
    help = (
        "Ingest official X posts into SocialMediaLink, manually. "
        "Default accounts come from the enabled X SocMedAccount registry "
        "entries; "
        f"rows are authored by the system user '{SYSTEM_AUTHOR_FIREBASE_ID}' and land "
        "PENDING_APPROVAL. --fixture ingests a saved payload offline (no token "
        "needed); --dry-run writes nothing. The live path requires a read-capable "
        "X_API_BEARER_TOKEN (the X API free tier cannot read)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--handle",
            action="append",
            dest="handles",
            metavar="HANDLE",
            help=(
                "Account to ingest, without '@'. Repeatable; defaults to the "
                "enabled X SocMedAccount registry. With --fixture, at most one."
            ),
        )
        parser.add_argument(
            "--since",
            metavar="YYYY-MM-DD",
            help="Inclusive UTC start date (API start_time). Mutually exclusive with --fixture.",
        )
        parser.add_argument(
            "--until",
            metavar="YYYY-MM-DD",
            help=(
                "Inclusive UTC end date (API end_time) — the whole day, up to "
                "23:59:59.999999Z."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            metavar="N",
            help=(
                "Maximum posts per handle, across pages. Defaults to "
                "settings.OFFICIAL_POST_FETCH_LIMIT."
            ),
        )
        parser.add_argument(
            "--fixture",
            metavar="PATH",
            help=(
                "Ingest a saved /2/users/{id}/tweets payload instead of calling the "
                "API. No network access."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Print what would be ingested and write nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # ``explicit`` is what the operator actually typed; ``accounts`` is
        # what will be run. They differ for --fixture, where the registry
        # default must not look like "several handles given".
        explicit: list[str] = [
            handle.strip().lstrip("@")
            for handle in (options.get("handles") or [])
            if handle.strip()
        ]

        limit = self._resolve_limit(options.get("limit"))
        since = self._parse_date(options.get("since"), "--since")
        until = self._parse_date(options.get("until"), "--until", end_of_day=True)
        if since is not None and until is not None and until < since:
            raise CommandError(
                f"--until ({options['until']}) is before --since ({options['since']})"
            )

        dry_run = bool(options.get("dry_run"))
        fixture = options.get("fixture")
        author = self._author()

        if fixture:
            if since is not None or until is not None:
                raise CommandError(
                    "--since/--until cannot be combined with --fixture: a saved "
                    "payload is already a fixed set of posts"
                )
            self._run_fixture(
                fixture,
                explicit_handles=explicit,
                author=author,
                limit=limit,
                dry_run=dry_run,
            )
            return

        # Live run: an explicit --handle is resolved (and auto-registered under
        # the Unassigned agency), otherwise the enabled X accounts in the
        # SocMedAccount registry are polled.
        accounts = (
            self._resolve_accounts(explicit)
            if explicit
            else list(
                SocMedAccount.objects.filter(
                    platform=IngestPlatform.X, is_enabled=True
                ).order_by("handle")
            )
        )
        if not accounts:
            raise CommandError(
                "no accounts to ingest: pass --handle or enable a registry "
                "account (SocMedAccount platform=x with is_enabled=True)"
            )

        self._run_live(
            accounts=accounts,
            since=since,
            until=until,
            limit=limit,
            dry_run=dry_run,
            author=author,
        )

    # --- argument resolution -------------------------------------------

    def _resolve_limit(self, raw: int | None) -> int:
        limit = settings.OFFICIAL_POST_FETCH_LIMIT if raw is None else raw
        if limit <= 0:
            raise CommandError(f"--limit must be a positive integer (got {limit})")
        return limit

    def _parse_date(
        self, raw: str | None, flag: str, *, end_of_day: bool = False
    ) -> datetime | None:
        """Parse ``YYYY-MM-DD`` into an aware UTC bound.

        ``end_of_day`` takes the last microsecond of the day so ``--until D``
        covers the whole of D.
        """
        if not raw:
            return None
        try:
            parsed = date.fromisoformat(raw)
        except ValueError:
            raise CommandError(f"{flag} must be YYYY-MM-DD (got {raw!r})") from None
        moment = time(23, 59, 59, 999999) if end_of_day else time(0, 0)
        return datetime.combine(parsed, moment, tzinfo=UTC)

    def _author(self) -> User:
        try:
            return get_system_author()
        except OfficialPostIngestError as exc:
            raise CommandError(str(exc)) from None

    def _resolve_accounts(self, handles: list[str]) -> list[SocMedAccount]:
        """Resolve each ``--handle`` to its registry account, auto-registering.

        ``resolve_account(..., create=True)`` registers an unknown handle under
        the ``Unassigned`` agency with no API call; the live fetch then fills
        ``user_id`` through ``ensure_user_profile`` inside ``fetch_user_posts``.
        A handle that can neither be matched nor registered is a command
        failure — the operator asked for a specific account and got nothing.
        """
        accounts: list[SocMedAccount] = []
        for handle in handles:
            account = resolve_account(IngestPlatform.X, handle=handle, create=True)
            if account is None:
                raise CommandError(
                    f"could not resolve or register a registry account for @{handle}"
                )
            accounts.append(account)
        return accounts

    # --- execution paths -----------------------------------------------

    def _run_fixture(
        self,
        path: str,
        *,
        explicit_handles: list[str],
        author: User,
        limit: int,
        dry_run: bool,
    ) -> None:
        if len(explicit_handles) > 1:
            raise CommandError(
                "--fixture ingests a single saved payload, so it cannot be attributed "
                f"to several handles ({', '.join(explicit_handles)}); pass exactly one "
                "--handle, or none to use the payload's own 'handle' key"
            )
        explicit = explicit_handles[0] if explicit_handles else None
        try:
            # A None handle resolves the payload's own top-level "handle" key.
            posts = load_fixture_posts(path, handle=explicit)
        except OfficialPostFetchError as exc:
            raise CommandError(str(exc)) from None

        if not posts:
            self.stdout.write(f"fixture {path} contains no posts; nothing to ingest")
            return

        handle = explicit or posts[0].handle
        # Auto-registration is itself a write, so a dry run may only preview an
        # account the registry already knows: a preview must write nothing at
        # all (no link rows, no account rows).
        account = resolve_account(IngestPlatform.X, handle=handle, create=not dry_run)
        if account is None:
            raise CommandError(
                f"fixture handle @{handle} is not in the registry; run without "
                "--dry-run to auto-register it under the 'Unassigned' agency"
            )

        posts = posts[:limit]
        summary = ingest_posts(posts, author=author, dry_run=dry_run)
        self._report(account.handle, summary, dry_run=dry_run, source=f"fixture {path}")

    def _run_live(
        self,
        *,
        accounts: list[SocMedAccount],
        since: datetime | None,
        until: datetime | None,
        limit: int,
        dry_run: bool,
        author: User,
    ) -> None:
        # Imported here (not at module scope) so the fixture-only path cannot
        # reach the HTTP layer at all.
        from incident.services.official_posts import fetch_user_posts

        windowed = since is not None or until is not None
        for account in accounts:
            try:
                if windowed:
                    posts = fetch_user_posts(
                        account, start_time=since, end_time=until, limit=limit
                    )
                else:
                    posts = fetch_user_posts(
                        account, since_id=latest_post_id(account), limit=limit
                    )
                summary = ingest_posts(posts, author=author, dry_run=dry_run)
            except (OfficialPostFetchError, OfficialPostIngestError) as exc:
                # A manual run fails loudly rather than pretending it worked. The
                # message is already sanitized by the service layer.
                raise CommandError(str(exc)) from None

            self._report(account.handle, summary, dry_run=dry_run, source="x api")
            if since is not None:
                self._warn_if_window_unreachable(account.handle, since, posts)

    # --- output ---------------------------------------------------------

    def _report(
        self, handle: str, summary: IngestSummary, *, dry_run: bool, source: str
    ) -> None:
        self.stdout.write(
            f"handle={handle} source={source} fetched={summary.fetched} "
            f"created={summary.created} skipped={summary.skipped} "
            f"duplicate_urls={summary.duplicate_urls} dry_run={dry_run}"
        )

    def _warn_if_window_unreachable(
        self, handle: str, since: datetime, posts: list[RawPost]
    ) -> None:
        """State the API window limit instead of under-fetching silently.

        Fires when the endpoint served nothing for the window, or when the
        oldest post it did return is still newer than ``--since`` — either way
        the window may reach past what this endpoint can serve. It is a warning
        rather than an error because an account can simply not have posted early
        in the window.
        """
        oldest = min((post.posted_at for post in posts), default=None)
        if oldest is not None and oldest <= since:
            return
        reached = (
            "the endpoint served no post for this window"
            if oldest is None
            else f"the oldest post it returned ({oldest.isoformat()}) is still newer"
        )
        self.stderr.write(
            self.style.WARNING(
                f"handle={handle}: nothing older than {since.date()} was reachable — "
                f"{reached}. GET /2/users/:id/tweets only serves an account's most "
                f"recent ~{API_WINDOW_POST_LIMIT:,} posts, and start_time/end_time filter "
                "within that window, so history older than the window cannot be "
                "backfilled through this endpoint."
            )
        )
