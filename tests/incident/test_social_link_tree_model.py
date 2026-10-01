"""``SocialMediaLink`` as an ordered nested tree: model contract + cycle guard.

Migration 0031 replaced the flat one-level ``thread`` self-FK with
``django-tree-queries``' ``OrderableTreeNode``: a ``parent`` FK (arbitrary
depth) plus ``position`` (the sibling sequence). These tests pin the parts of
that contract the library does NOT give for free.

THE THREE TRAPS THIS FILE EXISTS FOR
------------------------------------
1. **Two abstract base models, silently.** ``SocialMediaLink`` now inherits both
   ``TimeStampedModel`` (``created`` / ``modified``) and ``OrderableTreeNode``
   (``position``, ``parent``, ``objects``). Django merges abstract bases through
   the MRO and drops a duplicate silently, so "it imported" proves nothing —
   ``test_tree_and_timestamp_fields_all_survive_the_multiple_inheritance``
   asserts every field of both bases is really on the model.
2. **Loop protection is ``clean()``-only, so a plain ``save()`` creates cycles.**
   The library raises from ``TreeNode.clean()``, which only ``full_clean()``
   calls. The consequence is not a cosmetic tree bug: the recursive CTE anchors
   on ``parent_id IS NULL``, so a node inside a cycle is unreachable from every
   tree query, and ``ancestors()`` on it raises ``DoesNotExist`` (a 500) rather
   than returning an empty list. ``SocialMediaLink.save()`` therefore re-runs
   the check, and ``test_a_plain_save_that_would_close_a_cycle_is_rejected`` is
   the test that would fail loudly if that override were ever dropped. The
   ``update_fields`` carve-out that keeps the check off the moderation path has
   the same weight, which is why
   ``test_an_update_fields_save_spelled_with_the_attname_is_still_guarded``
   exists: Django keys ``update_fields`` on a field's name **or** attname, and a
   carve-out that matched only one of them is a hole rather than an
   optimisation.
3. **``on_delete`` is deliberately inverted.** The library's inherited FK is
   ``CASCADE``; this model overrides it to ``SET_NULL``, so deleting a link
   PROMOTES its subtree to roots instead of deleting it. That is a non-
   destructive trade, so it is pinned by a test rather than left to a comment.

Runs under plain ``django.test.TestCase`` and deliberately does NOT import
pytest: pytest is not installed in the app image, so a pytest-based file here is
uncollectable dead code.
"""

from django.core.exceptions import ValidationError
from django.db import connection, models
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from common.models import User
from incident.enums import SocialMediaLinkStatus
from incident.models import SocialMediaLink

#: ``OrderableTreeNode.save()`` issues one ``MAX(position)`` aggregate alongside
#: the write, to compute the append position when ``position`` is falsy — so a
#: create is two queries. Note the trigger is ``if not self.position:`` with no
#: ``_state.adding`` gate, i.e. it is NOT INSERT-scoped: a row whose
#: ``position`` is ``0`` (the column default, and what ``bulk_create`` leaves
#: behind) pays the aggregate on any later save too. The constant is named so a
#: change to the library's own auto-assign is a legible diff rather than a
#: mystery.
CREATE_QUERIES = 2
UPDATE_QUERIES = 1


def _link(user, **overrides):
    fields = {"url": "https://example.com/post", "user": user}
    fields.update(overrides)
    return SocialMediaLink.objects.create(**fields)


