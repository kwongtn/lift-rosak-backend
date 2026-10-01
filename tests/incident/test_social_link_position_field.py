"""``SocialMediaLinkScalar.position`` — the sibling sequence, exposed.

``position`` is the one number in the link tree that the server writes and no
client can read. It is ``OrderableTreeNode.position`` — the sibling sequence
inside ONE parent, written deterministically by the grouping service and by
``reorderSocialMediaLinks`` — and the scalar published the tree's SHAPE
(``parentId`` / ``isThreadRoot`` / ``sublinkCount`` / ``sublinks``) without its
ORDER. So the console hierarchy UI had nothing to render a sequence column from
and nothing to express a permutation in, and the honest alternative (faking it
from ``occurredAt``) would have made reorder meaningless: that is the FEED's
ordering, not the conversation's.

This is the read half of a write-then-read round trip that already exists
server-side, so the tests below pin the four things a client now depends on:

1. **The NULLABILITY is the contract.** ``position`` is a
   ``PositiveIntegerField(default=0)`` — NOT NULL on the model — so it renders
   ``position: Int!`` and a frontend type has to be ``number``, not
   ``number | null``. Asserted on the exact SDL line AND on graphql-core's
   non-null wrapper, because a client compiles against the printed SDL while
   execution enforces the wrapper: either one alone would leave a way for the
   two to disagree.

2. **It is a SIBLING number, and a client can order siblings with it.** A root
   and a sublink are given the SAME value here, on purpose: every root is one
   sibling set and every level of a tree is another, so the field is only
   comparable between two links with the same ``parentId``. Read as a global
   rank the fixtures below look like bugs, which is exactly the point.

3. **It is free.** It is a column on the row the feed has already fetched, so a
   client adding it to a page of fifty cards cannot make the page more
   expensive. Asserted by counting the queries of the same page with and
   without the field — the shape of the claim, not a number that would drift
   whenever the feed or the loader changes.

4. **The round trip works.** ``reorderSocialMediaLinks`` renumbers one sibling
   set to ``10, 20, 30, …``; those numbers have to come back out of the field, in
   the new order, through the real schema. The write half is already pinned by
   ``tests/incident/test_social_link_threads.py``; the read half is what was
   missing, and this is the test that would have caught a write-only column.

A NOTE ON THE QUERY COUNTS, because it costs an hour if you do not know it:
**only the FIRST async execution in a test is observable through
``CaptureQueriesContext``.** ``schema.execute`` is async and ``async_to_sync``
runs it in a fresh thread-sensitive executor per call, and Django's
``ConnectionHandler`` is ``thread_critical`` — the per-thread
``DatabaseWrapper`` the first call populates is not the one the second call logs
into, so a second ``CaptureQueriesContext`` in the same test captures ``0``
queries and looks like a spectacular optimisation. Every query-count assertion
below therefore owns its test and captures exactly once, and the with/without
comparison is made by pinning both sides to the same number rather than by
diffing two captures.

Runs under plain ``django.test.TestCase`` + ``asgiref.sync.async_to_sync`` (the
schema is async) and deliberately does NOT import pytest: pytest is not installed
in the app image, so a pytest-based file here is uncollectable dead code. Every
read goes through the REAL schema, and the mutation is the real mutation with
only the Firebase admin claim patched out (the harness
``tests/incident/test_social_link_threads.py`` already uses).
"""

import copy
import datetime as dt
import itertools
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from dotmap import DotMap
from graphql import GraphQLNonNull

from common.models import User
from incident.enums import SocialMediaLinkStatus
from incident.models import SocialMediaLink
from rosak.context import ContextLoaders
from rosak.schema import schema

# Distinct instants so a position-ordered result is distinguishable from both
# insertion order (ids ascending) and event order.
T0 = dt.datetime(2026, 9, 22, 9, 0, 0)
T1 = dt.datetime(2026, 9, 22, 10, 0, 0)
T2 = dt.datetime(2026, 9, 22, 11, 0, 0)
T3 = dt.datetime(2026, 9, 22, 12, 0, 0)

#: One page of the feed with ``position`` on every level, nested two deep so the
#: field is exercised on a ROOT and on a SUBLINK in a single payload: a root's
#: ``position`` ranks it among the roots, a sublink's among its own siblings,
#: and those are different sets.
FEED_QUERY = """
    query($first: Int!) {
      publicSocialMediaLinks(first: $first) {
        edges {
          node {
            id
            url
            occurredAt
            parentId
            position
            sublinks {
              id
              url
              occurredAt
              position
              sublinks {
                id
                position
              }
            }
          }
        }
      }
    }
"""

