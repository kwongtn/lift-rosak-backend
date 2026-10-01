"""Migration 0031: flat ``thread`` groups → ordered nested tree, and back.

``incident/migrations/0031_socialmedialink_tree_parent_and_more`` does two
things in one ``RunPython``: it folds the flat one-level ``thread`` groups into
``parent`` (``parent_id = thread_id``, valid because 0030's service-enforced
invariant guaranteed ``thread`` always pointed at a ROOT), then ranks every
sibling with ``Window(RowNumber())`` partitioned by ``parent_id``, ordered by
``occurred_at, id``, times 10.

The two rules the ranking pins are the ones a plausible-looking reimplementation
gets wrong:

* **partition by ``parent_id``** — subtrees are numbered INDEPENDENTLY. A
  global rank would make the second root's first child 30, and the "10, 20, 30"
  contract the tree's auto-append and G1's reorder both rely on would only hold
  for one branch.
* **order by ``occurred_at ASC, id ASC``** — the chronological story, with ``id``
  as the tie-break that makes the order TOTAL. Two links can share an
  ``occurred_at`` (the UI renders minute precision and 0030 documents grouping
  posts that share a minute), and ``RowNumber`` over a non-total order hands
  those two rows arbitrary numbers that can differ between two runs.

The fixtures below therefore DISAGREE with the alternatives on purpose:
``test_position_is_ranked_ten_twenty_thirty_per_parent`` builds siblings whose
insertion (``id``) order is the exact reverse of their ``occurred_at`` order, so
a rank by ``id`` cannot pass by accident, and two subtrees whose occurrences
interleave, so a global rank cannot either.

These tests drive the migration's own module-level functions directly (the
pattern ``test_social_link_occurred_at_backfill.py`` and
``test_legacy_status_backfill.py`` use) rather than replaying the executor: the
interesting behaviour is the SQL the migration emits, and calling
``convert_threads_to_tree(django_apps, None)`` runs it against real rows in the
live test database. A ``MigratorTestCase`` would add a full schema rebuild per
test to exercise the same statements.

THE ``thread_id`` COLUMN DOES NOT EXIST
---------------------------------------
0031 removed it, so a test that needs rows in the PRE-0031 threaded state adds
the column back with the same DDL Django's ``AddField`` emitted, populates it,
runs the migration function, and drops it again (``legacy_thread_column``). That
is the only honest way to exercise the conversion: there is no model field left
to populate, and writing a ``parent_id`` by hand would test nothing. The reverse
half needs the mirror image (``legacy_thread_column`` too, since it writes
``thread_id``), which is why the same helper serves both directions.

TIMEZONE TRAP, and why no datetime is ever read into Python here: ``USE_TZ =
False`` with ``TIME_ZONE = "Asia/Kuala_Lumpur"``, so every stored datetime is
naive LOCAL wall time. The ranking is computed by Postgres over the stored bytes
and only an integer rank is written back, so there is no value to re-interpret —
a well-meaning ``make_aware`` cannot even be placed, because no datetime crosses
the Python boundary. The literal instants below are asserted to survive the
migration byte-identically, which is the check that would fail if a future
revision of this migration grew a Python-side loop.
"""

import importlib
from contextlib import contextmanager
from datetime import datetime

from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import StateApps
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from common.models import User
from incident.models import SocialMediaLink

migration_0031 = importlib.import_module(
    "incident.migrations.0031_socialmedialink_tree_parent_and_more"
)

MIGRATION_0030 = "0030_socialmedialink_occurred_at_socialmedialink_thread_and_more"

#: Naive local instants, deliberately spread so ``occurred_at`` order and ``id``
#: order disagree (see the module docstring).
T0 = datetime(2026, 9, 20, 8, 0, 0)
T1 = datetime(2026, 9, 21, 9, 0, 0)
T2 = datetime(2026, 9, 22, 10, 0, 0)
T3 = datetime(2026, 9, 23, 11, 0, 0)