class TreeModelShapeTests(TestCase):
    """The field/MRO contract, asserted on the class rather than on behaviour."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-shape")

    def test_tree_and_timestamp_fields_all_survive_the_multiple_inheritance(self):
        names = {f.name for f in SocialMediaLink._meta.get_fields()}
        # From ``OrderableTreeNode``: the tree FK and the sibling sequence.
        self.assertIn("parent", names)
        self.assertIn("position", names)
        # From ``TimeStampedModel``. If either base were silently dropped by the
        # MRO merge these two would be the casualties, and nothing else in the
        # suite would notice — ``created``/``modified`` are read by moderation
        # and the console, not by any tree operation.
        self.assertIn("created", names)
        self.assertIn("modified", names)
        # A sanity anchor: a field declared on the model itself, so a broken
        # ``_meta.get_fields()`` cannot make the four assertions above vacuous.
        self.assertIn("url", names)
        self.assertIn("occurred_at", names)

    def test_orderable_tree_node_is_a_real_base_of_the_model(self):
        bases = {c.__name__ for c in SocialMediaLink.__mro__}
        self.assertIn("TimeStampedModel", bases)
        self.assertIn("OrderableTreeNode", bases)
        self.assertIn("TreeNode", bases)
        # ``TimeStampedModel`` precedes ``OrderableTreeNode`` in the MRO, so
        # ``save()`` reaches ``OrderableTreeNode.save``'s position auto-assign
        # on its way to ``Model.save`` rather than shadowing it.
        mro = [c.__name__ for c in SocialMediaLink.__mro__]
        self.assertLess(mro.index("TimeStampedModel"), mro.index("OrderableTreeNode"))

    def test_meta_ordering_is_position(self):
        # The sibling sequence is the model's default order. This is the change
        # with the widest blast radius: every ``SocialMediaLink`` queryset
        # without an explicit ``order_by`` now sorts by ``position``, where
        # before 0031 the model had no ``Meta.ordering`` and such querysets
        # came back in whatever order the planner produced. See
        # ``test_social_link_tree_migration.py`` and the M1 report for the
        # per-call-site audit.
        self.assertEqual(list(SocialMediaLink._meta.ordering), ["position"])

    def test_parent_is_nullable_with_set_null_and_the_children_related_name(self):
        field = SocialMediaLink._meta.get_field("parent")
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
        self.assertIs(field.remote_field.on_delete, models.SET_NULL)
        self.assertEqual(field.remote_field.related_name, "children")
        # The library locates the tree by the field NAME and its CTE hardcodes
        # ``parent_id``; renaming either side would break every tree query with
        # an opaque SQL error, so the names are pinned too.
        self.assertEqual(field.name, "parent")
        self.assertEqual(field.attname, "parent_id")

    def test_position_is_a_positive_integer_with_an_index(self):
        field = SocialMediaLink._meta.get_field("position")
        self.assertIsInstance(field, models.PositiveIntegerField)
        self.assertTrue(field.db_index)
        self.assertEqual(field.default, 0)

    def test_a_new_root_saves_with_no_parent(self):
        link = _link(self.user)
        self.assertIsNone(link.parent_id)
        self.assertIsNone(link.parent)
        self.assertEqual(list(link.children.all()), [])

    def test_a_lone_ungrouped_link_is_indistinguishable_from_a_conversation_root(
        self,
    ):
        """The SEMANTIC INVERSION of the flat ``thread`` design, pinned.

        The 0030 model had a separate field for grouping, so "this link has no
        ``thread``" and "this link is the top of a conversation" were two
        different questions, and the guard that lived here used to assert the
        first. Migration 0031 deleted that field: ``parent_id IS NULL`` now
        answers both at once. A link nobody has nested is a ROOT — a
        conversation of one — and the database cannot tell it apart from the root
        of a real tree, by construction.

        That collapse is the reason ``SocialMediaLinkScalar.isThreadRoot`` is a
        root marker and NOT a "has sublinks" marker: it is ``parent_id is None``,
        so it is ``true`` for every unthreaded link on the feed. The only correct
        "draw the N-links chip" test is ``sublinkCount > 0``. Pinned here so a
        future "let us treat an ungrouped link as thread-less again" reads as the
        schema change it would be, rather than as a harmless convenience.

        The negative half matters as much as the positive: a link WITH a parent
        must not report root, or the collapse would be lying in the other
        direction and a sublink would look like a page unit.
        """
        lone = _link(self.user)
        root = _link(self.user)
        sublink = _link(self.user, parent=root)

        # No tree, no grouping call, no thread at all — and structurally the same
        # shape as the root of a three-link conversation.
        self.assertIsNone(lone.parent_id)
        self.assertEqual(list(lone.children.all()), [])
        self.assertIsNone(root.parent_id)
        self.assertEqual(
            [link.pk for link in root.children.all()],
            [sublink.pk],
        )

        # The only thing that separates a lone link from a real conversation root
        # is whether anything points at it — which is exactly ``sublinkCount``
        # and NOT ``parentId is None``. A real root is equally "no parent", so
        # the root-marker test cannot distinguish the two.
        self.assertIsNone(root.parent_id)
        self.assertNotEqual(lone.parent_id, sublink.parent_id)
        self.assertIsNotNone(sublink.parent_id)
        # …and a sublink is not a root, so the collapse does not lie the other
        # way and turn a sublink into a page unit.
        self.assertNotEqual(sublink.parent_id, None)

    def test_full_clean_still_reaches_the_library_loop_check(self):
        # The ``save()`` guard is ADDITIVE: a caller that opts into
        # ``full_clean()`` still gets ``TreeNode.clean()`` through the MRO, so
        # the two guards cannot disagree about what a cycle is.
        root = _link(self.user)
        child = _link(self.user, parent=root)
        child.parent = child
        with self.assertRaises(ValidationError):
            child.full_clean()


class TreeCycleGuardTests(TestCase):
    """The guard the library does NOT provide: ``save()`` must reject a cycle."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-cycle")
        self.a = _link(self.user)
        self.b = _link(self.user, parent=self.a)
        self.c = _link(self.user, parent=self.b)

    def test_a_plain_save_that_would_close_a_cycle_is_rejected(self):
        # THE test this file exists for. ``tree_queries`` puts its loop
        # protection in ``clean()``, which only ``full_clean()`` runs, so
        # without the ``save()`` override this write succeeds and produces a row
        # that is unreachable from the recursive CTE (which anchors on
        # ``parent_id IS NULL``) and that makes ``ancestors()`` raise
        # ``DoesNotExist`` — a 500, not an empty list.
        self.a.parent = self.c
        with self.assertRaises(ValidationError) as ctx:
            self.a.save()

        message = str(ctx.exception)
        self.assertIn(str(self.a.pk), message)
        self.assertIn("descendant", message)

        # The row must be UNCHANGED: the guard runs before ``super().save()``,
        # so the rejected write left no trace in the database.
        self.a.refresh_from_db()
        self.assertIsNone(self.a.parent_id)
        # And the tree is still intact, still reachable depth-first from the
        # root. Without the guard this list is empty and ``c.ancestors()``
        # raises — the row is present in the table and invisible to the CTE.
        self.assertEqual(list(self.a.descendants()), [self.b, self.c])
        self.assertEqual(list(self.c.ancestors()), [self.a, self.b])

    def test_a_rejected_cycle_leaves_the_whole_subtree_reachable(self):
        self.a.parent = self.c
        with self.assertRaises(ValidationError):
            self.a.save()

        # ``ancestors()`` is root-first, and every node in the chain is still
        # reachable through the CTE. A cycle anywhere in the chain would make
        # the whole chain unreachable, and ``ancestors()`` on a node inside one
        # raises ``DoesNotExist`` rather than returning short.
        self.assertEqual(list(self.a.descendants()), [self.b, self.c])
        self.assertEqual([link.pk for link in self.a.ancestors()], [])
        self.assertEqual(
            [link.pk for link in self.c.ancestors()],
            [self.a.pk, self.b.pk],
        )

    def test_a_node_cannot_be_its_own_parent(self):
        # The degenerate cycle. The library's ancestor walk cannot see it (a node
        # is not its own ancestor), yet it is just as fatal to the CTE, so it is
        # rejected up front rather than by the walk.
        self.a.parent = self.a
        with self.assertRaises(ValidationError):
            self.a.save()

        self.a.refresh_from_db()
        self.assertIsNone(self.a.parent_id)

    def test_a_cycle_is_rejected_at_depth_not_just_against_the_direct_parent(self):
        # Guards against an implementation that only compares the new parent
        # against the node's own parent (the degenerate one-hop case). The
        # chain is a → b → c → d; making ``b`` a child of ``d`` closes a loop
        # three hops down, and a one-hop comparison would happily write it.
        # The database would then hold d → c → b → d, unreachable from any root.
        d = _link(self.user, parent=self.c)
        self.b.parent = d
        with self.assertRaises(ValidationError):
            self.b.save()

        self.b.refresh_from_db()
        self.assertEqual(self.b.parent_id, self.a.pk)
        # The whole four-deep chain is still one well-formed tree.
        self.assertEqual(
            [link.pk for link in self.a.descendants()],
            [self.b.pk, self.c.pk, d.pk],
        )

    def test_a_valid_re_parent_onto_a_sibling_subtree_is_allowed(self):
        # The negative control for the test above: re-parenting onto a node that
        # is NOT in the moved node's own subtree is a legitimate move (G1's
        # "group under a specific link"), so the guard must not over-reject.
        # ``a`` → (b → c) and ``a`` → d; move ``c`` under ``d``.
        d = _link(self.user, parent=self.a)
        self.c.parent = d
        self.c.save()

        self.c.refresh_from_db()
        self.assertEqual(self.c.parent_id, d.pk)
        self.assertEqual(
            [link.pk for link in self.a.descendants()],
            [self.b.pk, d.pk, self.c.pk],
        )

    def test_a_root_save_is_unaffected_and_costs_no_ancestor_walk(self):
        # The guard short-circuits on ``not self.parent_id``, so the common
        # case (every automated ingestion, every hand submission — all roots)
        # must not pay for the ancestor walk, which is a recursive CTE. A
        # regression here would add a CTE to every link write in the system.
        # The only extra query on a create is the library's own
        # ``MAX(position)`` append aggregate, which is not ours and is counted
        # separately by ``CREATE_QUERIES``.
        with CaptureQueriesContext(connection) as ctx:
            root = SocialMediaLink.objects.create(
                url="https://example.com/root", user=self.user
            )
        self.assertEqual(len(ctx.captured_queries), CREATE_QUERIES)
        self.assertFalse(
            any("WITH RECURSIVE" in q["sql"] for q in ctx.captured_queries)
        )
        self.assertIsNone(root.parent_id)

        # Editing an existing root is a single UPDATE with no aggregate at all:
        # ``position`` is already non-zero, so the library's append path does
        # not fire either.
        root.title = "edited"
        with CaptureQueriesContext(connection) as ctx:
            root.save()
        self.assertEqual(len(ctx.captured_queries), UPDATE_QUERIES)
        root.refresh_from_db()
        self.assertEqual(root.title, "edited")

    def test_an_update_fields_save_that_cannot_touch_parent_skips_the_check(self):
        # ``telegram_provider.handlers`` moderates with
        # ``link.asave(update_fields=["status"])``. That write cannot move a node
        # in the tree, so it must not run the (recursive-CTE) ancestor walk — the
        # guard scopes itself to the fields a partial write can carry, and
        # ``status`` is not one of them. Getting that scope wrong in the
        # permissive direction is exactly what the attname test below pins.
        parent = _link(self.user)
        child = _link(self.user, parent=parent)
        child.status = SocialMediaLinkStatus.LIVE
        with CaptureQueriesContext(connection) as ctx:
            child.save(update_fields=["status"])
        self.assertEqual(len(ctx.captured_queries), UPDATE_QUERIES)
        self.assertFalse(
            any("WITH RECURSIVE" in q["sql"] for q in ctx.captured_queries)
        )
        child.refresh_from_db()
        self.assertEqual(child.status, SocialMediaLinkStatus.LIVE)
        self.assertEqual(child.parent_id, parent.pk)

    def test_an_update_fields_save_spelled_with_the_attname_is_still_guarded(self):
        """A field has TWO spellings in ``update_fields``, and the guard needs both.

        Django does not key ``update_fields`` on the field NAME alone.
        ``Options._non_pk_concrete_field_names`` appends ``field.attname`` to the
        same allowlist set as ``field.name`` whenever the two differ, and
        ``Model._save_table`` keeps a field when
        ``f.name in update_fields or f.attname in update_fields``. So
        ``save(update_fields=["parent_id"])`` is a first-class spelling of the
        same re-parent write — and the UPDATE it emits carries the ``parent``
        column. A guard that tested for ``"parent"`` alone therefore returns
        early on exactly the write it exists to inspect, and the cycle lands
        silently. The first half of this test is the reason that bug cannot
        recur; the second half is the reason the optimisation cannot be undone
        by over-correcting into "always check".
        """
        # --- The positive control: a field that genuinely cannot move a node. ---
        # Exactly one statement — the UPDATE. The guard's ancestor walk is a
        # recursive CTE and would show up as extra captured queries, so a bare
        # count is enough to prove the optimisation survived the fix.
        with self.assertNumQueries(UPDATE_QUERIES):
            self.b.status = SocialMediaLinkStatus.LIVE
            self.b.save(update_fields=["status"])
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, SocialMediaLinkStatus.LIVE)
        self.assertEqual(self.b.parent_id, self.a.pk)

        # --- The hole: the attname spelling of a re-parent that closes a cycle. ---
        # The chain is a → b → c, so making ``a`` a child of its own great-
        # grandchild closes a loop. The capture proves the ordering, not just the
        # exception: the CTE appears (the guard really did walk) and the UPDATE
        # does not (nothing was written).
        with CaptureQueriesContext(connection) as ctx:
            with self.assertRaises(ValidationError) as caught:
                self.a.parent_id = self.c.pk
                self.a.save(update_fields=["parent_id"])

        message = str(caught.exception)
        self.assertIn(str(self.a.pk), message)
        self.assertIn("descendant", message)
        self.assertTrue(
            any("WITH RECURSIVE" in q["sql"] for q in ctx.captured_queries),
            "the guard returned before running the ancestor walk",
        )
        self.assertFalse(
            any(q["sql"].startswith("UPDATE") for q in ctx.captured_queries),
            "the rejected write reached the database",
        )

        # The row is UNCHANGED, and the tree is still one well-formed tree
        # reachable from its root. Had the write landed, ``a`` would be inside
        # the cycle: invisible to the CTE, and ``ancestors()`` on it would raise
        # ``DoesNotExist`` instead of returning an empty list.
        self.assertIsNone(SocialMediaLink.objects.get(pk=self.a.pk).parent_id)
        self.assertEqual(list(self.a.descendants()), [self.b, self.c])
        self.assertEqual(
            [link.pk for link in self.c.ancestors()],
            [self.a.pk, self.b.pk],
        )

    def test_an_update_fields_save_that_does_name_parent_still_checks(self):
        # The other half of the same decision: a re-parent saved as
        # ``update_fields=["parent"]`` MUST be guarded, or the optimisation
        # above would be a hole straight into the cycle the guard exists for.
        root = _link(self.user)
        other = _link(self.user)
        child = _link(self.user, parent=other)

        # A legal re-parent through the narrow write path: ``root`` becomes a
        # grandchild of ``other``. No cycle (root is not in its own subtree).
        root.parent = child
        root.save(update_fields=["parent"])
        self.assertEqual(SocialMediaLink.objects.get(pk=root.pk).parent_id, child.pk)

        # Now the cycle: the chain is other → child → root, and re-parenting
        # ``other`` under its own great-grandchild closes it. The guard has to
        # fire even though the write names only ``parent``, or the
        # ``update_fields`` optimisation is a hole straight into the bug it was
        # added to avoid.
        other.parent = root
        with self.assertRaises(ValidationError):
            other.save(update_fields=["parent"])
        self.assertIsNone(SocialMediaLink.objects.get(pk=other.pk).parent_id)

    def test_a_new_unsaved_child_cannot_already_be_in_a_cycle(self):
        # No pk yet means no subtree to fall into, so the guard must not run the
        # ancestor walk — only the library's own ``MAX(position)`` aggregate and
        # the INSERT itself.
        fresh = SocialMediaLink(url="https://example.com/new", user=self.user)
        fresh.parent = self.c
        with CaptureQueriesContext(connection) as ctx:
            fresh.save()
        self.assertEqual(len(ctx.captured_queries), CREATE_QUERIES)
        self.assertFalse(
            any("WITH RECURSIVE" in q["sql"] for q in ctx.captured_queries)
        )
        self.assertEqual(fresh.parent_id, self.c.pk)

    def test_bulk_writes_bypass_the_guard_and_that_is_known(self):
        # Documented limitation, pinned so it stays a decision rather than a
        # surprise: ``bulk_update`` / ``bulk_create`` never call ``save()``, so
        # they can write a cycle. That is why the grouping service (G1) rejects
        # cycles itself and assigns ``position`` explicitly. If a cycle ever
        # does land in the table, ``ancestors()`` raises ``DoesNotExist`` —
        # asserted here so the failure mode is on the record.
        self.a.parent = self.c
        SocialMediaLink.objects.bulk_update([self.a], ["parent"])
        with self.assertRaises(SocialMediaLink.DoesNotExist):
            list(self.a.ancestors())