#: The same page with ``position`` removed and nothing else changed. Paired with
#: ``FEED_QUERY`` by the query-count class below: any difference between the two
#: is a resolver, a loader or a second round trip that ``position`` is not
#: entitled to.
FEED_QUERY_WITHOUT_POSITION = """
    query($first: Int!) {
      publicSocialMediaLinks(first: $first) {
        edges {
          node {
            id
            url
            occurredAt
            parentId
            sublinks {
              id
              url
              occurredAt
              sublinks {
                id
              }
            }
          }
        }
      }
    }
"""

#: The FLAT page — no ``sublinks``, so no loader is involved at all. This is the
#: clean comparison: two statements, and the only difference between the two
#: variants is whether ``"position"`` is in the SELECT list of the page query.
FLAT_QUERY = """
    query($first: Int!) {
      publicSocialMediaLinks(first: $first) {
        edges { node { id url occurredAt parentId position } }
      }
    }
"""

FLAT_QUERY_WITHOUT_POSITION = """
    query($first: Int!) {
      publicSocialMediaLinks(first: $first) {
        edges { node { id url occurredAt parentId } }
      }
    }
"""

REORDER_MUTATION = """
    mutation Reorder($linkIds: [ID!]!, $parentId: ID) {
        reorderSocialMediaLinks(linkIds: $linkIds, parentId: $parentId) { ok }
    }
"""

#: The cost of the FLAT page: ``totalCount`` and the page itself. Nothing else,
#: because nothing on this query fans out. Pinned on both sides of the field
#: below — if the feed ever grows a third statement, both tests move together.
FLAT_PAGE_COST = 2

#: The cost of the NESTED page on a fixture of one root and two children: the
#: flat page's two, plus ``sublink_subtrees``' existence probe for the batch and
#: one recursive CTE for the only row on the page that has children. The same
#: shape ``tests/incident/test_social_link_thread_fields.py`` pins, so a
#: regression here shows up as a diff against that module rather than as a
#: mystery.
NESTED_PAGE_COST = FLAT_PAGE_COST + 1 + 1

# Process-wide rather than per-test, so two tests cannot mint the same URL even
# if the runner ever stops rolling each one back in its own transaction. Nothing
# here asserts BY url (ids are unambiguous), but a collision would make a
# printed failure ambiguous, which is the only reason these bother.
_URL_SEQ = itertools.count(1)


def execute_graphql(query: str, variables=None, user=None):
    """Same harness the other incident tests use — a DotMap context, no auth."""
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


def social_link_scalar_block() -> str:
    """The ``type SocialMediaLinkScalar { … }`` block of the built SDL.

    Parsed out of ``str(schema)`` — the same string the committed snapshot is
    compared against — rather than off the snapshot file, because the question
    is what the schema SERVES; a test reading the snapshot would only prove the
    snapshot contains itself.
    """
    sdl = str(schema)
    start = sdl.index("type SocialMediaLinkScalar {")
    return sdl[start : sdl.index("\n}", start)]


def _sql_dump(queries) -> str:
    """The captured statements, one per line, for a failure message.

    A query-count assertion that fails with a bare "expected 2, got 3" leaves the
    reader guessing which of the four shapes grew a statement, and the whole
    claim of this file's cost class is that nothing did.
    """
    return "\n".join(f"--- [{i}] {q['sql'][:300]}" for i, q in enumerate(queries))


class PositionFieldTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-position-field")

    def _link(self, parent=None, **overrides) -> SocialMediaLink:
        """A publicly-visible LIVE link unless the test says otherwise.

        LIVE + not automated is the only unconditionally public combination, so a
        test that forgets a status still exercises the visible path rather than
        silently testing the hidden one.

        ``position`` is passed through untouched, and that has a consequence
        worth knowing: the library's auto-assign fires only on a FALSY value, so
        an explicit ``10`` survives and is what lets these tests make
        ``position`` disagree with both ``id`` and ``occurredAt`` — while an
        explicit ``0`` does not (it is auto-numbered instead).
        """
        fields = {
            "url": f"https://x.com/lrt/status/pos-{next(_URL_SEQ)}",
            "user": self.user,
            "status": SocialMediaLinkStatus.LIVE,
        }
        if parent is not None:
            fields["parent"] = parent
        fields.update(overrides)
        return SocialMediaLink.objects.create(**fields)

    def _feed_nodes(self, query: str = FEED_QUERY, first: int = 100) -> dict:
        result = execute_graphql(query, variables={"first": first})
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return {
            int(edge["node"]["id"]): edge["node"]
            for edge in result.data["publicSocialMediaLinks"]["edges"]
        }


