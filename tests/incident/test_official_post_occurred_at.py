"""Regression tests for ingestion writing ``SocialMediaLink.occurred_at``.

``occurred_at`` is the user-facing "when did this happen" instant the link card
renders and every feed ordering, day-grouping header and keyset cursor is built
on. ``posted_at`` stays the read-only provider provenance column that
``manage.py export_official_posts`` reads. On the automated path both are written
from the single ``RawPost.posted_at``, so they cannot drift — and
``ingest_posts`` is the only writer, because the beat tick, the manual command's
live and ``--fixture`` runs, and the X webhook all funnel through it.

THE TRAP THIS FILE EXISTS FOR (MISTAKES.md, 2026-09-26, "an exported
``posted_at`` is naive **local** time"): ``USE_TZ = False`` with
``TIME_ZONE = "Asia/Kuala_Lumpur"``, and ``_parse_created_at`` always returns an
AWARE datetime. The Postgres adapter drops the tzinfo and shifts into the local
frame on the way in, so a post the X API reports as ``2026-09-26T03:15:00Z`` is
stored as ``2026-09-26T11:15:00``. A well-meaning ``make_aware``/``astimezone``
on either field would double-shift every post by +08:00, and because the UI
renders minute precision the shift is invisible on screen — it would only
surface later as links landing in the wrong calendar day against the service-day
window. So the stored values are pinned by literal, and the two wrong answers
(the un-shifted UTC instant, and a double-shifted +16:00) are pinned as explicit
non-equalities.

Self-contained by design: the fixture path and the ``RawPost`` builder live here
rather than being imported from the 5k-line ``incident/tests.py``, which is a test
module in its own right and would drag its whole suite behind this one.
"""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from incident.enums import IngestPlatform
from incident.models import SocialMediaLink
from incident.services.official_posts import (
    RawPost,
    get_system_author,
    ingest_posts,
    load_fixture_posts,
)
from incident.services.x_webhooks import ingest_webhook_payload

#: The saved ``GET /2/users/{id}/tweets`` payload the ingest tests already use,
#: so this file drives the real provider shape rather than a hand-built copy of
#: it. Its first tweet reports ``created_at: "2026-09-26T03:15:00.000Z"`` and its
#: second ``"2026-09-26T05:42:31.000Z"``.
SAMPLE_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "incident"
    / "fixtures"
    / "x_user_tweets_sample.json"
)

#: What the X API reports for the fixture's first tweet, as the aware datetime
#: ``_parse_created_at`` hands to ``ingest_posts``.
POSTED_AT_AWARE = datetime(2026, 9, 26, 3, 15, tzinfo=UTC)
#: What the column therefore holds after the ORM shifted it into the local frame
#: (Asia/Kuala_Lumpur, +08:00). Same minute, eight hours later.
POSTED_AT_LOCAL = datetime(2026, 9, 26, 11, 15, 0)
#: The second fixture tweet, so a second value proves the shift is applied per
#: value rather than being a hardcoded special case.
SECOND_AWARE = datetime(2026, 9, 26, 5, 42, 31, tzinfo=UTC)
SECOND_LOCAL = datetime(2026, 9, 26, 13, 42, 31)

#: The handle migration 0029 seeds, with its provider user id baked in.
TRACKED_HANDLE = "askrapidkl"
#: A post id no other test uses, so a stray row from a neighbouring test can
#: never satisfy ``.get()`` instead of the row this test created.
POST_ID = "1791559300000000001"


def _raw_post(
    *,
    post_id: str = POST_ID,
    handle: str = TRACKED_HANDLE,
    text: str = "Gangguan di laluan utama",
    posted_at: datetime = POSTED_AT_AWARE,
    url: str | None = None,
) -> RawPost:
    """One normalized provider post, shaped exactly as ``tweet_to_raw_post`` builds it.

    ``url`` is overridable so a test can present a *different* post id under the
    *same* permalink — the shape the ``normalized_url`` dedup exists for.
    """
    return RawPost(
        platform=IngestPlatform.X,
        post_id=post_id,
        handle=handle,
        text=text,
        posted_at=posted_at,
        url=url or f"https://x.com/{handle}/status/{post_id}",
        has_media=False,
        raw={"id": post_id, "created_at": posted_at.isoformat()},
    )