class TreeDeletePromotionTests(TestCase):
    """``SET_NULL``: deleting a link promotes its subtree instead of cascading."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-delete")
        self.root = _link(self.user)
        self.child = _link(self.user, parent=self.root)
        self.grandchild = _link(self.user, parent=self.child)
        self.grandchild_child = _link(self.user, parent=self.grandchild)

    def test_deleting_a_root_promotes_its_child_to_a_root(self):
        self.root.delete()

        child = SocialMediaLink.objects.get(pk=self.child.pk)
        self.assertIsNone(child.parent_id)
        # The grandchild keeps its parent: promotion is a single level, applied
        # by the FK's own ``SET_NULL``, and the rest of the subtree is untouched
        # because it never pointed at the deleted row.
        grandchild = SocialMediaLink.objects.get(pk=self.grandchild.pk)
        self.assertEqual(grandchild.parent_id, self.child.pk)

    def test_the_surviving_subtree_is_still_reachable_from_its_new_root(self):
        self.root.delete()

        promoted = SocialMediaLink.objects.get(pk=self.child.pk)
        self.assertEqual(
            [link.pk for link in promoted.descendants()],
            [self.grandchild.pk, self.grandchild_child.pk],
        )
        # …and the promoted row is a genuine root as far as the CTE is
        # concerned, which is the whole point: the tree is queryable again with
        # no repair step.
        self.assertEqual(
            [link.pk for link in SocialMediaLink.objects.filter(parent__isnull=True)],
            [self.child.pk],
        )

    def test_deleting_a_middle_node_promotes_only_its_own_children(self):
        self.child.delete()

        grandchild = SocialMediaLink.objects.get(pk=self.grandchild.pk)
        self.assertIsNone(grandchild.parent_id)
        self.assertEqual(
            [link.pk for link in grandchild.descendants()],
            [self.grandchild_child.pk],
        )
        self.assertEqual(list(self.root.descendants()), [])


class TreePositionTests(TestCase):
    """``position`` is a gap-spaced sibling sequence, not an index."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-position")

    def test_position_appends_at_max_siblings_plus_the_model_step(self):
        # The stride is read from the model's own save() rather than hardcoded,
        # so a future change to the library's convention (or to a subclass of
        # this model) does not leave this test asserting a stale number. The
        # current value is 10.
        first = _link(self.user)
        second = _link(self.user)
        third = _link(self.user)

        step = second.position - first.position
        self.assertEqual(step, 10)
        self.assertEqual(
            [first.position, second.position, third.position], [10, 20, 30]
        )
        self.assertEqual(third.position - second.position, step)

    def test_position_is_assigned_per_parent_not_globally(self):
        # Two different parents number their children from the same base, so
        # ``max(siblings)`` is scoped to the sibling set. A global sequence
        # would make the second root's first child 40, and the "10, 20, 30"
        # contract G1's reorder mutation relies on would be a root-only
        # accident.
        root_a = _link(self.user)
        root_b = _link(self.user)
        a1 = _link(self.user, parent=root_a)
        b1 = _link(self.user, parent=root_b)
        a2 = _link(self.user, parent=root_a)
        b2 = _link(self.user, parent=root_b)

        self.assertEqual([a1.position, a2.position], [10, 20])
        self.assertEqual([b1.position, b2.position], [10, 20])

    def test_an_explicit_position_is_never_overwritten(self):
        # Re-parenting and reordering (G1) assign positions explicitly. The
        # auto-assign only fires when the value is falsy, so a deliberately
        # chosen position must survive a save.
        root = _link(self.user)
        other = _link(self.user)
        _link(self.user, parent=root)
        explicit = _link(self.user, parent=root, position=5)
        self.assertEqual(explicit.position, 5)
        explicit.save()
        explicit.refresh_from_db()
        self.assertEqual(explicit.position, 5)

        # A node moved under a different parent keeps the position it was given
        # (the library does NOT recompute on re-parent) — which is why the
        # service assigns one rather than trusting the auto-assign.
        explicit.parent = other
        explicit.save()
        explicit.refresh_from_db()
        self.assertEqual(explicit.position, 5)
        self.assertEqual(explicit.parent_id, other.pk)

    def test_default_meta_ordering_returns_siblings_in_position_order(self):
        root = _link(self.user)
        third = _link(self.user, parent=root)
        first = _link(self.user, parent=root, position=1)
        second = _link(self.user, parent=root, position=2)

        # No explicit ``order_by``: this is the implicit ordering the audit is
        # about, exercised at the level where it is actually meaningful.
        self.assertEqual(
            [link.pk for link in SocialMediaLink.objects.filter(parent=root)],
            [first.pk, second.pk, third.pk],
        )

    def test_default_meta_ordering_works_at_a_non_root_level_too(self):
        # Ordering by ``position`` is GLOBAL, not per-level: without a
        # ``parent_id`` term the ordering is only a sibling order when the
        # queryset is already narrowed to one parent. A tree query that mixes
        # levels (which is what ``descendants()`` returns) therefore does NOT
        # come out grouped by depth from ``Meta.ordering`` alone — it is
        # depth-first by the CTE, and the default ``ORDER BY`` is applied on top.
        # Pinned so nobody later "fixes" the default ordering to
        # ``("parent", "position")`` and silently changes feed ordering.
        root = _link(self.user)
        child_a = _link(self.user, parent=root)
        child_b = _link(self.user, parent=root)
        grandchild = _link(self.user, parent=child_a)

        # ``descendants()`` is depth-first: both children, then the grandchild
        # nested under the first.
        self.assertEqual(
            [link.pk for link in root.descendants()],
            [child_a.pk, grandchild.pk, child_b.pk],
        )
        # The nesting is invisible to a flat ``position``-ordered queryset: the
        # sole child of ``child_a`` is ALSO position 10, colliding with
        # ``child_a`` itself, so a flat list cannot be read as a tree. This is
        # the concrete reason ``Meta.ordering`` is ``["position"]`` alone and
        # every consumer that mixes levels has to order explicitly.
        flat = list(SocialMediaLink.objects.filter(parent__isnull=False))
        self.assertEqual(len(flat), 3)
        self.assertEqual(sorted(link.position for link in flat), [10, 10, 20])
        self.assertEqual(
            {(link.parent_id, link.position) for link in flat},
            {(root.pk, 10), (root.pk, 20), (child_a.pk, 10)},
        )
        # Explicit narrowing to one parent is what makes a sibling order total.
        self.assertEqual([link.pk for link in child_a.children.all()], [grandchild.pk])
        self.assertEqual(
            [link.pk for link in SocialMediaLink.objects.filter(parent=root)],
            [child_a.pk, child_b.pk],
        )
        self.assertEqual(
            [link.pk for link in SocialMediaLink.objects.filter(parent=child_a)],
            [grandchild.pk],
        )