class PositionNullabilityTests(PositionFieldTestCase):
    """``position: Int!`` — the exact line, and why the ``!`` is load-bearing."""

    def test_the_built_sdl_declares_it_as_a_non_null_int(self):
        block = social_link_scalar_block()

        self.assertIn(
            "\n  position: Int!\n",
            f"\n{block}\n",
            msg=f"SocialMediaLinkScalar.position is not `position: Int!`. Got:\n{block}",
        )

    def test_it_is_not_nullable_in_graphql_core_either(self):
        # The printed SDL is what a client compiles against; the non-null wrapper
        # is what actually enforces it at execution. Asserting only the string
        # would miss a schema whose printer and type map disagree, and asserting
        # only the wrapper would miss a client that reads the SDL — and it is
        # exactly the ``!`` that a frontend type generator keys off.
        field = schema._schema.type_map["SocialMediaLinkScalar"].fields["position"]

        self.assertEqual(str(field.type), "Int!")
        self.assertIsInstance(field.type, GraphQLNonNull)
        self.assertIs(field.type.of_type, schema._schema.type_map["Int"])

    def test_the_model_column_really_is_not_null(self):
        # WHY the field takes no null branch, read off the model rather than
        # asserted as a constant: ``OrderableTreeNode`` declares
        # ``PositiveIntegerField(default=0)``, so a client typing this
        # ``number | null`` has been told about a state that cannot occur, and
        # ``position ?? 0`` is dead code that reads as though it were not.
        model_field = SocialMediaLink._meta.get_field("position")

        self.assertFalse(model_field.null, msg="the model column became nullable")

    def test_a_stored_value_comes_back_verbatim_even_when_it_is_not_ten(self):
        # The field is the COLUMN, not a derived rank: a value the library never
        # produces (7 — the service always renumbers ``10, 20, 30, …``) still
        # reads back exactly as written. A resolver that normalised, divided by
        # ten or computed an index would answer 0 or 1 here, and a client that
        # diffed two payloads would see the sequence shift under it.
        odd = self._link(occurred_at=T0, position=7)

        self.assertEqual(odd.position, 7, msg="the model did not store the value")

        node = self._feed_nodes()[odd.id]

        self.assertEqual(node["position"], 7)
        self.assertIsInstance(node["position"], int)

    def test_an_auto_assigned_position_comes_back_as_a_number(self):
        # A link inserted with no explicit rank is numbered by the library
        # (``max_sibling + 10``), so the common case on a fresh feed is a value
        # the client never sent. It must be a plain number that can be sorted —
        # including the first sibling, which the library puts at ``10`` and NOT at
        # ``0``: a client rendering "1." from the number is still wrong, but a
        # client sorting on it is right, and that is what the field is for.
        first = self._link(occurred_at=T0)
        second = self._link(occurred_at=T1)

        nodes = self._feed_nodes()

        self.assertEqual(first.position, 10)
        self.assertEqual(nodes[first.id]["position"], 10)
        self.assertEqual(nodes[second.id]["position"], 20)
        self.assertEqual(
            sorted(
                (n["position"] for n in nodes.values()),
            ),
            [10, 20],
        )