def _xaa_post_create_payload(*, post_id: str, created_at: str) -> dict:
    """A minimal Activity API ``post.create`` delivery for a tracked account.

    Only the fields ``_create_items`` / ``_users_by_id`` / ``tweet_to_raw_post``
    read are present. The ``includes.users`` expansion is what attributes the
    post without a network call — the registry row keyed by provider user id is
    not this fictitious id, so without the expansion the post would be dropped
    as unresolved rather than ingested.
    """
    author_id = "2244994945"
    return {
        "data": {
            "event_type": "post.create",
            "payload": {
                "id": post_id,
                "text": "Gangguan di laluan utama",
                "created_at": created_at,
                "author_id": author_id,
            },
            "includes": {
                "users": [
                    {"id": author_id, "username": TRACKED_HANDLE, "name": "RapidKL"}
                ]
            },
        }
    }


class IngestWritesOccurredAtTests(TestCase):
    """``ingest_posts`` writes the user-facing twin next to the provenance column."""

    def setUp(self):
        # Seeded by migration 0027's data migration; a missing seed must fail
        # loudly, so this is not mocked.
        self.author = get_system_author()

    def test_an_ingested_row_carries_occurred_at_equal_to_posted_at(self):
        post = _raw_post()

        summary = ingest_posts([post], author=self.author)

        self.assertEqual(summary.created, 1)
        link = SocialMediaLink.objects.get(post_id=POST_ID)
        # Both columns populated and carrying the SAME instant — the automated
        # path has exactly one source value, so there is nothing to drift.
        self.assertIsNotNone(link.occurred_at)
        self.assertIsNotNone(link.posted_at)
        self.assertEqual(link.occurred_at, link.posted_at)
        # ``posted_at`` keeps its meaning and is still written: the export
        # command's only input is unaffected by the new field.
        self.assertEqual(link.posted_at, timezone.make_naive(post.posted_at))
        # And neither is the ingest time, which is what a missing write would
        # silently leave behind.
        self.assertNotEqual(link.occurred_at, link.created)

    def test_the_aware_provider_instant_lands_as_naive_local_wall_time(self):
        # Driven through the real loader so the aware value is produced by the
        # real parser, not hand-built here.
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))
        self.assertEqual(posts[0].posted_at, POSTED_AT_AWARE)
        self.assertIsNotNone(posts[0].posted_at.tzinfo)

        ingest_posts(posts, author=self.author)

        link = SocialMediaLink.objects.get(post_id=posts[0].post_id)
        # Read the COLUMN back: the in-memory instance still holds the aware
        # value it was created with, because the conversion happens in the DB
        # adapter, not in Python.
        self.assertIsNone(link.occurred_at.tzinfo)
        self.assertIsNone(link.posted_at.tzinfo)
        self.assertEqual(link.occurred_at, POSTED_AT_LOCAL)
        # Byte-identical, not merely equal to the right minute.
        self.assertEqual(link.occurred_at.isoformat(), "2026-09-26T11:15:00")
        # Neither of the two wrong answers: the un-shifted UTC instant (03:15),
        # or a second +08:00 on top of the already-local value (19:15).
        self.assertNotEqual(link.occurred_at, POSTED_AT_LOCAL - timedelta(hours=8))
        self.assertNotEqual(link.occurred_at, POSTED_AT_LOCAL + timedelta(hours=8))
        # A second, differently-timed post proves the shift is applied per value
        # rather than being a property of one hardcoded instant.
        other = SocialMediaLink.objects.get(post_id=posts[1].post_id)
        self.assertEqual(posts[1].posted_at, SECOND_AWARE)
        self.assertEqual(other.occurred_at, SECOND_LOCAL)
        self.assertEqual(other.occurred_at.isoformat(), "2026-09-26T13:42:31")

    def test_re_ingesting_the_same_post_leaves_occurred_at_untouched(self):
        post = _raw_post()
        first = ingest_posts([post], author=self.author)
        link = SocialMediaLink.objects.get(post_id=POST_ID)
        self.assertEqual(link.occurred_at, POSTED_AT_LOCAL)

        # Stand in for a row whose display instant a human later adjusted: the
        # re-ingest must not quietly revert it, because the duplicate branch
        # takes no write at all.
        adjusted = datetime(2026, 9, 27, 9, 30, 0)
        SocialMediaLink.objects.filter(pk=link.pk).update(occurred_at=adjusted)

        second = ingest_posts([post], author=self.author)

        self.assertEqual(first.created, 1)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.skipped, 1)
        self.assertEqual(second.created_ids, ())
        self.assertEqual(SocialMediaLink.objects.count(), 1)
        link.refresh_from_db()
        self.assertEqual(link.occurred_at, adjusted)
        # The read-only provenance column is equally untouched by a re-ingest:
        # a redelivery must not restate the provider's own instant either.
        self.assertEqual(link.posted_at, POSTED_AT_LOCAL)

    def test_a_dry_run_writes_nothing_so_it_never_sets_the_field(self):
        summary = ingest_posts([_raw_post()], author=self.author, dry_run=True)

        # The projected count still reflects what a real run would create.
        self.assertEqual(summary.fetched, 1)
        self.assertEqual(summary.created, 1)
        self.assertEqual(summary.created_ids, ())
        # No row at all is the only way to leave ``occurred_at`` unset — the
        # column is NOT NULL, so a preview could not half-populate it either.
        self.assertEqual(SocialMediaLink.objects.count(), 0)

    def test_a_duplicate_url_creates_no_twin_and_writes_no_occurred_at(self):
        original = _raw_post()
        ingest_posts([original], author=self.author)
        existing = SocialMediaLink.objects.get(post_id=POST_ID)

        # Same permalink under the other tracked account, with a post id the
        # store has never seen — so only the normalized_url check can catch it.
        twin = _raw_post(
            post_id="1791559300000000002", handle="myrapidkl", url=original.url
        )
        summary = ingest_posts([twin], author=self.author)

        self.assertEqual(summary.duplicate_urls, 1)
        self.assertEqual(summary.created, 0)
        self.assertEqual(SocialMediaLink.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.socmed_account.handle, TRACKED_HANDLE)
        self.assertEqual(existing.occurred_at, POSTED_AT_LOCAL)


