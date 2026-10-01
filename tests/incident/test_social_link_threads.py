"""Sublink trees for ``SocialMediaLink``: nesting, explicit ordering, and the two
invariants the service enforces (no cycles, depth <= ``MAX_THREAD_DEPTH``).

A thread is a ROOT row plus an ordered nested tree hanging off it; a root is
simply a link with ``parent_id IS NULL``. The service
(``incident.services.social_link_threads``) owns the shape, so the readers may
assume it: a subtree is reachable from its root, a sibling set is numbered
``10, 20, 30, …`` with no gaps, and nothing in the table sits in a cycle.

Three things here are tests of a *rejection* rather than of a result, and they
are the reason this module is long: a cycle is not "invisible", it is a 500
(``ancestors()`` on a node inside one raises ``DoesNotExist``), a depth overrun
makes the recursive-CTE reads grow without bound, and a partially-applied group
leaves a hierarchy no reader can interpret. Each of those has a test that asserts
the WHOLE tree is byte-identical afterwards — asserting only the raised error
would pass for an implementation that wrote half the change before validating.

Determinism gets the same treatment, because the library will not give it:
``OrderableTreeNode`` auto-assigns ``max_sibling + 10`` on INSERT and does not
touch ``position`` at all on a re-parent, so "run the same call twice" is the
only way to catch a write that lands rows in an arbitrary order.

Runs under plain ``django.test.TestCase`` + ``asgiref.sync.async_to_sync`` (the
services are coroutines) and deliberately does NOT import pytest: pytest is not
installed in the app image, so a pytest-based file here is uncollectable dead
code.
"""

import copy
import datetime as dt
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from dotmap import DotMap

from common.models import User
from incident.models import SocialMediaLink
from incident.services import social_link_threads
from incident.services.errors import IncidentServiceError
from incident.services.feed_links import submit_feed_link
from rosak.context import ContextLoaders
from rosak.schema import schema

# Deliberately different from "now" so a root picked on submission time cannot
# pass by accident.
EARLIEST = dt.datetime(2026, 9, 28, 9, 0, 0)
BEFORE = dt.datetime(2026, 9, 28, 8, 0, 0)
MIDDLE = dt.datetime(2026, 9, 28, 10, 0, 0)
LATEST = dt.datetime(2026, 9, 28, 11, 0, 0)

# The services are coroutines; these tests are sync so ``setUp`` and the
# assertions can touch the ORM directly.
_group = async_to_sync(social_link_threads.group_social_media_links)
_ungroup = async_to_sync(social_link_threads.ungroup_social_media_links)
_reorder = async_to_sync(social_link_threads.reorder_social_media_links)
_submit_feed_link = async_to_sync(submit_feed_link)


def execute_graphql(query: str, variables=None, user=None):
    """Same harness the sibling incident tests use — a DotMap context, no auth."""
    context = DotMap(
        {
            "loaders": copy.deepcopy(ContextLoaders),
            "request": None,
            "response": None,
            "user": user,
        }
    )
    return async_to_sync(schema.execute)(
        query, variable_values=variables, context_value=context
    )


def _link(user: User, url: str, **overrides) -> SocialMediaLink:
    fields = {"url": url, "user": user}
    fields.update(overrides)
    return SocialMediaLink.objects.create(**fields)


def _parent_of(link_id: int) -> int | None:
    return SocialMediaLink.objects.values_list("parent_id", flat=True).get(pk=link_id)


def _children(parent_id: int | None) -> list[SocialMediaLink]:
    """The children of ``parent_id`` in their stored order. ``order_by`` is
    explicit because ``Meta.ordering`` is a bare ``["position"]``, NOT grouped by
    parent — relying on the default would be relying on a coincidence."""
    return list(
        SocialMediaLink.objects.filter(parent_id=parent_id).order_by("position", "pk")
    )


def _child_ids(parent_id: int | None) -> list[int]:
    return [row.pk for row in _children(parent_id)]


def _positions(parent_id: int | None) -> list[int]:
    return [row.position for row in _children(parent_id)]


def _tree() -> list[tuple[int, int | None, int]]:
    """Every row's ``(pk, parent_id, position)`` — the whole tree, one read.

    This is the snapshot the "nothing was written" assertions compare. Asserting
    on the two links a call named is not enough: the same call can renumber a
    sibling the caller never mentioned, and that is still a write.
    """
    return sorted(SocialMediaLink.objects.values_list("pk", "parent_id", "position"))


def _assert_well_formed(test: TestCase) -> None:
    """The two invariants, asserted over EVERY row: no self-parent, no cycle, and
    nothing deeper than ``MAX_THREAD_DEPTH``. Walks UP from each row, so it holds
    for a tree the service built and for one that was hand-edited underneath it.
    """
    parents = {pk: parent for pk, parent, _ in _tree()}
    for pk in parents:
        seen = {pk}
        node = parents[pk]
        depth = 1
        while node is not None:
            test.assertIn(node, parents, f"link {pk} points at missing parent {node}")
            test.assertNotIn(node, seen, f"link {pk} sits in a cycle via {node}")
            seen.add(node)
            node = parents[node]
            depth += 1
        test.assertLessEqual(
            depth - 1,
            social_link_threads.MAX_THREAD_DEPTH,
            f"link {pk} is {depth - 1} levels deep, past MAX_THREAD_DEPTH",
        )


def _assert_numbered(test: TestCase, parent_id: int | None) -> None:
    """The sibling set of ``parent_id`` is exactly ``10, 20, 30, …``.

    A gap or a duplicate means the set is not a sequence: ``ORDER BY position``
    stops being total the moment two rows share a number, and every reader that
    renders the set then depends on the planner.
    """
    rows = _children(parent_id)
    test.assertEqual(
        [row.position for row in rows],
        [(index + 1) * 10 for index in range(len(rows))],
        msg=(
            f"children of {parent_id} are not numbered 10, 20, 30, … in order: "
            f"{[(row.pk, row.position) for row in rows]}"
        ),
    )