class SiblingPositionTests(PositionFieldTestCase):
    """It is a rank among SIBLINGS, and a client can order siblings with it."""

    def test_a_root_and_a_sublink_each_expose_their_own_sibling_position(self):
        # Two DIFFERENT sibling sets, deliberately given the same number: all the
        # roots are one set and all of root's children are another, so the root
        # and its first sublink can both read 10. Read as a global rank this
        # fixture looks like a bug, which is the point — the field's contract is
        # per-parent, and a client comparing two positions without comparing
        # their parents has made a category error the API cannot catch.
        root = self._link(occurred_at=T0, position=10)
        first = self._link(root, occurred_at=T1, position=10)
        second = self._link(root, occurred_at=T2, position=20)
        deeper = self._link(first, occurred_at=T3, position=30)

        nodes = self._feed_nodes()

        self.assertEqual(nodes[root.id]["position"], 10)
        self.assertEqual(nodes[first.id]["position"], 10)
        self.assertEqual(nodes[second.id]["position"], 20)
        self.assertEqual(nodes[deeper.id]["position"], 30)
        # …and the collision is between a root and a sublink, i.e. ACROSS
        # parents, which is precisely the comparison that must never be made.
        self.assertIsNone(nodes[root.id]["parentId"])
        self.assertEqual(nodes[first.id]["parentId"], str(root.id))

    def test_a_client_can_order_siblings_by_the_exposed_position(self):
        # All three candidate orders disagree at once:
        #
        #   position : b (10), a (20), c (30)
        #   id ASC   : a, b, c   (a was created first)
        #   occurred : a (T1), b (T3), c (T2)
        #
        # so a payload whose ``position`` values cannot reproduce the sublink
        # order has a field that is decorative rather than usable — which is the
        # failure the console's sequence column would have shipped with.
        root = self._link(occurred_at=T0)
        a = self._link(root, occurred_at=T1, position=20)
        b = self._link(root, occurred_at=T3, position=10)
        c = self._link(root, occurred_at=T2, position=30)

        sublinks = self._feed_nodes()[root.id]["sublinks"]

        self.assertLess(a.id, b.id)
        self.assertLess(b.id, c.id)
        by_position = sorted(sublinks, key=lambda node: node["position"])
        self.assertEqual(
            [node["id"] for node in by_position],
            [str(b.id), str(a.id), str(c.id)],
        )
        # Sorting by the event instant — the tempting substitute, and what every
        # OTHER link list in this schema is ordered by — gives a different
        # sequence, so the two are not interchangeable.
        by_occurred = sorted(sublinks, key=lambda node: node["occurredAt"])
        self.assertNotEqual(
            [node["id"] for node in by_position],
            [node["id"] for node in by_occurred],
            msg="position and occurredAt agree here, so this fixture cannot tell "
            "the sibling order from the feed order",
        )
        # And the field agrees with what ``sublinks`` already returns, so a client
        # can render the server's order or its own sort and get one answer.
        self.assertEqual(
            [node["id"] for node in sublinks], [str(b.id), str(a.id), str(c.id)]
        )

    def test_two_roots_may_carry_the_same_position(self):
        # ⚠️ THE TRAP, made representable rather than described. ``position`` is
        # scoped to a parent and a root's parent is ``None``, so every root is a
        # sibling of every other root and two of them can hold the same value.
        # Nothing constrains the column either, so a hand-edited duplicate is
        # equally legal. The field therefore can never be a global tie-break, a
        # sort key across parents, or an identity: ``id`` is the only thing that
        # names a link, and ``(position, id)`` is the order inside ONE sibling
        # set — which is exactly what ``sublinks`` does internally, so a client
        # wanting the same stability has to break the tie the same way.
        first = self._link(occurred_at=T0, position=10)
        second = self._link(occurred_at=T2, position=10)

        nodes = self._feed_nodes()

        self.assertIsNone(nodes[first.id]["parentId"])
        self.assertIsNone(nodes[second.id]["parentId"])
        self.assertEqual(nodes[first.id]["position"], 10)
        self.assertEqual(nodes[second.id]["position"], 10)
        # Distinct rows, indistinguishable by position alone.
        self.assertNotEqual(nodes[first.id]["id"], nodes[second.id]["id"])
        roots = sorted(
            (nodes[first.id], nodes[second.id]),
            key=lambda node: (node["position"], int(node["id"])),
        )
        self.assertEqual(
            [node["id"] for node in roots], [str(first.id), str(second.id)]
        )

    def test_the_number_is_a_rank_and_not_an_index_so_a_gap_is_room(self):
        # ⚠️ THE OTHER TRAP. The library spaces siblings by ten so one can be
        # inserted between two others without renumbering them, which means the
        # value is NOT an ordinal a client may render: ``position`` 40 does not
        # mean "the fourth". Both halves are pinned — the gap is visible to the
        # client, and the row sitting after it is present and ordered, so the gap
        # is the room it is meant to be rather than a missing row.
        root = self._link(occurred_at=T0)
        first = self._link(root, occurred_at=T1, position=10)
        second = self._link(root, occurred_at=T2, position=20)
        third = self._link(root, occurred_at=T3, position=40)

        sublinks = self._feed_nodes()[root.id]["sublinks"]

        self.assertEqual(
            [child["position"] for child in sublinks],
            [10, 20, 40],
            msg="the 30 gap is not readable, so a client cannot see the room it "
            "would insert into",
        )
        self.assertEqual(
            [child["id"] for child in sublinks],
            [str(first.id), str(second.id), str(third.id)],
        )
        # No row is missing: three children, and the last is numbered 40.
        self.assertEqual(len(sublinks), 3)