def historical_apps_at_0031_data_migration():
    """The ``apps`` a ``RunPython`` inside 0031 actually receives.

    The migration functions only ever call ``apps.get_model(...)``, and they
    MUST be handed a model carrying all three columns: ``parent`` and
    ``position`` (added by the two ``AddField``s preceding the ``RunPython``)
    plus ``thread`` (removed by the ``RemoveField`` that follows it). The live
    model no longer has ``thread``, so the ``django.apps.apps`` shortcut that
    ``test_social_link_occurred_at_backfill.py`` uses — correctly, for a column
    that still exists — raises ``FieldError`` here.

    So the state is rebuilt the way the executor builds it: load the project
    state at 0030, replay 0031's own operations onto it up to (but not
    including) the ``RemoveField``, and render a fresh ``StateApps``. That
    historical model has a PLAIN ``Manager``: the tree manager comes from an
    abstract base class at import time, which a historical model does not
    inherit — which is precisely why the migration ranks siblings with plain ORM
    aggregates instead of a tree queryset.
    """
    executor = MigrationExecutor(connection)
    state = executor.loader.project_state(("incident", MIGRATION_0030))
    for operation in migration_0031.Migration.operations:
        if isinstance(operation, migrations.RemoveField):
            break
        operation.state_forwards("incident", state)
    return StateApps(state.real_apps, state.models)


@contextmanager
def legacy_thread_column():
    """Temporarily restore the pre-0031 ``thread_id`` column.

    DDL matches what ``AddField(thread)`` produced: a nullable ``bigint`` with no
    declared foreign key, since ``RemoveField`` drops the constraint first and
    no statement under test depends on it.

    ``SET CONSTRAINTS ALL IMMEDIATE`` runs first: Django declares foreign keys
    ``DEFERRABLE INITIALLY DEFERRED``, so a ``TestCase``'s surrounding
    transaction holds pending trigger events after the fixture inserts and
    Postgres then refuses the DDL outright ("cannot ALTER TABLE ... because it
    has pending trigger events"). Flushing them is a no-op here — every
    deferred FK the fixtures touch is satisfied.
    """
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            "ALTER TABLE incident_socialmedialink ADD COLUMN thread_id bigint NULL"
        )
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE incident_socialmedialink DROP COLUMN thread_id")


def _link(user, **overrides):
    """Create a link, writing ``thread_id`` directly if a thread was named.

    The live model has no ``thread`` field, so the pre-0031 grouping state has
    to be set in the database. ``.update()`` (not ``save()``) also keeps the
    fixture clear of the live tree guard, which is not what these tests are
    about.
    """
    thread = overrides.pop("thread", ...)
    fields = {"url": "https://example.com/post", "user": user}
    fields.update(overrides)
    link = SocialMediaLink.objects.create(**fields)
    if thread is not ...:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE incident_socialmedialink SET thread_id = %s WHERE id = %s",
                [None if thread is None else thread.pk, link.pk],
            )
    return link


def _positions_by_pk():
    return dict(SocialMediaLink.objects.values_list("pk", "position").order_by("pk"))


class LegacyThreadTestCase(TestCase):
    """Base: 0031 is applied to the test database, so the old column is restored.

    Both halves of the ``RunPython`` touch ``thread_id`` — the forward half
    reads it, the reverse half writes it — so *every* test here needs the
    pre-0031 column to exist, and the historical model that knows about it. One
    base class rather than a per-test ``with`` block, because a test that
    forgets the DDL fails with a confusing "column does not exist" from inside
    the migration instead of a clear setUp error.
    """

    def setUp(self):
        super().setUp()
        self.historical_apps = historical_apps_at_0031_data_migration()
        column = legacy_thread_column()
        column.__enter__()
        self.addCleanup(column.__exit__, None, None, None)