class NewThreadTests(TestCase):
    """``parentId`` omitted: elect a root, nest the rest under it."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-root")

    def test_the_earliest_event_becomes_the_root_and_the_rest_nest_under_it(self):
        # Selected out of order, and ``created`` runs opposite to ``occurred_at``
        # on purpose: the latest event is the OLDEST submission here, so a root
        # picked on ``created`` would pick the wrong row.
        late = _link(self.user, "https://x.com/lrt/status/101", occurred_at=LATEST)
        early = _link(self.user, "https://x.com/lrt/status/102", occurred_at=EARLIEST)
        middle = _link(self.user, "https://x.com/lrt/status/103", occurred_at=MIDDLE)

        root = _group(self.user, is_admin=True, link_ids=[late.id, early.id, middle.id])

        self.assertEqual(root.id, early.id)
        self.assertIsNone(_parent_of(early.id))
        self.assertEqual(_child_ids(early.id), [middle.id, late.id])
        # The root is never its own child, and the children are in
        # ``occurred_at ASC`` order — the same key that elected the root.
        self.assertEqual(_positions(early.id), [10, 20])
        _assert_numbered(self, early.id)
        # NOT asserted on the root set: the elected root keeps the ``position``
        # the library's insert-time ``max_sibling + 10`` gave it, and grouping
        # says nothing about how roots are ordered. Only
        # ``reorderSocialMediaLinks(parentId: null, …)`` renumbers those.
        _assert_well_formed(self)

    def test_links_sharing_an_event_time_are_broken_by_id(self):
        # Two links reported for the same instant. Without the ``id`` tie-break
        # the root would depend on query/insertion order, so the same selection
        # could produce two different threads.
        first = _link(self.user, "https://x.com/lrt/status/111", occurred_at=EARLIEST)
        second = _link(self.user, "https://x.com/lrt/status/112", occurred_at=EARLIEST)
        lower, higher = sorted((first.id, second.id))

        root = _group(self.user, is_admin=True, link_ids=[higher, lower])

        self.assertEqual(root.id, lower)
        self.assertEqual(_child_ids(lower), [higher])
        _assert_well_formed(self)

    def test_promoting_a_sublink_to_root_detaches_it_from_the_old_tree(self):
        """A sublink that becomes a root must stop pointing at its old parent, or
        the new thread would hang off a row that is itself inside another one.

        ``BEFORE`` is EARLIER than ``EARLIEST`` — the constant names a point
        before the baseline, not "the baseline minus something" — so ``outer``
        has to carry the earlier event for it to win the root election here.
        """
        outer = _link(self.user, "https://x.com/lrt/status/121", occurred_at=BEFORE)
        inner = _link(self.user, "https://x.com/lrt/status/122", occurred_at=EARLIEST)
        _group(self.user, is_admin=True, link_ids=[outer.id, inner.id])
        self.assertEqual(_parent_of(inner.id), outer.id)

        partner = _link(self.user, "https://x.com/lrt/status/123", occurred_at=MIDDLE)
        root = _group(self.user, is_admin=True, link_ids=[inner.id, partner.id])

        self.assertEqual(root.id, inner.id)
        self.assertIsNone(_parent_of(inner.id))
        self.assertEqual(_child_ids(inner.id), [partner.id])
        # ``outer`` is untouched: it was not selected, so it is still the root of
        # its own (now empty) thread rather than being dragged along.
        self.assertIsNone(_parent_of(outer.id))
        self.assertEqual(_child_ids(outer.id), [])
        _assert_well_formed(self)


class NestingTests(TestCase):
    """``parentId`` naming a SUBLINK nests instead of collapsing to the root."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-nesting")
        self.a = _link(self.user, "https://x.com/lrt/status/131", occurred_at=EARLIEST)
        self.b = _link(self.user, "https://x.com/lrt/status/132", occurred_at=MIDDLE)
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])

    def test_appending_under_a_sublink_does_not_hoist_the_child_to_the_root(self):
        """The behaviour the old service actively undid.

        It resolved a member target up to its root and put everything on the
        root, because depth had to stay 1. Nesting makes the named link the
        parent, so the third link is a GRANDchild — which is the whole point of
        the change and the reason the argument is not called ``threadId``.
        """
        c = _link(self.user, "https://x.com/lrt/status/133", occurred_at=LATEST)

        root = _group(self.user, is_admin=True, link_ids=[c.id], parent_id=self.b.id)

        self.assertEqual(_parent_of(c.id), self.b.id)
        self.assertEqual(_child_ids(self.b.id), [c.id])
        # ``a`` still has exactly one child: nothing was hoisted onto it.
        self.assertEqual(_child_ids(self.a.id), [self.b.id])
        # The return value is the THREAD root, resolved for the caller's benefit
        # only — the write itself nested one level deeper.
        self.assertEqual(root.id, self.a.id)
        _assert_well_formed(self)

    def test_a_sublink_target_may_be_named_repeatedly_to_go_deeper(self):
        b2 = _link(self.user, "https://x.com/lrt/status/134", occurred_at=LATEST)
        b3 = _link(self.user, "https://x.com/lrt/status/135", occurred_at=LATEST)
        _group(self.user, is_admin=True, link_ids=[b2.id], parent_id=self.b.id)
        _group(self.user, is_admin=True, link_ids=[b3.id], parent_id=b2.id)

        self.assertEqual(_parent_of(b3.id), b2.id)
        self.assertEqual(_parent_of(b2.id), self.b.id)
        self.assertEqual(_parent_of(self.b.id), self.a.id)
        _assert_well_formed(self)

    def test_grouping_a_single_link_is_a_no_op_success(self):
        root = _group(self.user, is_admin=True, link_ids=[self.b.id])

        self.assertEqual(root.id, self.b.id)
        self.assertIsNone(_parent_of(self.b.id))