class WebhookPathWritesOccurredAtTests(TestCase):
    """The X webhook reaches ``ingest_posts``, so it inherits the field.

    The webhook builds its own ``RawPost``s via the shared
    ``tweet_to_raw_post`` and hands them to the shared ``ingest_posts``; this
    pins that structurally, because a future path that wrote a ``SocialMediaLink``
    directly would leave the delivered post with the field default (ingest time)
    and the feed would silently mis-order it.
    """

    def test_a_delivery_stores_occurred_at_at_the_post_time(self):
        payload = _xaa_post_create_payload(
            post_id="1791559400000000001",
            created_at="2026-09-28T04:05:00.000Z",
        )

        result = ingest_webhook_payload(payload)

        self.assertEqual(result.ingested, 1)
        link = SocialMediaLink.objects.get(post_id="1791559400000000001")
        self.assertEqual(link.occurred_at, datetime(2026, 9, 28, 12, 5, 0))
        self.assertEqual(link.occurred_at, link.posted_at)
        # Post time, not delivery time.
        self.assertNotEqual(link.occurred_at, link.created)


class ExportStaysOnPostedAtTests(TestCase):
    """The export keeps reading the provenance column, not the display twin.

    The docstring now says so explicitly, which makes it a claim worth pinning:
    an archive is a record of what the provider published, so switching the
    exported column to ``occurred_at`` would change the meaning of every
    previously published dataset.
    """

    def setUp(self):
        self.author = get_system_author()
        ingest_posts([_raw_post()], author=self.author)

    def _records(self) -> list[dict]:
        """Run the export with its default ``--output -`` and parse the JSONL."""
        out = StringIO()
        call_command("export_official_posts", stdout=out, stderr=StringIO())
        return [json.loads(line) for line in out.getvalue().splitlines() if line]

    def test_the_exported_column_is_posted_at_and_occurred_at_is_not_added(self):
        records = self._records()

        self.assertEqual(len(records), 1)
        self.assertEqual(
            list(records[0]),
            ["post_id", "posted_at", "handle", "text", "permalink"],
        )
        self.assertEqual(records[0]["posted_at"], "2026-09-26T11:15:00")
        self.assertNotIn("occurred_at", records[0])
        # The two columns hold the same instant, so which one is read is a
        # documented decision rather than a difference in the emitted bytes —
        # which is exactly why switching it would be a silent contract change.
        link = SocialMediaLink.objects.get(post_id=POST_ID)
        self.assertEqual(records[0]["posted_at"], link.occurred_at.isoformat())