class PositionCostsNoQueryTests(PositionFieldTestCase):
    """⚠️ A model attribute, so it must not cost anything.

    ``position`` is a column on the row the feed has already fetched. A resolver
    or a loader here would be invisible in a schema diff and very visible on a
    page of fifty cards — exactly the class of regression the sibling hierarchy
    fields were built to avoid, so it is pinned in numbers rather than in a
    comment.

    Each test below owns ONE ``CaptureQueriesContext`` and the with/without
    comparison is made by pinning both sides to the same number; see the module
    docstring for why a second capture in the same test would read ``0``.
    """

    # One root with two children, so the fixture exercises the loader's subtree
    # read as well as the page read: a field that queried per row would show up on
    # the children's own rows too, not just on the root's.
    def setUp(self):
        super().setUp()
        self.root = self._link(occurred_at=T0)
        self.first = self._link(self.root, occurred_at=T1, position=10)
        self.second = self._link(self.root, occurred_at=T2, position=20)

    def _capture(self, query: str) -> tuple[dict, list[dict]]:
        with CaptureQueriesContext(connection) as ctx:
            nodes = self._feed_nodes(query)
        return nodes, list(ctx.captured_queries)

    def test_the_flat_page_selects_position_from_the_row_it_already_fetches(self):
        # The positive, structural version of the cost claim. Two statements and
        # no more: ``totalCount`` and the page. The page statement reads the
        # column off the row, so the number provably came out of a fetch that was
        # happening anyway — a resolver or a loader would add a statement here
        # and fail the count.
        nodes, queries = self._capture(FLAT_QUERY)

        self.assertEqual(len(queries), FLAT_PAGE_COST, msg=_sql_dump(queries))
        page = [q["sql"] for q in queries if '"position"' in q["sql"]]
        self.assertEqual(
            len(page),
            1,
            msg="expected one statement to read the column:\n" + _sql_dump(queries),
        )
        self.assertIn('"incident_socialmedialink"."id"', page[0])
        # A filter or a sort on the sibling sequence would mean the API is
        # treating it as something it is not — a global, addressable order. It is
        # only ever SELECTED.
        self.assertNotIn('WHERE "position"', page[0])
        self.assertEqual(nodes[self.root.id]["position"], 10)
        self.assertEqual(nodes[self.first.id]["position"], 10)
        self.assertEqual(nodes[self.second.id]["position"], 20)

    def test_the_flat_page_costs_the_same_without_position(self):
        # The other half of the A/B. Note WHY the two sides are equal down to the
        # statement: the ORM selects the WHOLE row, so ``"position"`` is already
        # in the page query whether or not the client asked for the field. There
        # is no column left to add, which is the entire reason the field is free —
        # and the reason a future "optimisation" that deferred it (a resolver, a
        # loader, ``.only()`` on the feed) would be a regression rather than a
        # tidy-up. The assertion below is that the row is fetched whole.
        _nodes, queries = self._capture(FLAT_QUERY_WITHOUT_POSITION)

        self.assertEqual(len(queries), FLAT_PAGE_COST, msg=_sql_dump(queries))
        page = [
            q["sql"]
            for q in queries
            if "SELECT" in q["sql"] and "COUNT" not in q["sql"]
        ]
        self.assertEqual(len(page), 1, msg=_sql_dump(queries))
        for column in ('"id"', '"position"', '"parent_id"', '"occurred_at"'):
            self.assertIn(
                f'"incident_socialmedialink".{column}',
                page[0],
                msg=f"the page query no longer fetches the whole row ({column})",
            )

    def test_the_nested_page_costs_the_same_with_position(self):
        # The realistic console shape: the hierarchy selection AND the sequence.
        # Four statements — the flat pair, ``sublink_subtrees``' existence probe
        # for the batch, and one recursive CTE for the root (the only row on the
        # page with children). ``position`` is inside the page statement and
        # inside the CTE, and costs nothing of its own.
        nodes, queries = self._capture(FEED_QUERY)

        self.assertEqual(len(queries), NESTED_PAGE_COST, msg=_sql_dump(queries))
        self.assertEqual(nodes[self.root.id]["position"], 10)
        self.assertEqual(
            [child["position"] for child in nodes[self.root.id]["sublinks"]],
            [10, 20],
        )

    def test_the_nested_page_costs_the_same_without_position(self):
        _nodes, queries = self._capture(FEED_QUERY_WITHOUT_POSITION)

        self.assertEqual(len(queries), NESTED_PAGE_COST, msg=_sql_dump(queries))