class OrderingTests(TestCase):
    """``position`` is written by the service, never inherited from the library."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-ordering")
        self.a = _link(self.user, "https://x.com/lrt/status/141", occurred_at=EARLIEST)
        self.b = _link(self.user, "https://x.com/lrt/status/142", occurred_at=MIDDLE)
        self.c = _link(self.user, "https://x.com/lrt/status/143", occurred_at=LATEST)

    def test_positions_are_reindexed_to_ten_twenty_thirty(self):
        # ``a`` is the elected root, so it is ``b`` and ``c`` that are numbered.
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id, self.c.id])

        self.assertEqual(_positions(self.a.id), [10, 20])
        self.assertEqual(_child_ids(self.a.id), [self.b.id, self.c.id])
        _assert_numbered(self, self.a.id)

    def test_a_three_link_sibling_set_is_numbered_to_thirty(self):
        third = _link(
            self.user,
            "https://x.com/lrt/status/147",
            occurred_at=LATEST + dt.timedelta(hours=1),
        )
        _group(
            self.user,
            is_admin=True,
            link_ids=[self.a.id, self.b.id, self.c.id, third.id],
        )

        self.assertEqual(_positions(self.a.id), [10, 20, 30])
        self.assertEqual(_child_ids(self.a.id), [self.b.id, self.c.id, third.id])
        _assert_numbered(self, self.a.id)

    def test_the_same_call_twice_writes_nothing_the_second_time(self):
        """The idempotent no-op, asserted as "no UPDATE is even issued".

        ``_changed_rows`` diffs ``(parent_id, position)`` against the values read
        inside the transaction, so a repeated grouping is a genuine no-op. Saying
        so at the SQL level is stronger than comparing the tree afterwards: an
        implementation that re-wrote the same values would pass the weaker
        assertion while still touching every row and moving ``modified``-adjacent
        bookkeeping around.
        """
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id, self.c.id])
        after_first = _tree()

        with CaptureQueriesContext(connection) as ctx:
            root = _group(
                self.user, is_admin=True, link_ids=[self.c.id, self.a.id, self.b.id]
            )

        updates = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].lstrip().upper().startswith("UPDATE")
        ]
        self.assertEqual(updates, [], msg="a repeated grouping issued an UPDATE")
        self.assertEqual(_tree(), after_first)
        self.assertEqual(root.id, self.a.id)

    def test_the_input_order_does_not_change_the_result(self):
        _group(self.user, is_admin=True, link_ids=[self.b.id, self.a.id, self.c.id])
        first = _tree()

        # A different selection order, same three links: the root election and the
        # child order are both functions of ``(occurred_at, id)`` alone.
        _group(self.user, is_admin=True, link_ids=[self.c.id, self.b.id, self.a.id])

        self.assertEqual(_tree(), first)
        self.assertEqual(_child_ids(self.a.id), [self.b.id, self.c.id])

    def test_new_children_lead_and_the_ones_already_there_keep_their_order(self):
        """The documented splice rule, pinned because it is a choice.

        A regroup puts the freshly nested links first (that is the order the
        caller just expressed) and the children that were already there follow
        unchanged. Reversing either half would reshuffle a branch nobody asked to
        touch.
        """
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])
        later = _link(self.user, "https://x.com/lrt/status/144", occurred_at=LATEST)

        _group(self.user, is_admin=True, link_ids=[later.id], parent_id=self.a.id)

        self.assertEqual(_child_ids(self.a.id), [later.id, self.b.id])
        self.assertEqual(_positions(self.a.id), [10, 20])
        _assert_numbered(self, self.a.id)

    def test_the_slot_a_link_vacated_is_closed(self):
        """Re-parenting renumbers the source set too, so no gaps survive.

        Without this, ``10, 30, 40`` is left behind and "every sibling set is
        ``10, 20, 30, …``" stops being an invariant a later reorder can rely on.
        ``other`` carries the earliest event so it wins the root election and
        really does have a three-child set to renumber.
        """
        other = _link(self.user, "https://x.com/lrt/status/145", occurred_at=BEFORE)
        third = _link(self.user, "https://x.com/lrt/status/146", occurred_at=LATEST)
        _group(
            self.user,
            is_admin=True,
            link_ids=[other.id, self.b.id, self.c.id, third.id],
        )
        self.assertEqual(_positions(other.id), [10, 20, 30])
        self.assertEqual(_child_ids(other.id), [self.b.id, self.c.id, third.id])

        _group(self.user, is_admin=True, link_ids=[self.b.id], parent_id=self.a.id)

        self.assertEqual(_positions(other.id), [10, 20])
        self.assertEqual(_child_ids(other.id), [self.c.id, third.id])
        _assert_numbered(self, other.id)

    def test_grouping_does_not_move_modified(self):
        """Regrouping is a presentation change, not a content edit.

        The write is scoped to ``["parent", "position"]``, so model_utils'
        ``modified`` stamp stays put and the console's "recently edited" ordering
        is not reshuffled by a cosmetic action. Asserted on the value and on the
        SQL, because a ``save()``-based implementation would pass the first and
        fail the second.
        """
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])
        before = {row.pk: row.modified for row in SocialMediaLink.objects.all()}
        with CaptureQueriesContext(connection) as ctx:
            _group(self.user, is_admin=True, link_ids=[self.c.id], parent_id=self.a.id)
        after = {row.pk: row.modified for row in SocialMediaLink.objects.all()}

        self.assertEqual(after, before)
        for query in ctx.captured_queries:
            if query["sql"].lstrip().upper().startswith("UPDATE"):
                self.assertNotIn(
                    "modified",
                    query["sql"],
                    msg="the structural write must not touch `modified`",
                )


class CycleRejectionTests(TestCase):
    """A cycle is the one failure the library will NOT catch for you."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-cycle")
        # ``a`` is the root, ``b`` its child, ``c`` ``b``'s child.
        self.a = _link(self.user, "https://x.com/lrt/status/151", occurred_at=EARLIEST)
        self.b = _link(self.user, "https://x.com/lrt/status/152", occurred_at=MIDDLE)
        self.c = _link(self.user, "https://x.com/lrt/status/153", occurred_at=LATEST)
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])
        _group(self.user, is_admin=True, link_ids=[self.c.id], parent_id=self.b.id)

    def test_naming_a_selected_link_as_the_parent_is_rejected(self):
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(self.user, is_admin=True, link_ids=[self.b.id], parent_id=self.b.id)

        self.assertEqual(_tree(), before, msg="a self-parent slipped through")
        _assert_well_formed(self)

    def test_naming_a_descendant_of_a_selected_link_is_rejected(self):
        """``c`` sits below ``b``, so ``b`` must not become ``c``'s child.

        The selection is ordered so the CLASHING link is not the first one: the
        service locks the selection by ``(occurred_at, id)``, so ``spare`` is
        ``movers[0]`` here. An implementation that asked the question the other
        way round — "is the target a descendant of the first selected link?" —
        would look at ``spare``'s (empty) subtree, find nothing and write the
        cycle. The upward walk from the target has no such blind spot, which is
        exactly why it is the one that is written down.
        """
        spare = _link(self.user, "https://x.com/lrt/status/154", occurred_at=BEFORE)
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(
                self.user,
                is_admin=True,
                link_ids=[spare.id, self.b.id],
                parent_id=self.c.id,
            )

        self.assertEqual(_tree(), before)
        _assert_well_formed(self)

    def test_a_cycle_on_the_new_thread_path_is_rejected_too(self):
        """Electing a root is a re-parenting like any other and can close a loop.

        ``b`` is ``c``'s parent and has the LATER event, so grouping ``[b, c]``
        elects ``c`` — a descendant of ``b`` — as the new root and would make
        ``b`` its own child's child. Only reachable if the cycle check runs on the
        ``parentId is null`` path too, which is why it is factored out of the
        branch rather than written into the append arm.

        The fixture is not rigged: give ``c`` the later event and the identical
        call is a legitimate promotion, so what is being tested is the event-time
        collision and not some accidental cycle in the setup.
        """
        a = _link(self.user, "https://x.com/lrt/status/157", occurred_at=BEFORE)
        b = _link(self.user, "https://x.com/lrt/status/158", occurred_at=MIDDLE)
        c = _link(self.user, "https://x.com/lrt/status/159", occurred_at=EARLIEST)
        _group(self.user, is_admin=True, link_ids=[a.id, b.id])
        _group(self.user, is_admin=True, link_ids=[c.id], parent_id=b.id)
        self.assertEqual(_parent_of(c.id), b.id)
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(self.user, is_admin=True, link_ids=[b.id, c.id])

        self.assertEqual(_tree(), before)
        _assert_well_formed(self)

    def test_a_rejected_cycle_writes_nothing_even_for_the_other_links(self):
        """All-or-nothing: the spare link that was perfectly legal to move stays
        exactly where it was, because the call as a whole was refused."""
        spare = _link(self.user, "https://x.com/lrt/status/157", occurred_at=BEFORE)
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(
                self.user,
                is_admin=True,
                link_ids=[spare.id, self.b.id],
                parent_id=self.c.id,
            )

        self.assertIsNone(_parent_of(spare.id))
        self.assertEqual(_tree(), before)


