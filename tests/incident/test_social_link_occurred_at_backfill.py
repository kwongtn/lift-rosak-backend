"""Regression tests for the incident 0030 ``SocialMediaLink.occurred_at`` backfill.

``occurred_at`` is the user-facing "when did this happen" instant every feed
ordering and the keyset cursor are built on. Migration 0030 seeds it for
pre-existing rows with ``COALESCE(posted_at, created)`` and can be reverted with
``created``.

These tests drive the migration's own module-level functions directly (the
pattern ``test_legacy_status_backfill.py`` uses) rather than replaying the
executor: the interesting behaviour is the SQL the backfill emits, and calling
``backfill_occurred_at(django_apps, None)`` runs that SQL against real rows in
the live test database. A ``MigratorTestCase`` would add a full schema rebuild
per test to exercise the same single ``UPDATE``.

THE TRAP THIS FILE EXISTS FOR (MISTAKES.md, 2026-09-26, "an exported
``posted_at`` is naive **local** time"): ``USE_TZ = False`` with
``TIME_ZONE = "Asia/Kuala_Lumpur"``, so both ``posted_at`` and ``created`` are
already naive local wall time and the backfill is a byte copy. A well-meaning
``make_aware``/``astimezone`` in the migration would shift every value by +08:00,
and because the UI renders minute precision the shift is invisible on screen —
it would only surface later as links landing in the wrong calendar day against
the service-day window. So the value is pinned by literal, and the two wrong
answers (the un-shifted UTC instant, and a double-shifted +16:00) are pinned as
explicit non-equalities.
"""

import importlib
from datetime import UTC, datetime, timedelta

from django.apps import apps as django_apps
from django.test import TestCase
from django.utils import timezone

from common.models import User
from incident.models import SocialMediaLink

migration_0030 = importlib.import_module(
    "incident.migrations.0030_socialmedialink_occurred_at_socialmedialink_thread_and_more"
)

# What the X API reported as 2026-09-26T03:15:00Z, after ingestion stored it
# through the ORM and the ORM shifted it into the local frame. This is what the
# column holds, and therefore what the backfill has to copy.
POSTED_AT_LOCAL = datetime(2026, 9, 26, 11, 15, 0)
# The pre-0030 value the backfill is standing in for: the column would have been
# filled with the field default (``timezone.now()``) by ``AddField``, i.e.
# something close to "right now" and nothing like the real event time.
PRE_BACKFILL_OCCURRED_AT = datetime(2026, 9, 30, 8, 0, 0)


def _link(user, **overrides):
    fields = {"url": "https://example.com/post", "user": user}
    fields.update(overrides)
    return SocialMediaLink.objects.create(**fields)


class OccurredAtBackfillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-occurred")

    def test_a_row_with_a_post_time_takes_that_post_time_verbatim(self):
        link = _link(self.user, posted_at=POSTED_AT_LOCAL, is_automated=True)
        # Stand in for the state AddField leaves behind: ``occurred_at`` present
        # but holding the default, so the backfill has real work to do.
        SocialMediaLink.objects.filter(pk=link.pk).update(
            occurred_at=PRE_BACKFILL_OCCURRED_AT
        )

        migration_0030.backfill_occurred_at(django_apps, None)

        link.refresh_from_db()
        self.assertEqual(link.occurred_at, POSTED_AT_LOCAL)
        # Byte-identical, not merely equal to the right minute.
        self.assertEqual(link.occurred_at.isoformat(), "2026-09-26T11:15:00")
        # The real post time wins over the row's creation time.
        self.assertNotEqual(link.occurred_at, link.created)
        # Neither of the two wrong answers: the un-shifted UTC instant (03:15),
        # or a second +08:00 on top of the already-local value (19:15).
        self.assertNotEqual(link.occurred_at, POSTED_AT_LOCAL - timedelta(hours=8))
        self.assertNotEqual(link.occurred_at, POSTED_AT_LOCAL + timedelta(hours=8))

    def test_a_row_without_a_post_time_falls_back_to_created(self):
        link = _link(self.user, posted_at=None)
        SocialMediaLink.objects.filter(pk=link.pk).update(
            occurred_at=PRE_BACKFILL_OCCURRED_AT
        )

        migration_0030.backfill_occurred_at(django_apps, None)

        link.refresh_from_db()
        self.assertIsNone(link.posted_at)
        self.assertEqual(link.occurred_at, link.created)
        self.assertEqual(link.occurred_at.isoformat(), link.created.isoformat())

    def test_a_row_ingested_with_an_aware_post_time_is_not_shifted_twice(self):
        # The ingestion path stores an aware UTC value through the ORM, which
        # drops the tzinfo and shifts to local. The backfill must then copy the
        # already-local stored value, NOT re-apply the conversion.
        aware_post_time = datetime(2026, 9, 26, 3, 15, tzinfo=UTC)
        link = _link(self.user, posted_at=aware_post_time, is_automated=True)
        # The in-memory instance still holds the aware value it was built with;
        # the conversion happens in the DB adapter, so read the COLUMN back —
        # which is what the backfill sees. This is the same re-fetch
        # ``incident/tests.py`` does before asserting naive-local storage.
        link.refresh_from_db()
        self.assertEqual(link.posted_at, timezone.make_naive(aware_post_time))
        self.assertEqual(link.posted_at, POSTED_AT_LOCAL)
        self.assertIsNone(link.posted_at.tzinfo)
        SocialMediaLink.objects.filter(pk=link.pk).update(
            occurred_at=PRE_BACKFILL_OCCURRED_AT
        )

        migration_0030.backfill_occurred_at(django_apps, None)

        link.refresh_from_db()
        self.assertEqual(link.occurred_at, POSTED_AT_LOCAL)

    def test_the_reverse_half_pins_occurred_at_to_created(self):
        link = _link(self.user, posted_at=POSTED_AT_LOCAL, is_automated=True)
        SocialMediaLink.objects.filter(pk=link.pk).update(
            occurred_at=PRE_BACKFILL_OCCURRED_AT
        )

        migration_0030.backfill_occurred_at(django_apps, None)
        migration_0030.revert_occurred_at_to_created(django_apps, None)

        link.refresh_from_db()
        self.assertEqual(link.occurred_at, link.created)
        # The migration has no destructive half: provider provenance survives
        # a full forward + reverse round trip untouched.
        self.assertEqual(link.posted_at, POSTED_AT_LOCAL)

    def test_a_new_row_defaults_occurred_at_to_now(self):
        before = timezone.now()
        link = _link(self.user)
        after = timezone.now()

        self.assertGreaterEqual(link.occurred_at, before)
        self.assertLessEqual(link.occurred_at, after)
        # Non-null by design: keyset pagination on (-occurred_at, -id) needs a
        # total order, so a fresh row can never land in a NULL gap. The column
        # is NOT NULL, but a re-read still proves the Python-side default made
        # it all the way to storage rather than being dropped on INSERT.
        link.refresh_from_db()
        self.assertIsNotNone(link.occurred_at)
        self.assertGreaterEqual(link.occurred_at, before)
        self.assertLessEqual(link.occurred_at, after)

    def test_occurred_at_orders_under_the_composite_index_keyset(self):
        # The index exists to serve `ORDER BY occurred_at DESC, id DESC`, so the
        # pair has to be a total order: two links sharing an instant still sort
        # deterministically by id.
        older = _link(self.user, occurred_at=datetime(2026, 9, 26, 9, 0, 0))
        newer = _link(self.user, occurred_at=datetime(2026, 9, 26, 10, 0, 0))
        tie_a = _link(self.user, occurred_at=datetime(2026, 9, 26, 10, 0, 0))
        tie_b = _link(self.user, occurred_at=datetime(2026, 9, 26, 10, 0, 0))

        ordered = list(
            SocialMediaLink.objects.order_by("-occurred_at", "-id").values_list(
                "pk", flat=True
            )
        )
        self.assertEqual(ordered, [tie_b.pk, tie_a.pk, newer.pk, older.pk])


class ThreadRootInvariantsTests(TestCase):
    """The DB-level half of the threading contract; B5 enforces the rest.

    ``thread`` must be nullable-with-a-default so an ungrouped link needs no
    value, and ``on_delete=SET_NULL`` is the documented trade that keeps a
    deleted root from taking its members with it.
    """

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-thread")
        self.root = _link(self.user, thread=None)
        self.member = _link(self.user, thread=self.root)

    def test_an_ungrouped_link_has_no_thread(self):
        ungrouped = _link(self.user)
        self.assertIsNone(ungrouped.thread_id)

    def test_a_root_is_reachable_from_its_members(self):
        self.assertIsNone(self.root.thread_id)
        self.assertEqual(self.member.thread, self.root)
        self.assertEqual(list(self.root.thread_members.all()), [self.member])

    def test_deleting_a_root_un_threads_its_members_instead_of_cascading(self):
        self.root.delete()

        member = SocialMediaLink.objects.get(pk=self.member.pk)
        self.assertIsNone(member.thread_id)