class ReorderRoundTripTests(PositionFieldTestCase):
    """The write-then-read round trip that makes the field worth exposing.

    ``reorderSocialMediaLinks`` is the only surface in the API that can SET a
    sequence: it takes a permutation of one existing sibling set and renumbers it
    ``10, 20, 30, …``. Before this field the mutation wrote a column no client
    could see — a client could change the order and had no way to show the
    operator what the order currently was, let alone confirm the write landed.
    These go through the REAL mutation and read the result back through the REAL
    field, so the two halves are asserted to agree rather than each being right
    on its own.

    Only the Firebase admin claim is patched: the service's own validation
    (sibling membership, cycles, depth) is exercised in
    ``tests/incident/test_social_link_threads.py`` and is not what this file is
    about.
    """

    def setUp(self):
        super().setUp()
        self.root = self._link(occurred_at=T0)
        self.first = self._link(self.root, occurred_at=T1, position=10)
        self.second = self._link(self.root, occurred_at=T3, position=20)
        self.third = self._link(self.root, occurred_at=T2, position=30)

    def _reorder(self, link_ids, parent_id):
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=True,
        ):
            return execute_graphql(
                REORDER_MUTATION,
                {
                    "linkIds": [str(link_id) for link_id in link_ids],
                    "parentId": str(parent_id) if parent_id is not None else None,
                },
                user=self.user,
            )

    def test_reordering_a_sibling_set_is_readable_back_through_the_field(self):
        # A permutation that disagrees with both the current numbering and the
        # event order, so a payload that merely echoed the old state fails.
        result = self._reorder(
            [self.third.id, self.first.id, self.second.id], self.root.id
        )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["reorderSocialMediaLinks"]["ok"])

        sublinks = self._feed_nodes()[self.root.id]["sublinks"]

        # The field shows the NEW order, and the renumbering is ``10, 20, 30`` —
        # so the client's sequence column and the server's ``sublinks`` order are
        # one answer, which is what makes the round trip a round trip rather than
        # two features that happen to exist.
        self.assertEqual(
            [child["id"] for child in sublinks],
            [str(self.third.id), str(self.first.id), str(self.second.id)],
        )
        self.assertEqual([child["position"] for child in sublinks], [10, 20, 30])

    def test_reordering_one_sibling_set_leaves_the_others_alone(self):
        # ``position`` is scoped to a parent, so renumbering one set must not
        # renumber another — and the field is how a client would notice if it did,
        # since the second tree's rows travel in the same payload.
        other = self._link(occurred_at=T0)
        stranger = self._link(other, occurred_at=T1, position=10)

        self._reorder([self.second.id, self.third.id, self.first.id], self.root.id)

        nodes = self._feed_nodes()
        self.assertEqual(
            [child["position"] for child in nodes[self.root.id]["sublinks"]],
            [10, 20, 30],
        )
        self.assertEqual(
            [child["position"] for child in nodes[other.id]["sublinks"]], [10]
        )
        self.assertEqual(nodes[stranger.id]["position"], 10)

    def test_reordering_the_roots_is_visible_on_the_roots(self):
        # ``parentId: null`` is the root set — a real sibling set like any other,
        # so the field has to answer for it too or the console's "which link leads
        # this thread" control has nothing to render. Both roots are explicitly
        # numbered so the expected values are not the library's auto-assign,
        # which would let this pass for the wrong reason.
        other = self._link(occurred_at=T1, position=10)

        result = self._reorder([other.id, self.root.id], None)

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["reorderSocialMediaLinks"]["ok"])

        nodes = self._feed_nodes()
        self.assertEqual(nodes[other.id]["position"], 10)
        self.assertEqual(nodes[self.root.id]["position"], 20)
        # The named order is the stored order, and the console re-renders the root
        # sequence from these two numbers alone.
        roots = sorted(
            (nodes[other.id], nodes[self.root.id]),
            key=lambda node: (node["position"], int(node["id"])),
        )
        self.assertEqual(
            [node["id"] for node in roots], [str(other.id), str(self.root.id)]
        )
        # The feed page is still ``occurredAt DESC``, which is the whole reason a
        # client cannot draw the root sequence from arrival order: ``other`` is
        # the LATER event so it arrives first, and it is also the one just
        # promoted to lead.
        self.assertEqual(nodes[self.root.id]["occurredAt"], T0.isoformat())
        self.assertEqual(nodes[other.id]["occurredAt"], T1.isoformat())