class DepthCapTests(TestCase):
    """``MAX_THREAD_DEPTH`` is a write-side guard on how deep real data goes."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-depth")
        # ``depth_0`` is the root; ``depth_n`` ends up ``n`` levels below it.
        self.chain = [
            _link(
                self.user,
                f"https://x.com/lrt/status/1{60 + index}",
                occurred_at=EARLIEST + dt.timedelta(hours=index),
            )
            for index in range(5)
        ]

    def _build(self, levels: int):
        """Nest ``levels`` links below the root by grouping them one at a time."""
        _group(
            self.user,
            is_admin=True,
            link_ids=[self.chain[0].id, self.chain[1].id],
        )
        for index in range(2, levels + 1):
            _group(
                self.user,
                is_admin=True,
                link_ids=[self.chain[index].id],
                parent_id=self.chain[index - 1].id,
            )

    def test_a_tree_exactly_at_the_cap_is_accepted(self):
        self._build(social_link_threads.MAX_THREAD_DEPTH)

        cap = social_link_threads.MAX_THREAD_DEPTH
        self.assertEqual(
            _parent_of(self.chain[cap].id),
            self.chain[cap - 1].id,
            msg="the deepest accepted link is not a direct child of the level above",
        )
        _assert_well_formed(self)

    def test_one_level_past_the_cap_is_rejected_and_nothing_is_written(self):
        self._build(social_link_threads.MAX_THREAD_DEPTH)
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(
                self.user,
                is_admin=True,
                link_ids=[self.chain[4].id],
                parent_id=self.chain[3].id,
            )

        self.assertIsNone(_parent_of(self.chain[4].id))
        self.assertEqual(_tree(), before)
        _assert_well_formed(self)

    def test_a_subtree_that_travels_with_the_link_is_counted(self):
        """The depth of the result, not the depth of the mover.

        ``chain[0]`` is a root whose own subtree already reaches the cap. Parking
        it under another root would put its deepest descendant one level past the
        cap, so it is refused — a check that only measured the moved link itself
        would have measured ``0`` and let it through, and the read side would then
        have to walk four levels with nothing bounding it.
        """
        self._build(social_link_threads.MAX_THREAD_DEPTH)
        spare = _link(self.user, "https://x.com/lrt/status/169", occurred_at=BEFORE)
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(
                self.user,
                is_admin=True,
                link_ids=[self.chain[0].id],
                parent_id=spare.id,
            )

        self.assertIsNone(_parent_of(self.chain[0].id))
        self.assertEqual(_tree(), before)


class GroupPermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(firebase_id="test-user-tree-owner")
        self.stranger = User.objects.create(firebase_id="test-user-tree-stranger")
        self.admin = User.objects.create(firebase_id="test-user-tree-admin")
        self.mine = _link(
            self.owner, "https://x.com/lrt/status/171", occurred_at=EARLIEST
        )
        self.theirs = _link(
            self.stranger, "https://x.com/lrt/status/172", occurred_at=MIDDLE
        )

    def test_a_submitter_cannot_group_someone_elses_link(self):
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(
                self.owner,
                is_admin=False,
                link_ids=[self.mine.id, self.theirs.id],
            )

        self.assertEqual(_tree(), before)
        _assert_well_formed(self)

    def test_a_submitter_cannot_nest_under_someone_elses_link(self):
        """The TARGET is permission-checked, not just the selection.

        The old service let a submitter graft their own link onto somebody else's
        thread by naming that thread. Nesting made the target a real row in the
        caller's own tree, so the check moved onto it: the named link has to be
        theirs, whoever owns the root above it.
        """
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(
                self.owner,
                is_admin=False,
                link_ids=[self.mine.id],
                parent_id=self.theirs.id,
            )

        self.assertEqual(_tree(), before)
        _assert_well_formed(self)

    def test_a_submitter_can_group_and_nest_their_own_links(self):
        second = _link(self.owner, "https://x.com/lrt/status/173", occurred_at=MIDDLE)
        third = _link(self.owner, "https://x.com/lrt/status/174", occurred_at=LATEST)

        root = _group(self.owner, is_admin=False, link_ids=[self.mine.id, second.id])
        _group(self.owner, is_admin=False, link_ids=[third.id], parent_id=second.id)

        self.assertEqual(root.id, self.mine.id)
        self.assertEqual(_parent_of(second.id), self.mine.id)
        self.assertEqual(_parent_of(third.id), second.id)
        _assert_well_formed(self)

    def test_an_admin_can_group_any_links_including_a_mixed_selection(self):
        root = _group(
            self.admin,
            is_admin=True,
            link_ids=[self.theirs.id, self.mine.id],
        )

        self.assertEqual(root.id, self.mine.id)
        self.assertEqual(_parent_of(self.theirs.id), self.mine.id)
        _assert_well_formed(self)

    def test_ungrouping_someone_elses_link_is_rejected(self):
        _group(self.admin, is_admin=True, link_ids=[self.mine.id, self.theirs.id])
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _ungroup(self.owner, is_admin=False, link_ids=[self.theirs.id])

        self.assertEqual(_tree(), before)

    def test_reordering_someone_elses_sublinks_is_rejected(self):
        _group(self.admin, is_admin=True, link_ids=[self.mine.id, self.theirs.id])
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _reorder(
                self.owner,
                is_admin=False,
                parent_id=self.mine.id,
                link_ids=[self.theirs.id],
            )

        self.assertEqual(_tree(), before)


class GroupInputValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-inputs")
        self.link = _link(
            self.user, "https://x.com/lrt/status/181", occurred_at=EARLIEST
        )

    def test_an_empty_selection_is_rejected(self):
        with self.assertRaises(IncidentServiceError):
            _group(self.user, is_admin=True, link_ids=[])
        with self.assertRaises(IncidentServiceError):
            _reorder(self.user, is_admin=True, parent_id=None, link_ids=[])

    def test_a_repeated_id_is_rejected(self):
        # Not cosmetic: the reindex renumbers EVERY child of the target, so a
        # duplicated id hides how wide the write is. For a reorder it is worse —
        # the list IS the order, and "which of the two mentions goes first" has no
        # answer.
        with self.assertRaises(IncidentServiceError):
            _group(self.user, is_admin=True, link_ids=[self.link.id, self.link.id])
        with self.assertRaises(IncidentServiceError):
            _reorder(
                self.user,
                is_admin=True,
                parent_id=None,
                link_ids=[self.link.id, self.link.id],
            )

    def test_an_unknown_id_is_rejected_and_nothing_is_written(self):
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(self.user, is_admin=True, link_ids=[self.link.id, 987654321])

        self.assertEqual(_tree(), before)

    def test_an_unknown_target_is_rejected_and_nothing_is_written(self):
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _group(
                self.user,
                is_admin=True,
                link_ids=[self.link.id],
                parent_id=987654321,
            )
        with self.assertRaises(IncidentServiceError):
            _reorder(
                self.user, is_admin=True, parent_id=987654321, link_ids=[self.link.id]
            )

        self.assertEqual(_tree(), before)

    def test_ungrouping_repeats_is_tolerated(self):
        # Bulk "clear selection" is idempotent; failing a repeat would punish a
        # harmless client-side double click.
        _ungroup(self.user, is_admin=True, link_ids=[self.link.id, self.link.id])

        self.assertIsNone(_parent_of(self.link.id))


class LockOrderTests(TestCase):
    """Every ``select_for_update`` in the service must carry a deterministic
    ``order_by``.

    An unordered lock takes its rows in whatever order the planner returns, and
    two concurrent calls over overlapping rows that then take them in OPPOSITE
    orders deadlock — Postgres detects the cycle and aborts one (40P01), which
    reaches the client as a 500. The single ``transaction.atomic()`` around each
    write bounds that to availability, not correctness, so nothing here can catch
    a deadlock by asserting on state; the only thing testable is the presence of
    the ordering itself, which is why these assert on SQL.
    """

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-lockorder")
        self.a = _link(self.user, "https://x.com/lrt/status/191", occurred_at=EARLIEST)
        self.b = _link(self.user, "https://x.com/lrt/status/192", occurred_at=MIDDLE)
        self.c = _link(self.user, "https://x.com/lrt/status/193", occurred_at=LATEST)

    def _lock_sql(self, run) -> list[str]:
        """Every ``SELECT ... FOR UPDATE`` the run issued, in order."""
        with CaptureQueriesContext(connection) as ctx:
            run()
        return [q["sql"] for q in ctx.captured_queries if "FOR UPDATE" in q["sql"]]

    def test_the_selection_lock_keeps_the_root_election_ordering(self):
        locks = self._lock_sql(
            lambda: _group(self.user, is_admin=True, link_ids=[self.a.id, self.c.id])
        )
        # The selection lock is the only one that does not filter on
        # ``parent_id``: the reindex locks key on it (and use ``NOT (id IN ...)``
        # to exclude the rows they are about to move), so a bare ``"id" IN`` test
        # would match those too. Matching on the WHERE fragment, not the column
        # list — every one of these selects ``parent_id`` as a column.
        selection = [sql for sql in locks if '"parent_id" =' not in sql]
        self.assertEqual(len(selection), 1, msg="\n".join(locks))
        self.assertIn('"id" IN', selection[0])
        self.assertIn(
            'ORDER BY "incident_socialmedialink"."occurred_at" ASC', selection[0]
        )
        self.assertIn('"incident_socialmedialink"."id" ASC', selection[0])

    def test_every_other_lock_is_ordered_by_pk(self):
        # ``a`` and ``b`` nest FIRST (outside the capture) so the run under test
        # really does take a target lock and really does reindex a sibling set.
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])

        locks = self._lock_sql(
            lambda: _group(
                self.user, is_admin=True, link_ids=[self.c.id], parent_id=self.a.id
            )
        )
        self.assertTrue(locks, "expected the grouping to issue row locks")
        sibling_locks = [sql for sql in locks if '"parent_id" =' in sql]
        for sql in sibling_locks:
            self.assertIn(
                'ORDER BY "incident_socialmedialink"."id" ASC',
                sql,
                msg=(
                    "this lock is unordered, so two concurrent operations over "
                    "overlapping rows can take them in opposite orders and "
                    "deadlock:\n" + sql
                ),
            )
        # At least one sibling-set lock really was taken, so the loop above is not
        # vacuously true.
        self.assertTrue(
            sibling_locks, msg="expected a sibling-set lock:\n" + "\n".join(locks)
        )

    def test_the_target_lock_is_pinned_to_the_base_table(self):
        # Postgres cannot lock the nullable side of an outer join, so a
        # ``select_related`` added to the target lookup later would raise
        # "FOR UPDATE cannot be applied to the nullable side of an outer join".
        # ``of=("self",)`` is the insurance, and it is free — asserted here so it
        # cannot be tidied away as a no-op.
        locks = self._lock_sql(
            lambda: _group(
                self.user, is_admin=True, link_ids=[self.c.id], parent_id=self.a.id
            )
        )
        self.assertTrue(
            any('FOR UPDATE OF "incident_socialmedialink"' in sql for sql in locks),
            msg="no base-table-pinned lock was issued:\n" + "\n".join(locks),
        )

    def test_the_ungroup_and_reorder_locks_are_ordered(self):
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])

        for run in (
            lambda: _ungroup(self.user, is_admin=True, link_ids=[self.a.id, self.c.id]),
            lambda: _reorder(
                self.user, is_admin=True, parent_id=self.a.id, link_ids=[self.b.id]
            ),
        ):
            locks = self._lock_sql(run)
            self.assertTrue(locks)
            for sql in locks:
                self.assertIn(
                    'ORDER BY "incident_socialmedialink"."id" ASC',
                    sql,
                    msg=(
                        "this lock is unordered, so two concurrent calls over "
                        "overlapping rows can deadlock:\n" + sql
                    ),
                )


class ReorderTests(TestCase):
    """``reorderSocialMediaLinks``: the only surface that can SET a sequence."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-reorder")
        self.root = _link(
            self.user, "https://x.com/lrt/status/201", occurred_at=EARLIEST
        )
        self.children = [
            _link(
                self.user,
                f"https://x.com/lrt/status/21{index}",
                occurred_at=EARLIEST + dt.timedelta(hours=index),
            )
            for index in range(3)
        ]
        _group(
            self.user,
            is_admin=True,
            link_ids=[self.root.id] + [child.id for child in self.children],
        )
        self.assertEqual(
            _child_ids(self.root.id), [child.id for child in self.children]
        )

    def test_the_named_order_becomes_the_stored_order(self):
        order = [self.children[2].id, self.children[0].id, self.children[1].id]

        _reorder(self.user, is_admin=True, parent_id=self.root.id, link_ids=order)

        self.assertEqual(_child_ids(self.root.id), order)
        self.assertEqual(_positions(self.root.id), [10, 20, 30])
        _assert_numbered(self, self.root.id)

    def test_a_partial_reorder_leads_with_the_named_link(self):
        # The console's "move up": naming one child puts it first and the rest
        # keep their relative order behind it.
        _reorder(
            self.user,
            is_admin=True,
            parent_id=self.root.id,
            link_ids=[self.children[1].id],
        )

        self.assertEqual(
            _child_ids(self.root.id),
            [self.children[1].id, self.children[0].id, self.children[2].id],
        )
        self.assertEqual(_positions(self.root.id), [10, 20, 30])
        _assert_numbered(self, self.root.id)

    def test_repeating_a_reorder_writes_nothing(self):
        order = [self.children[1].id, self.children[2].id, self.children[0].id]
        _reorder(self.user, is_admin=True, parent_id=self.root.id, link_ids=order)
        after_first = _tree()

        with CaptureQueriesContext(connection) as ctx:
            _reorder(self.user, is_admin=True, parent_id=self.root.id, link_ids=order)

        self.assertEqual(
            [
                q["sql"]
                for q in ctx.captured_queries
                if q["sql"].lstrip().upper().startswith("UPDATE")
            ],
            [],
        )
        self.assertEqual(_tree(), after_first)

    def test_the_roots_can_be_reordered(self):
        # ``parentId: null`` is a real use, not a degenerate one: the console
        # decides which link leads a thread.
        first, second = self.children[0], self.children[1]
        _ungroup(self.user, is_admin=True, link_ids=[first.id, second.id])

        _reorder(
            self.user,
            is_admin=True,
            parent_id=None,
            link_ids=[second.id, first.id, self.root.id],
        )

        self.assertEqual(
            sorted(
                SocialMediaLink.objects.filter(parent__isnull=True).values_list(
                    "pk", flat=True
                )
            ),
            sorted([second.id, first.id, self.root.id]),
        )
        # Renumbering the root set is also what clears the position tie left
        # behind by the ungroup above — the documented remedy.
        _assert_numbered(self, None)

    def test_ids_that_are_not_siblings_are_rejected(self):
        outsider = _link(self.user, "https://x.com/lrt/status/219", occurred_at=BEFORE)
        before = _tree()

        with self.assertRaises(IncidentServiceError):
            _reorder(
                self.user,
                is_admin=True,
                parent_id=self.root.id,
                link_ids=[self.children[0].id, outsider.id],
            )

        self.assertEqual(_tree(), before)
        self.assertIsNone(_parent_of(outsider.id))

    def test_a_root_cannot_be_reordered_among_somebody_elses_sublinks(self):
        # ``root``'s parent is ``None``, so it is a sibling of no child set other
        # than the roots. Asking for it as a child of itself is the sibling check
        # firing, not a cycle.
        with self.assertRaises(IncidentServiceError):
            _reorder(
                self.user,
                is_admin=True,
                parent_id=self.root.id,
                link_ids=[self.root.id],
            )

    def test_an_unknown_root_set_is_rejected_when_the_caller_names_no_link(self):
        with self.assertRaises(IncidentServiceError):
            _reorder(
                self.user, is_admin=True, parent_id=987654321, link_ids=[self.root.id]
            )


class UngroupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-ungroup")
        self.root = _link(
            self.user, "https://x.com/lrt/status/221", occurred_at=EARLIEST
        )
        self.m1 = _link(self.user, "https://x.com/lrt/status/222", occurred_at=MIDDLE)
        self.m2 = _link(self.user, "https://x.com/lrt/status/223", occurred_at=LATEST)
        _group(
            self.user, is_admin=True, link_ids=[self.root.id, self.m1.id, self.m2.id]
        )
        self.grandchild = _link(
            self.user, "https://x.com/lrt/status/224", occurred_at=LATEST
        )
        _group(
            self.user,
            is_admin=True,
            link_ids=[self.grandchild.id],
            parent_id=self.m1.id,
        )

    def test_ungrouping_promotes_the_named_link_to_a_root(self):
        _ungroup(self.user, is_admin=True, link_ids=[self.m1.id])

        self.assertIsNone(_parent_of(self.m1.id))
        # The root is untouched and still roots what is left of the thread.
        self.assertIsNone(_parent_of(self.root.id))
        self.assertEqual(_child_ids(self.root.id), [self.m2.id])
        _assert_well_formed(self)

    def test_ungrouping_leaves_the_links_own_sublinks_attached(self):
        """The asymmetry, stated as a test because a reader will expect a cascade.

        Only the NAMED links are detached. ``grandchild`` was never named, so it
        keeps pointing at ``m1`` and the branch simply continues under a
        representative that is now itself a root. This is correct, not a missing
        cascade: a cascade would have to invent a new parent for an arbitrary
        subtree, and every such guess is a thread-topology decision the caller did
        not make. Dissolving the branch is ungrouping its links, one call at a
        time, and every intermediate state is a legal tree.
        """
        before = _tree()

        _ungroup(self.user, is_admin=True, link_ids=[self.m1.id])

        self.assertEqual(_parent_of(self.grandchild.id), self.m1.id)
        self.assertEqual(_child_ids(self.m1.id), [self.grandchild.id])
        # Everything except the one cleared edge is byte-identical, ``position``
        # included: ungroup writes ``["parent"]`` and nothing else.
        self.assertEqual(
            [row for row in _tree() if row[0] != self.m1.id],
            [row for row in before if row[0] != self.m1.id],
        )
        self.assertEqual(_parent_of(self.m1.id), None)
        _assert_well_formed(self)

    def test_ungrouping_the_root_leaves_its_sublinks_attached(self):
        _ungroup(self.user, is_admin=True, link_ids=[self.root.id])

        self.assertIsNone(_parent_of(self.root.id))
        self.assertEqual(_child_ids(self.root.id), [self.m1.id, self.m2.id])
        self.assertEqual(_parent_of(self.grandchild.id), self.m1.id)
        _assert_well_formed(self)

    def test_ungrouping_every_sublink_leaves_two_singleton_roots(self):
        _ungroup(self.user, is_admin=True, link_ids=[self.m1.id, self.m2.id])
        _ungroup(self.user, is_admin=True, link_ids=[self.grandchild.id])

        self.assertIsNone(_parent_of(self.root.id))
        self.assertIsNone(_parent_of(self.m1.id))
        self.assertIsNone(_parent_of(self.m2.id))
        self.assertIsNone(_parent_of(self.grandchild.id))
        self.assertEqual(
            SocialMediaLink.objects.filter(parent__isnull=False).count(), 0
        )
        _assert_well_formed(self)