class ThreadGroupConversionTests(LegacyThreadTestCase):
    """Forward: ``parent_id = thread_id`` for every row that had a group."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create(firebase_id="test-user-0031-convert")

    def test_a_thread_member_becomes_a_child_of_that_thread_root(self):
        root = _link(self.user, thread=None)
        member = _link(self.user, thread=root)

        migration_0031.convert_threads_to_tree(self.historical_apps, None)

        root.refresh_from_db()
        member.refresh_from_db()
        self.assertIsNone(root.parent_id)
        self.assertEqual(member.parent_id, root.pk)
        # And the shape the tree expects: the member is reachable from the root
        # through the recursive CTE, which is the whole point of the conversion.
        self.assertEqual(list(root.children.all()), [member])

    def test_a_row_that_was_never_threaded_stays_a_root(self):
        # The 0030 default: every pre-existing ungrouped link had
        # ``thread_id IS NULL`` and must survive as a root, not as a row
        # pointing at itself or at nothing-in-particular.
        lonely = _link(self.user, thread=None)

        migration_0031.convert_threads_to_tree(self.historical_apps, None)

        lonely.refresh_from_db()
        self.assertIsNone(lonely.parent_id)
        self.assertEqual(lonely.position, migration_0031.POSITION_STEP)

    def test_a_group_of_five_becomes_a_one_level_tree_of_five(self):
        # Conversion is a straight copy, not a walk: the members keep pointing
        # at the root, none of them is re-pointed at the root's parent (there is
        # none), and the root keeps none of its old semantics beyond being a root.
        root = _link(self.user, thread=None)
        members = [_link(self.user, thread=root) for _ in range(5)]

        migration_0031.convert_threads_to_tree(self.historical_apps, None)

        self.assertEqual(
            sorted(
                SocialMediaLink.objects.filter(parent_id=root.pk).values_list(
                    "pk", flat=True
                )
            ),
            sorted(link.pk for link in members),
        )
        self.assertEqual(
            list(
                SocialMediaLink.objects.filter(parent__isnull=True).values_list(
                    "pk", flat=True
                )
            ),
            [root.pk],
        )

    def test_the_conversion_is_a_single_update_and_does_not_rewrite_datetimes(self):
        # Two properties, one assertion each.
        root = _link(self.user, thread=None)
        member = _link(self.user, thread=root, occurred_at=T1, posted_at=T1)
        before = member.occurred_at

        with CaptureQueriesContext(connection) as ctx:
            migration_0031.convert_threads_to_tree(self.historical_apps, None)

        # 1. The group copy is ONE update, not a Python read/modify/write loop:
        #    the ids move inside the database, so nothing can be re-interpreted
        #    in another timezone frame on the way through. (The fixture's own
        #    raw ``SET thread_id`` write is outside the capture.)
        updates = [
            q["sql"]
            for q in ctx.captured_queries
            if '"parent_id" = "incident_socialmedialink"."thread_id"' in q["sql"]
        ]
        self.assertEqual(len(updates), 1)

        # 2. The stored instant is byte-identical afterwards (USE_TZ = False, so
        #    naive local wall time in, naive local wall time out).
        member.refresh_from_db()
        self.assertIsNone(member.occurred_at.tzinfo)
        self.assertEqual(member.occurred_at.isoformat(), before.isoformat())
        self.assertEqual(member.occurred_at.isoformat(), T1.isoformat())


class PositionBackfillTests(LegacyThreadTestCase):
    """Forward: ``Window(RowNumber())`` over ``(parent_id)`` / ``(occurred_at, id)``."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create(firebase_id="test-user-0031-position")

    def test_position_is_ranked_ten_twenty_thirty_per_parent(self):
        # Deliberately created in REVERSE chronological order, so the insertion
        # (``id``) order is the exact inverse of the ``occurred_at`` order: a
        # rank by ``id`` produces 10, 20, 30 in the wrong sequence and fails.
        late = _link(self.user, occurred_at=T3)
        middle = _link(self.user, occurred_at=T2)
        early = _link(self.user, occurred_at=T1)

        migration_0031.convert_threads_to_tree(self.historical_apps, None)

        positions = _positions_by_pk()
        self.assertEqual(positions[early.pk], 10)
        self.assertEqual(positions[middle.pk], 20)
        self.assertEqual(positions[late.pk], 30)
        # The rule is "earliest occurrence first", not "lowest id first": the
        # insertion order is the exact reverse of the ranking.
        self.assertGreater(early.pk, middle.pk)
        self.assertGreater(middle.pk, late.pk)

    def test_siblings_in_different_subtrees_are_numbered_independently(self):
        # Two roots, their occurrences interleaved in time. A global rank would
        # give root B's first child 40; the per-parent partition gives it 10
        # again, which is what makes the "10, 20, 30" contract hold on every
        # branch rather than only on the first.
        root_a = _link(self.user, occurred_at=T0)
        root_b = _link(self.user, occurred_at=T0)
        a1 = _link(self.user, parent=root_a, occurred_at=T3)
        b1 = _link(self.user, parent=root_b, occurred_at=T2)
        a2 = _link(self.user, parent=root_a, occurred_at=T1)
        b2 = _link(self.user, parent=root_b, occurred_at=T0)

        migration_0031.convert_threads_to_tree(self.historical_apps, None)

        positions = _positions_by_pk()
        # Root A's children by occurrence: a2 (T1) then a1 (T3).
        self.assertEqual(positions[a2.pk], 10)
        self.assertEqual(positions[a1.pk], 20)
        # Root B's children by occurrence: b2 (T0) then b1 (T2). Independent
        # numbering, and a different sequence from A's despite the interleaving.
        self.assertEqual(positions[b2.pk], 10)
        self.assertEqual(positions[b1.pk], 20)
        # The roots are a sibling set too (both ``parent_id IS NULL``) and are
        # ranked among themselves: T0 ties, so ``id`` decides.
        self.assertEqual(positions[root_a.pk], 10)
        self.assertEqual(positions[root_b.pk], 20)

    def test_rows_sharing_an_occurred_at_are_broken_by_id(self):
        # The tie-break, and the reason it is not decorative: the UI renders
        # minute precision, so two links submitted together share an
        # ``occurred_at`` exactly. Without ``id`` in the ``ORDER BY``,
        # ``RowNumber`` would hand these two arbitrary numbers.
        tie_a = _link(self.user, occurred_at=T1)
        tie_b = _link(self.user, occurred_at=T1)
        self.assertEqual(tie_a.occurred_at, tie_b.occurred_at)
        self.assertLess(tie_a.pk, tie_b.pk)

        migration_0031.convert_threads_to_tree(self.historical_apps, None)

        positions = _positions_by_pk()
        self.assertEqual(positions[tie_a.pk], 10)
        self.assertEqual(positions[tie_b.pk], 20)
        # Distinct values, not a tie: two siblings at the same position would
        # make the sequence non-deterministic for the client.
        self.assertNotEqual(positions[tie_a.pk], positions[tie_b.pk])

    def test_a_converted_member_is_ranked_among_its_new_siblings(self):
        # The conversion runs FIRST and the ranking reads the FINAL
        # ``parent_id``, so the ranking is computed over the tree the conversion
        # produced rather than over the pre-0031 grouping. The members are
        # created in the REVERSE of their occurrence order, so a ranking taken
        # by ``id`` cannot pass.
        root = _link(self.user, thread=None, occurred_at=T1)
        other_root = _link(self.user, thread=None, occurred_at=T0)
        late_member = _link(self.user, thread=root, occurred_at=T3)
        early_member = _link(self.user, thread=root, occurred_at=T2)
        # Insertion order is the reverse of occurrence order, so ranking by
        # ``id`` would swap these two.
        self.assertGreater(early_member.pk, late_member.pk)

        migration_0031.convert_threads_to_tree(self.historical_apps, None)

        positions = _positions_by_pk()
        # The two roots are one sibling set, ranked by occurrence: other_root
        # (T0) then root (T1).
        self.assertEqual(positions[other_root.pk], 10)
        self.assertEqual(positions[root.pk], 20)
        # The two members are a DIFFERENT sibling set under the root, ranked by
        # occurrence: early_member (T2) then late_member (T3) — the LOWER id of
        # the pair takes position 20, so an id-based ranking cannot pass.
        self.assertEqual(positions[early_member.pk], 10)
        self.assertEqual(positions[late_member.pk], 20)
        # And the conversion really did the re-parenting the ranking depends on.
        self.assertEqual(
            SocialMediaLink.objects.get(pk=late_member.pk).parent_id, root.pk
        )
        self.assertEqual(
            sorted(
                SocialMediaLink.objects.filter(parent_id=root.pk).values_list(
                    "pk", flat=True
                )
            ),
            sorted([early_member.pk, late_member.pk]),
        )

    def test_the_backfill_writes_batches_through_bulk_update(self):
        # ``bulk_update`` in batches, so a large table is not held in memory and
        # the historical model's ``save()`` (and therefore the live tree guard)
        # never runs. Asserted by counting statements: one windowed SELECT, one
        # UPDATE per batch, and no per-row SELECT.
        for _ in range(4):
            _link(self.user, occurred_at=T0)

        with CaptureQueriesContext(connection) as ctx:
            migration_0031.convert_threads_to_tree(self.historical_apps, None)

        # Only the write that touches ``position``; the conversion's own
        # ``SET parent_id = thread_id`` runs as a statement even when it matches
        # no row, so counting bare UPDATEs would be off by one here.
        updates = [
            q["sql"]
            for q in ctx.captured_queries
            if '"position" = ' in q["sql"]
            and q["sql"].lstrip().upper().startswith("UPDATE")
        ]
        selects = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].lstrip().upper().startswith("SELECT")
        ]
        # One batch (4 rows < BATCH_SIZE) and it touched only ``position``.
        self.assertEqual(len(updates), 1)
        self.assertIn('"position" = ', updates[0])
        # The ranking is computed by Postgres in one windowed SELECT.
        self.assertEqual(len(selects), 1)
        self.assertIn("ROW_NUMBER() OVER", selects[0])
        self.assertIn("PARTITION BY", selects[0])
        self.assertIn('ORDER BY "incident_socialmedialink"."occurred_at"', selects[0])
        self.assertIn('"incident_socialmedialink"."id"', selects[0])