class AtomicityTests(TestCase):
    """A multi-link write is ONE ``transaction.atomic()`` block.

    Asserted by making the write itself fail after it has already changed
    something: a service that flushed per link, or outside the block, would leave
    the first link moved. Asserting the error alone cannot tell the two apart,
    which is why this test injects the failure instead.
    """

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-atomic")
        self.a = _link(self.user, "https://x.com/lrt/status/231", occurred_at=EARLIEST)
        self.b = _link(self.user, "https://x.com/lrt/status/232", occurred_at=MIDDLE)
        self.c = _link(self.user, "https://x.com/lrt/status/233", occurred_at=LATEST)

    def _explode_after_one_row(self, rows):
        real_write = social_link_threads._write_structure
        real_write(rows[:1])
        raise RuntimeError("simulated failure after the first row was written")

    def test_a_failure_mid_write_rolls_the_whole_group_back(self):
        before = _tree()

        with patch.object(
            social_link_threads, "_write_structure", self._explode_after_one_row
        ):
            with self.assertRaises(RuntimeError):
                _group(
                    self.user, is_admin=True, link_ids=[self.a.id, self.b.id, self.c.id]
                )

        self.assertEqual(_tree(), before)
        _assert_well_formed(self)

    def test_a_failure_mid_reorder_rolls_the_whole_sibling_set_back(self):
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id, self.c.id])
        before = _tree()

        with patch.object(
            social_link_threads, "_write_structure", self._explode_after_one_row
        ):
            with self.assertRaises(RuntimeError):
                _reorder(
                    self.user,
                    is_admin=True,
                    parent_id=self.a.id,
                    link_ids=[self.c.id, self.b.id],
                )

        self.assertEqual(_tree(), before)


GROUP_MUTATION = """
    mutation Group($linkIds: [ID!]!, $parentId: ID) {
        groupSocialMediaLinks(linkIds: $linkIds, parentId: $parentId) { ok id }
    }
"""

UNGROUP_MUTATION = """
    mutation Ungroup($linkIds: [ID!]!) {
        ungroupSocialMediaLinks(linkIds: $linkIds) { ok id }
    }
"""

REORDER_MUTATION = """
    mutation Reorder($linkIds: [ID!]!, $parentId: ID) {
        reorderSocialMediaLinks(linkIds: $linkIds, parentId: $parentId) { ok }
    }
"""


class ThreadGroupingMutationTests(TestCase):
    """The mutation layer's job: the wire shape, the admin flag, and the ``id`` the
    client refetches from."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-tree-mutation")
        self.other = User.objects.create(firebase_id="test-user-tree-mutation-2")
        self.first = _link(
            self.user, "https://x.com/lrt/status/241", occurred_at=EARLIEST
        )
        self.second = _link(
            self.user, "https://x.com/lrt/status/242", occurred_at=MIDDLE
        )
        self.foreign = _link(
            self.other, "https://x.com/lrt/status/243", occurred_at=EARLIEST
        )

    def _run(self, query, variables, *, is_admin=True):
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=is_admin,
        ):
            return execute_graphql(query, variables=variables, user=self.user)

    def _group(self, link_ids, *, is_admin=True, parent_id=None):
        return self._run(
            GROUP_MUTATION,
            {
                "linkIds": [str(link_id) for link_id in link_ids],
                "parentId": str(parent_id) if parent_id is not None else None,
            },
            is_admin=is_admin,
        )

    def test_grouping_returns_the_root_id_so_the_client_can_refresh_one_thread(self):
        result = self._group([self.second.id, self.first.id])

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["groupSocialMediaLinks"]["ok"])
        # The root's id, as an int (GenericMutationReturn.id is int | None), so
        # the client can refetch exactly that thread.
        self.assertEqual(result.data["groupSocialMediaLinks"]["id"], self.first.id)
        self.assertEqual(_parent_of(self.second.id), self.first.id)

    def test_nesting_under_a_sublink_through_the_mutation(self):
        self._group([self.first.id, self.second.id])

        result = self._group([self.foreign.id], parent_id=self.second.id)

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        # The ROOT is named back even though the write nested a level deeper.
        self.assertEqual(result.data["groupSocialMediaLinks"]["id"], self.first.id)
        self.assertEqual(_parent_of(self.foreign.id), self.second.id)

    def test_the_old_thread_id_argument_is_gone_and_not_aliased(self):
        """The rename is deliberate, so a stale client must fail LOUDLY.

        An alias would keep accepting ``threadId`` and go on serving the one-level
        behaviour it names; the client would never learn that the sublink level it
        wants is spelled differently, and would keep flattening its threads. The
        schema-level rejection is the whole point of the rename.
        """
        result = self._run(
            """
            mutation Legacy($linkIds: [ID!]!, $threadId: ID) {
                groupSocialMediaLinks(linkIds: $linkIds, threadId: $threadId) { ok }
            }
            """,
            {
                "linkIds": [str(self.first.id), str(self.second.id)],
                "threadId": None,
            },
        )

        self.assertIsNotNone(result.errors)
        self.assertIn("threadId", str(result.errors[0]))
        self.assertIsNone(_parent_of(self.second.id))

    def test_a_non_admin_cannot_group_a_foreign_link_through_the_mutation(self):
        before = _tree()

        result = self._group([self.first.id, self.foreign.id], is_admin=False)

        self.assertIsNotNone(result.errors)
        self.assertEqual(_tree(), before)

    def test_ungrouping_returns_ok_and_detaches_only_the_named_links(self):
        self._group([self.first.id, self.second.id])

        result = self._run(UNGROUP_MUTATION, {"linkIds": [str(self.second.id)]})

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["ungroupSocialMediaLinks"]["ok"])
        self.assertIsNone(_parent_of(self.second.id))
        self.assertIsNone(_parent_of(self.first.id))

    def test_reorder_accepts_an_explicit_null_for_the_roots(self):
        result = self._run(
            REORDER_MUTATION,
            {
                "linkIds": [str(self.second.id), str(self.first.id)],
                "parentId": None,
            },
        )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["reorderSocialMediaLinks"]["ok"])
        # Two named roots lead in the order they were sent; ``foreign`` was not
        # named, so it keeps its relative order behind them. All three end up
        # numbered 10, 20, 30 — the tie an ungroup leaves behind is cleared by
        # renumbering the whole set.
        self.assertEqual(
            _child_ids(None), [self.second.id, self.first.id, self.foreign.id]
        )
        self.assertEqual(_positions(None), [10, 20, 30])
        _assert_numbered(self, None)

    def test_reorder_accepts_a_parent_id(self):
        self._group([self.first.id, self.second.id])
        result = self._run(
            REORDER_MUTATION,
            {"linkIds": [str(self.second.id)], "parentId": str(self.first.id)},
        )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["reorderSocialMediaLinks"]["ok"])
        self.assertEqual(_child_ids(self.first.id), [self.second.id])

    def test_omitting_parent_id_on_reorder_is_refused_not_treated_as_the_roots(self):
        """UNSET is a THIRD state, and it is not "the roots".

        ``strawberry.Maybe`` distinguishes omitted from ``null``, and the omission
        is the dangerous one: answering it as "reorder every root" would let a
        client that forgot the argument rewrite the order of the whole system's
        roots. It is refused, with a message that says which of the two the caller
        meant.
        """
        before = _tree()

        result = self._run(
            """
            mutation ReorderNoParent($linkIds: [ID!]!) {
                reorderSocialMediaLinks(linkIds: $linkIds) { ok }
            }
            """,
            {"linkIds": [str(self.second.id), str(self.first.id)]},
        )

        self.assertIsNotNone(result.errors)
        self.assertIn("parentId", str(result.errors[0]))
        self.assertEqual(_tree(), before)


class FeedLinkOccurredAtTests(TestCase):
    """``FeedLinkInput.occurredAt`` was declared and unwired — a schema field
    that silently did nothing. These pin the fixed contract: a value is stored
    verbatim, an omission falls back to the NOT NULL column default, and the
    canonical-URL dedup is untouched by either.

    Kept here because ``occurred_at`` is what elects a thread's root, so the two
    features are one contract: an event time that is not stored would silently
    re-root threads on submission time."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-feed-occurred")

    def _submit(self, *, url: str, **kwargs):
        # ``title`` is always supplied so the title path never reaches the
        # network (``fetch_page_title``); every assertion here is about the
        # event-time column.
        return _submit_feed_link(
            self.user,
            url=url,
            title="Reported delay",
            line_ids=[],
            station_ids=[],
            status=None,
            delay_minutes=None,
            notes="",
            **kwargs,
        )

    def test_an_explicit_event_time_is_stored_verbatim(self):
        result = self._submit(
            url="https://example.com/feed-occurred", occurred_at=EARLIEST
        )

        link = SocialMediaLink.objects.get(pk=result.link.id)
        self.assertEqual(link.occurred_at, EARLIEST)
        self.assertIsNone(link.occurred_at.tzinfo, msg="stored naive local")

    def test_omitting_it_falls_back_to_now(self):
        before = dt.datetime.now()
        result = self._submit(url="https://example.com/feed-occurred")
        after = dt.datetime.now()

        link = SocialMediaLink.objects.get(pk=result.link.id)
        self.assertGreaterEqual(link.occurred_at, before)
        self.assertLessEqual(link.occurred_at, after)

    def test_a_duplicate_canonical_url_still_short_circuits(self):
        """The dedup is the feed path's reason for existing — untouched, and it
        deliberately does NOT rewrite the first submission's event time."""
        first = self._submit(
            url="https://example.com/feed-occurred", occurred_at=EARLIEST
        )
        second = self._submit(
            url="https://example.com/feed-occurred/?utm_source=x#frag",
            occurred_at=LATEST,
        )

        self.assertTrue(second.is_duplicate)
        self.assertEqual(second.duplicate_of_id, first.link.id)
        self.assertEqual(
            SocialMediaLink.objects.filter(
                normalized_url="https://example.com/feed-occurred"
            ).count(),
            1,
        )
        link = SocialMediaLink.objects.get(pk=first.link.id)
        self.assertEqual(link.occurred_at, EARLIEST)