class ReverseMigrationTests(LegacyThreadTestCase):
    """Reverse: rebuild ``thread`` from ``parent``, zero ``position``."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create(firebase_id="test-user-0031-reverse")
        # A tree built with the LIVE model, standing in for rows a forward run
        # of the migration would have left behind.
        self.root = _link(self.user)
        self.child = _link(self.user, parent=self.root)
        self.grandchild = _link(self.user, parent=self.child)

    def test_the_reverse_reconstructs_thread_from_parent(self):
        migration_0031.revert_tree_to_threads(self.historical_apps, None)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, thread_id FROM incident_socialmedialink ORDER BY id"
            )
            rows = dict(cursor.fetchall())

        # Every parented row points at its parent: the pre-0031 shape for a
        # depth-1 group. The root had no parent and so had no thread. Asserting
        # on ``parent`` alone would not prove ``thread`` was written — this
        # reads the column itself.
        self.assertIsNone(rows[self.root.pk])
        self.assertEqual(rows[self.child.pk], self.root.pk)
        self.assertEqual(rows[self.grandchild.pk], self.child.pk)

    def test_the_reverse_leaves_parent_alone(self):
        # The reverse reconstructs the old column; it must NOT "tidy up" the new
        # one, because the forward half has to be able to re-derive the same
        # grouping afterwards. A reverse that zeroed ``parent_id`` would silently
        # flatten the tree on every rollback.
        migration_0031.revert_tree_to_threads(self.historical_apps, None)

        self.assertEqual(
            SocialMediaLink.objects.get(pk=self.child.pk).parent_id, self.root.pk
        )
        self.assertEqual(
            SocialMediaLink.objects.get(pk=self.grandchild.pk).parent_id,
            self.child.pk,
        )

    def test_the_reverse_zeroes_position(self):
        self.assertEqual(self.root.position, 10)
        self.assertEqual(self.child.position, 10)
        self.assertEqual(self.grandchild.position, 10)

        migration_0031.revert_tree_to_threads(self.historical_apps, None)

        # ``position`` has no pre-0031 counterpart, so the closest reversible
        # value is the field default the ``AddField`` would have produced.
        for link in (self.root, self.child, self.grandchild):
            link.refresh_from_db()
            self.assertEqual(link.position, 0)

    def test_a_forward_reverse_round_trip_preserves_the_grouping(self):
        # This is the regression the reversibility claim rests on: a rollback
        # followed by a re-apply must land on the same tree, not a flattened one.
        root = _link(self.user, thread=None, occurred_at=T0)
        member_a = _link(self.user, thread=root, occurred_at=T1)
        member_b = _link(self.user, thread=root, occurred_at=T2)

        migration_0031.convert_threads_to_tree(self.historical_apps, None)
        after_first_forward = _positions_by_pk()
        # The forward run's shape is what the round trip has to reproduce: two
        # members under the root, ranked T1 then T2.
        self.assertEqual(after_first_forward[member_a.pk], 10)
        self.assertEqual(after_first_forward[member_b.pk], 20)

        migration_0031.revert_tree_to_threads(self.historical_apps, None)
        migration_0031.convert_threads_to_tree(self.historical_apps, None)

        # ``position`` is zeroed by the reverse, but the DERIVED sequence comes
        # back identical: the re-run re-derives it from ``occurred_at, id``
        # alone, and the reverse left ``parent_id`` alone. This is what makes
        # "migrate back then migrate forward" safe to run in a rollback.
        self.assertEqual(_positions_by_pk(), after_first_forward)
        self.assertEqual(SocialMediaLink.objects.get(pk=member_a.pk).parent_id, root.pk)
        self.assertEqual(SocialMediaLink.objects.get(pk=member_b.pk).parent_id, root.pk)
        self.assertIsNone(SocialMediaLink.objects.get(pk=root.pk).parent_id)
