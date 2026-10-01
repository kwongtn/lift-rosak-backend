"""Link hierarchy on ``SocialMediaLinkScalar`` — the public read contract.

``parentId`` / ``isThreadRoot`` / ``sublinkCount`` / ``sublinks`` are what the
home feed's thread UI renders now that ``SocialMediaLink`` is an ordered nested
tree (``parent`` + ``position``, migration 0031). Three properties are worth
pinning, and all three are things the flat depth-1 design could not even ask:

1. **They count what a visitor could actually open, and they count the SAME
   thing.** ``sublinkCount`` is the number on the "N links" chip and
   ``sublinks`` is what the chip expands to. Both read one loader call, so the
   chip cannot disagree with the list it labels — a divergence would advertise a
   link that leads nowhere. The moderation rule is the shared predicate
   (``incident.services.social_link_visibility``), applied to every row at every
   depth, so a HIDDEN row is not reachable through the nesting even though the
   feed's own ``.exclude(status=HIDDEN)`` never sees it.

2. **They batch, per SUBTREE and not per level.** ``node.children`` is a plain
   ``RelatedManager``, so a tree walked the obvious way costs one query per
   level per node; a depth-3 tree is 3 queries for one ``descendants()``
   statement. The loader fetches each subtree whole and rebuilds the nesting in
   Python. That is asserted with ``CaptureQueriesContext`` rather than left to a
   comment — and the assertions pin the EXACT query shape (one existence probe
   for the batch + one CTE per threaded key), so a reimplementation that
   re-fetches ``filter(parent_id=self.id)`` per row fails here instead of
   quietly costing 50 queries on a page of 50 cards.

3. **They describe each node, not the whole tree.** ``sublinkCount`` counts
   THIS node's descendants at any depth; a member answers for its own
   sublinks, never for its thread. A client that wants the whole conversation
   walks ``parentId`` up to the root. The trap that comes with it:
   ``isThreadRoot`` is ``parentId is None``, which is ALSO true for every
   ungrouped link — it is a root marker, never a "has sublinks" marker, and the
   only correct affordance test is ``sublinkCount > 0``.

4. **The read side is not bounded by ``MAX_THREAD_DEPTH``; the write side is.**
   A client may select ``sublinks`` nested deeper than the store holds, and the
   levels it does not have come back as ``[]`` — never an error, never a
   fabricated row. ``OverDeepSelectionTests`` executes that promise rather than
   taking the two docstrings that make it for granted, because a read-side clamp
   or a validation error would break a client that is working today.

Runs under plain ``django.test.TestCase`` + ``asgiref.sync.async_to_sync`` (the
GraphQL schema is async) and deliberately does NOT import pytest: pytest is not
installed in the app image, so a pytest-based file here is uncollectable dead
code. Every query goes through the REAL schema — the loader plumbing only proves
itself inside GraphQL execution, where the fields are actually resolved.
"""

import copy
import datetime as dt
import hashlib
import itertools

from asgiref.sync import async_to_sync
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from dotmap import DotMap

from common.models import User
from incident.enums import SocialMediaLinkStatus
from incident.models import SocialMediaLink
from incident.schema.loaders import batch_load_sublink_subtrees
from incident.services.social_link_threads import MAX_THREAD_DEPTH
from rosak.context import ContextLoaders
from rosak.schema import schema

# Fixed, distinct instants so a ``position``-ordered result is distinguishable
# from insertion order (ids ascending) and from event order.
T0 = dt.datetime(2026, 9, 20, 9, 0, 0)
T1 = dt.datetime(2026, 9, 20, 10, 0, 0)
T2 = dt.datetime(2026, 9, 20, 11, 0, 0)
T3 = dt.datetime(2026, 9, 20, 12, 0, 0)

# ``first`` is generous so the whole fixture comes back on one page: the batching
# assertions are about queries-per-row, not about pagination. The hierarchy
# selection is one level deep HERE on purpose — the query-count tests want the
# loader keys to be the rows on the page and nothing else, so the per-subtree
# bound is exactly readable.
FEED_QUERY = """
    query($first: Int!) {
      publicSocialMediaLinks(first: $first) {
        edges {
          node {
            id
            url
            occurredAt
            parentId
            isThreadRoot
            sublinkCount
            sublinks {
              id
              url
              occurredAt
            }
          }
        }
      }
    }
"""

# The same selection nested to the depth this file's fixtures reach, for the
# agreement test: ``sublinkCount`` has to equal the rows a client can actually
# walk to through ``sublinks``, and that is only checkable on a payload that
# carries the nesting.
DEEP_QUERY = """
    query($first: Int!) {
      publicSocialMediaLinks(first: $first) {
        edges {
          node {
            id
            url
            sublinkCount
            sublinks {
              id
              url
              sublinkCount
              sublinks {
                id
                url
                sublinkCount
                sublinks {
                  id
                  url
                  sublinkCount
                }
              }
            }
          }
        }
      }
    }
"""

# One ``sublinks`` level DEEPER than ``MAX_THREAD_DEPTH`` levels of data, so the
# deepest selection asks a leaf for children it does not have. Read side is not
# capped; this is the payload that proves it comes back empty. Kept separate from
# ``DEEP_QUERY`` on purpose: that one is used by the query-COUNT assertions,
# which want the loader keys to be exactly the rows on the page, so its depth is
# tied to the fixture rather than to the cap.
OVER_DEEP_QUERY = """
    query($first: Int!) {
      publicSocialMediaLinks(first: $first) {
        edges {
          node {
            id
            sublinkCount
            sublinks {
              id
              sublinkCount
              sublinks {
                id
                sublinkCount
                sublinks {
                  id
                  sublinkCount
                  sublinks {
                    id
                    sublinkCount
                    sublinks {
                      id
                      sublinkCount
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
"""

# The loader's step 1 — "which of these ids have any child at all?" — is the
# only query that filters on ``parent_id IN (...)``. Matching on that clause
# rather than on the column name keeps the marker off the feed's own page query,
# which selects every column (parent_id included).
EXISTENCE_PROBE_MARKER = '"parent_id" IN ('

# Step 2 is one recursive CTE per subtree that survived the probe. The library
# emits ``WITH RECURSIVE`` for the ancestor computation, so the marker is the
# query's SHAPE rather than a column name that could appear elsewhere.
SUBTREE_MARKER = "WITH RECURSIVE"

# ``SocialMediaLink.url`` is a ``URLField`` (varchar(200)) and nothing in the
# database constrains it, so a ``sublinks`` assertion can only say which row it
# means by comparing URLs: they have to be distinct, and they have to fit.
_URL_PREFIX = "https://x.com/lrt/status/thread-"

# Process-wide rather than per-test, so two tests cannot mint the same URL even
# if the runner ever stops rolling each one back in its own transaction. The
# consequence is that URLs differ between runs — no assertion may hard-code one.
_URL_SEQ = itertools.count(1)


def unique_url(test_name: str) -> str:
    """A short, fixed-width, globally unique stand-in for a post permalink.

    Length is the trap. ``test_name`` is a variable-length string and the column
    is fixed at 200, so a token built out of it fails on whichever tests happen
    to have long names — the fixture breaks, not the code under test.

    The obvious way to reach for a "unique id" here is ``self.id``, and that is
    a trap of its own: on a ``TestCase`` ``id`` is not a row id, it is
    ``unittest.TestCase.id`` — a bound method whose ``str()`` is a ~180 character
    repr of the test instance, growing with the test's own method name. It reads
    exactly like a primary key, which is precisely why it keeps coming back.

    So the name is hashed down to 8 hex chars — kept only so that a URL printed
    in a failure still names the test that minted it — and a counter carries the
    uniqueness.
    """
    digest = hashlib.blake2b(test_name.encode(), digest_size=4).hexdigest()
    return f"{_URL_PREFIX}{digest}-{next(_URL_SEQ)}"


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


def reachable_urls(node: dict) -> set[str]:
    """Every link a client can walk to from ``node`` by following ``sublinks``.

    The recursive counterpart to ``sublinkCount``. Asserting the count against
    this set is what makes the two fields' agreement structural rather than
    numeric: a fixture change that hid a middle node, dropped a level or
    double-counted one fails HERE, not as a puzzling off-by-one somewhere.

    The walk stops where the query stopped selecting — the deepest ``sublinks``
    in the payload is the deepest one a client can ask this question about, and
    treating a missing key as "no children" rather than as an error keeps the
    helper usable at every level of the same selection.
    """
    urls = set()
    for child in node.get("sublinks", []):
        urls.add(child["url"])
        urls |= reachable_urls(child)
    return urls


class LinkHierarchyTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-link-hierarchy")

    def _url(self) -> str:
        # Unique per row so a ``sublinks`` URL assertion is unambiguous even
        # though only (socmed_account, post_id) is constrained in the DB.
        # Note there is deliberately NO ``self.id`` here — on a TestCase that is
        # ``unittest.TestCase.id``, a bound method, not a row id. See
        # ``unique_url`` and ``FixtureUrlTests`` below.
        return unique_url(self._testMethodName)

    def _link(self, parent=None, **overrides) -> SocialMediaLink:
        """A publicly-visible LIVE link unless the test says otherwise.

        LIVE + not automated is the only unconditionally public combination, so
        a test that forgets to set a status still exercises the visible path
        instead of silently testing the hidden one.

        ``position`` is passed through untouched: the library's auto-assign only
        fires on a falsy value, so an explicit one survives and is what the
        ordering tests use to disagree with ``occurred_at`` and with id order.
        """
        fields = {
            "url": self._url(),
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
        edges = result.data["publicSocialMediaLinks"]["edges"]
        return {int(e["node"]["id"]): e["node"] for e in edges}

    def _node(self, link: SocialMediaLink, query: str = FEED_QUERY) -> dict:
        nodes = self._feed_nodes(query)
        self.assertIn(link.id, nodes, msg=f"link {link.id} missing from the feed")
        return nodes[link.id]


class OccurredAtFieldTests(LinkHierarchyTestCase):
    def test_occurred_at_is_exposed_and_is_not_created(self):
        # The reason this field exists: the card shows when the thing HAPPENED.
        # If it ever fell back to ``created``, old reports would be relabelled
        # as new ones with nothing in the payload to notice.
        link = self._link(occurred_at=T1)
        self.assertNotEqual(link.occurred_at, link.created)

        node = self._node(link)

        self.assertEqual(node["occurredAt"], "2026-09-20T10:00:00")

    def test_occurred_at_is_non_null(self):
        # NOT NULL on the model (a nullable column would sort NULLs last on a
        # DESC keyset scan instead of first), so the field takes no null branch.
        self.assertIsNotNone(self._node(self._link())["occurredAt"])

    def test_occurred_at_carries_no_utc_offset(self):
        # USE_TZ = False + TIME_ZONE Asia/Kuala_Lumpur: the stored value is naive
        # local wall time and must go out verbatim. An offset here means
        # something made it aware and reshifted it (MISTAKES.md 2026-09-26).
        self.assertEqual(
            self._node(self._link(occurred_at=T1))["occurredAt"],
            "2026-09-20T10:00:00",
        )

    def test_occurred_at_still_orders_the_feed_not_the_sublink_list(self):
        # The FEED is ``occurred_at DESC, id DESC``; ``sublinks`` is
        # ``position``. Created here so the two disagree: the later event is the
        # first sublink. If ``sublinks`` ever started following the feed's
        # ordering the sibling sequence G1's reorder mutation writes would be
        # cosmetic.
        root = self._link(occurred_at=T0)
        first = self._link(root, occurred_at=T3, position=10)
        second = self._link(root, occurred_at=T1, position=20)

        node = self._node(root)

        # Insertion order (id ASC) is second then first, the reverse of the
        # sibling sequence — so this list cannot have come from either by luck.
        self.assertLess(first.id, second.id)
        self.assertEqual(
            [c["url"] for c in node["sublinks"]],
            [first.url, second.url],
            msg="sublinks followed the event time instead of position",
        )


class ParentIdAndRootMarkerTests(LinkHierarchyTestCase):
    def test_parent_id_is_null_for_a_root(self):
        root = self._link(occurred_at=T0)
        self._link(root, occurred_at=T1)

        self.assertIsNone(self._node(root)["parentId"])

    def test_parent_id_on_a_sublink_is_its_parents_id(self):
        # NOT the root's id. Under the depth-1 design ``threadId`` named the root
        # from anywhere in the thread; here ``parentId`` is strictly the immediate
        # parent, which is what makes it a walk UP one level rather than a jump
        # to the top. A client that wants the root follows it repeatedly.
        root = self._link(occurred_at=T0)
        child = self._link(root, occurred_at=T1)
        grandchild = self._link(child, occurred_at=T2)

        self.assertEqual(self._node(child)["parentId"], str(root.id))
        self.assertEqual(self._node(grandchild)["parentId"], str(child.id))

    def test_is_thread_root_is_true_for_a_root(self):
        root = self._link(occurred_at=T0)
        self._link(root, occurred_at=T1)

        self.assertTrue(self._node(root)["isThreadRoot"])

    def test_is_thread_root_is_false_for_every_sublink(self):
        root = self._link(occurred_at=T0)
        child = self._link(root, occurred_at=T1)
        grandchild = self._link(child, occurred_at=T2)

        nodes = self._feed_nodes()

        self.assertFalse(nodes[child.id]["isThreadRoot"])
        self.assertFalse(nodes[grandchild.id]["isThreadRoot"])

    def test_is_thread_root_is_also_true_for_a_plain_ungrouped_link(self):
        # ⚠️ THE TRAP THIS FIELD EXISTS ALONG WITH. ``isThreadRoot`` is
        # ``parentId is None``, and a link with no parent is a root in exactly
        # the sense a thread root is — an ungrouped link is a conversation of
        # one. So the field cannot answer "does this link have a group to
        # expand?"; the client must gate the chip on ``sublinkCount > 0`` /
        # ``sublinks.length > 0``. Asserted here so nobody "fixes" the field into
        # a has-sublinks marker and breaks every ungrouped card.
        lonely = self._link(occurred_at=T0)

        node = self._node(lonely)

        self.assertIsNone(node["parentId"])
        self.assertTrue(node["isThreadRoot"])
        self.assertEqual(node["sublinkCount"], 0)
        self.assertEqual(node["sublinks"], [])

    def test_a_root_with_children_is_distinguishable_only_by_the_count(self):
        # The affirmative half of the trap: root-with-children and root-with-none
        # are indistinguishable through ``parentId``/``isThreadRoot`` and
        # separated only by the count. Both render through the same component, so
        # this is exactly the decision the client has to get right.
        with_children = self._link(occurred_at=T0)
        self._link(with_children, occurred_at=T1)
        without = self._link(occurred_at=T0)

        nodes = self._feed_nodes()

        self.assertTrue(nodes[with_children.id]["isThreadRoot"])
        self.assertTrue(nodes[without.id]["isThreadRoot"])
        self.assertIsNone(nodes[with_children.id]["parentId"])
        self.assertIsNone(nodes[without.id]["parentId"])
        self.assertGreater(nodes[with_children.id]["sublinkCount"], 0)
        self.assertEqual(nodes[without.id]["sublinkCount"], 0)


class SublinkCountTests(LinkHierarchyTestCase):
    def _three_level_tree(self):
        """``root -> (a -> a1, b)`` — four rows across three levels.

        Built with explicit positions so the sibling order is unambiguous and
        independent of insertion order.
        """
        root = self._link(occurred_at=T0)
        a = self._link(root, occurred_at=T1, position=10)
        b = self._link(root, occurred_at=T2, position=20)
        a1 = self._link(a, occurred_at=T3, position=10)
        return root, a, b, a1

    def test_a_childless_link_reports_zero(self):
        leaf = self._link(occurred_at=T0)

        node = self._node(leaf)

        # Not 1: the depth-1 design's ``threadSize`` counted the row itself, so a
        # lone link read 1 and a root read n+1. Here the count is descendants
        # only, which is the quantity the chip shows and the thing a client can
        # compare against the length of the list it fetched.
        self.assertEqual(node["sublinkCount"], 0)
        self.assertEqual(node["sublinks"], [])

    def test_the_count_includes_descendants_at_every_depth(self):
        root, _a, _b, _a1 = self._three_level_tree()

        node = self._node(root)

        # a, b (direct) + a1 (grandchild) = 3. A depth-1 implementation reads 2
        # here, so this is the assertion that the nesting is real.
        self.assertEqual(node["sublinkCount"], 3)
        self.assertEqual(len(node["sublinks"]), 2)

    def test_a_sublink_counts_its_own_descendants_not_the_whole_tree(self):
        # THE correction to the old contract. A member reports ``threadSize`` for
        # the whole thread, because it could not have anything of its own; a
        # sublink here reports only what hangs below IT, so a client must walk to
        # the root for the conversation total. Summing these per level (which is
        # the tempting recursive move) is how a client would over-count by the
        # depth of the tree.
        root, a, b, a1 = self._three_level_tree()

        nodes = self._feed_nodes()

        self.assertEqual(nodes[root.id]["sublinkCount"], 3)
        self.assertEqual(nodes[a.id]["sublinkCount"], 1)
        self.assertEqual(nodes[b.id]["sublinkCount"], 0)
        self.assertEqual(nodes[a1.id]["sublinkCount"], 0)

    def test_two_trees_are_independent(self):
        root_a = self._link(occurred_at=T0)
        a1 = self._link(root_a, occurred_at=T1, position=10)
        a2 = self._link(root_a, occurred_at=T2, position=20)
        root_b = self._link(occurred_at=T0)
        b1 = self._link(root_b, occurred_at=T1, position=10)

        nodes = self._feed_nodes()

        self.assertEqual(nodes[root_a.id]["sublinkCount"], 2)
        self.assertEqual(nodes[root_b.id]["sublinkCount"], 1)
        self.assertEqual(
            [c["url"] for c in nodes[root_a.id]["sublinks"]], [a1.url, a2.url]
        )
        self.assertEqual([c["url"] for c in nodes[root_b.id]["sublinks"]], [b1.url])


class OverDeepSelectionTests(LinkHierarchyTestCase):
    """The read side is NOT bounded by ``MAX_THREAD_DEPTH``, and that is a promise.

    ``MAX_THREAD_DEPTH`` is a WRITE-side cap, so nothing stops a client asking for
    more levels of ``sublinks`` than the deepest stored tree. Two docstrings
    promise what happens then — the ``sublinks`` field ("a deeper selection than
    we store simply comes back empty, never wrong") and
    ``social_link_threads.MAX_THREAD_DEPTH`` ("the levels it asked for and we do
    not have simply come back empty") — and a promise about the read contract is
    load-bearing for a client, so it is executed here rather than trusted. A
    future read-side clamp, a validation error, or a depth cap on the resolver
    would each break a client that works today, and this is the test that says
    so.
    """

    def test_a_selection_deeper_than_the_store_returns_empty_levels_not_an_error(self):
        # The requirement is "empty, never wrong": the deepest stored level must
        # come back with an EMPTY ``sublinks`` list and the rows above it
        # unaffected. A read-side clamp that invented a placeholder row, or one
        # that dropped the level without an empty list, would pass a weaker
        # assertion and both would be wrong.
        # MAX_THREAD_DEPTH levels deep: root (depth 0) .. the cap. Built
        # directly rather than through the grouping service, because the point is
        # the shape the READ side answers for a tree already at the cap.
        chain = [self._link(occurred_at=T0)]
        for depth in range(1, MAX_THREAD_DEPTH + 1):
            chain.append(self._link(chain[-1], occurred_at=T0, position=depth * 10))
        root = chain[0]
        self.assertEqual(len(chain), MAX_THREAD_DEPTH + 1)

        # One more ``sublinks`` level than there is data for: the deepest
        # selection is a leaf asking for children it does not have.
        result = execute_graphql(OVER_DEEP_QUERY, {"first": 50})
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")

        nodes = {
            edge["node"]["id"]: edge["node"]
            for edge in result.data["publicSocialMediaLinks"]["edges"]
        }
        self.assertIn(str(root.id), nodes)

        # Every stored level is present, each ``sublinkCount`` is what is really
        # below it, and the DEEPEST stored link — the one at the cap — reports an
        # empty list rather than an error or a fabricated child.
        for depth, link in enumerate(chain):
            self.assertIn(str(link.id), nodes, msg=f"level {depth} missing")
            current = nodes[str(link.id)]
            remaining = len(chain) - depth - 1
            self.assertEqual(
                current["sublinkCount"],
                remaining,
                msg=f"wrong sublinkCount at depth {depth}",
            )
            if remaining:
                self.assertEqual(
                    [child["id"] for child in current["sublinks"]],
                    [str(chain[depth + 1].id)],
                    msg=f"wrong child at depth {depth}",
                )
            else:
                self.assertEqual(
                    current["sublinks"],
                    [],
                    msg=(
                        f"the deepest stored link (depth {MAX_THREAD_DEPTH}) "
                        "returned rows it does not have"
                    ),
                )


class CountAndListAgreeTests(LinkHierarchyTestCase):
    def test_the_count_equals_the_rows_reachable_through_sublinks(self):
        # THE structural assertion. Both fields read one loader result, so this
        # must hold for any fixture — it is not a numeric coincidence that a
        # bigger or deeper tree would break. If a future change gave
        # ``sublinkCount`` its own count query (or counted rows the nesting
        # cannot reach), this fails here instead of in the UI.
        root = self._link(occurred_at=T0)
        a = self._link(root, occurred_at=T1, position=10)
        b = self._link(root, occurred_at=T2, position=20)
        a1 = self._link(a, occurred_at=T3, position=10)
        a1a = self._link(a1, occurred_at=T0, position=10)
        self._link(b, occurred_at=T1, position=20)

        nodes = self._feed_nodes(DEEP_QUERY)

        for link in (root, a, b, a1, a1a):
            node = nodes[link.id]
            self.assertEqual(
                node["sublinkCount"],
                len(reachable_urls(node)),
                msg=f"count/list disagreement on link {link.id}: "
                f"{node['sublinkCount']} vs {sorted(reachable_urls(node))}",
            )
        # And the fixture really is 5 deep, so the equality above is not the
        # vacuous 0 == 0 that a childless link would give.
        self.assertEqual(nodes[root.id]["sublinkCount"], 5)

    def test_sublinks_holds_direct_children_only_never_the_parent(self):
        root = self._link(occurred_at=T0)
        a = self._link(root, occurred_at=T1, position=10)
        b = self._link(root, occurred_at=T2, position=20)
        self._link(a, occurred_at=T3, position=10)

        node = self._node(root)

        self.assertEqual([c["url"] for c in node["sublinks"]], [a.url, b.url])
        self.assertNotIn(root.url, [c["url"] for c in node["sublinks"]])

    def test_a_hidden_middle_node_is_excluded_from_the_count_too(self):
        # root -> hidden -> visible grandchild. The grandchild is itself public,
        # but no client can reach it: the node it hangs off is not in the list
        # the client walks. Counting it would put a "1 link" chip on the card
        # that expands to nothing — the exact badge/list divergence the shared
        # loader read exists to prevent. So the whole suppressed branch drops out
        # of both fields.
        root = self._link(occurred_at=T0)
        hidden = self._link(
            root,
            occurred_at=T1,
            position=10,
            status=SocialMediaLinkStatus.HIDDEN,
        )
        orphan = self._link(hidden, occurred_at=T2, position=10)
        visible = self._link(root, occurred_at=T3, position=20)

        nodes = self._feed_nodes()

        self.assertEqual(nodes[root.id]["sublinkCount"], 1)
        self.assertEqual([c["url"] for c in nodes[root.id]["sublinks"]], [visible.url])
        # …and the orphan is still in the tree, it is only unreachable through
        # the nesting: it has its own entry on the flat feed, as its own root of
        # the branch.
        self.assertNotIn(hidden.url, [c["url"] for c in nodes[root.id]["sublinks"]])
        self.assertIn(orphan.id, nodes)


class SublinkOrderingTests(LinkHierarchyTestCase):
    def test_sublinks_follow_position_not_id_and_not_occurred_at(self):
        # All three candidate orders are made to disagree at once:
        #
        #   position  : b (10), a (20)
        #   id ASC    : a, b      (a was created first)
        #   occurred  : a (T1), b (T3)
        #
        # so a resolver that sorted by either of the others — or forgot to sort
        # and inherited insertion order — fails. ``position`` is the sequence
        # ``reorderSocialMediaLinks`` writes, so this is the order the
        # move-up/move-down controls actually produce.
        root = self._link(occurred_at=T0)
        a = self._link(root, occurred_at=T1, position=20)
        b = self._link(root, occurred_at=T3, position=10)

        node = self._node(root)

        self.assertLess(a.id, b.id)
        self.assertEqual([c["url"] for c in node["sublinks"]], [b.url, a.url])

    def test_position_order_holds_at_a_non_root_level(self):
        # ``Meta.ordering = ["position"]`` is GLOBAL, so it is only a sibling
        # order when the queryset is already narrowed to one parent (M1 pins
        # that). The loader therefore sorts per parent in Python; if it leaned on
        # the model default the depth-2 sibling order would be a coincidence of
        # whatever numbers the auto-assign happened to hand out.
        root = self._link(occurred_at=T0)
        child = self._link(root, occurred_at=T1, position=10)
        deep_first = self._link(child, occurred_at=T2, position=10)
        deep_second = self._link(child, occurred_at=T3, position=20)
        # Give a row of the OTHER branch a lower position than both, so a global
        # sort would interleave the levels.
        self._link(root, occurred_at=T0, position=5)

        node = self._feed_nodes(DEEP_QUERY)[child.id]

        self.assertEqual(
            [c["url"] for c in node["sublinks"]], [deep_first.url, deep_second.url]
        )

    def test_siblings_sharing_a_position_come_back_in_id_order(self):
        # ``position`` is gap-spaced but not unique (nothing constrains it), so
        # the sort needs a tie-break or Postgres may return same-position rows in
        # any order and a client would see its list reorder between page loads.
        root = self._link(occurred_at=T0)
        first = self._link(root, occurred_at=T1, position=10)
        second = self._link(root, occurred_at=T2, position=10)

        node = self._node(root)

        self.assertLess(first.id, second.id)
        self.assertEqual(
            [c["id"] for c in node["sublinks"]], [str(first.id), str(second.id)]
        )


class VisibilityGatingTests(LinkHierarchyTestCase):
    """The moderation rule must apply at every depth, not just to the root row.

    A root is filtered by the feed's own ``.exclude(...)`` pair. Its sublinks are
    reached through ``sublinks``, which no queryset-level gate touches — so
    without the per-row predicate a hidden link's URL and title come straight out
    of a public feed through a nested field, at whatever depth it was hidden.
    """

    def test_a_hidden_sublink_is_excluded_from_sublinks(self):
        root = self._link(occurred_at=T0)
        visible = self._link(root, occurred_at=T1, position=10)
        hidden = self._link(
            root,
            occurred_at=T2,
            position=20,
            status=SocialMediaLinkStatus.HIDDEN,
        )

        urls = [c["url"] for c in self._node(root)["sublinks"]]

        self.assertEqual(urls, [visible.url])
        self.assertNotIn(hidden.url, urls)

    def test_a_hidden_sublink_does_not_inflate_the_count(self):
        root = self._link(occurred_at=T0)
        self._link(root, occurred_at=T1, position=10)
        self._link(
            root,
            occurred_at=T2,
            position=20,
            status=SocialMediaLinkStatus.HIDDEN,
        )

        node = self._node(root)

        # Attached but not openable: 1, not 2.
        self.assertEqual(node["sublinkCount"], 1)

    def test_a_hidden_grandchild_is_excluded_from_the_roots_count(self):
        # The depth that did not exist before: the root's count must survive a
        # hidden row two levels down, or the chip advertises a link the expansion
        # cannot show.
        root = self._link(occurred_at=T0)
        child = self._link(root, occurred_at=T1, position=10)
        self._link(child, occurred_at=T2, position=10)
        self._link(
            child,
            occurred_at=T3,
            position=20,
            status=SocialMediaLinkStatus.HIDDEN,
        )

        nodes = self._feed_nodes()

        self.assertEqual(nodes[root.id]["sublinkCount"], 2)
        self.assertEqual(nodes[child.id]["sublinkCount"], 1)

    def test_an_unapproved_automated_sublink_is_excluded(self):
        # Same second gate as the feed's own filter: an official post nobody has
        # approved is not public, sublink or not.
        root = self._link(occurred_at=T0)
        visible = self._link(root, occurred_at=T1, position=10)
        pending = self._link(
            root,
            occurred_at=T2,
            position=20,
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
            is_automated=True,
        )

        node = self._node(root)

        self.assertEqual([c["url"] for c in node["sublinks"]], [visible.url])
        self.assertEqual(node["sublinkCount"], 1)
        self.assertNotIn(pending.url, [c["url"] for c in node["sublinks"]])

    def test_a_hidden_root_of_a_branch_does_not_leak_its_sublinks(self):
        # The root itself is filtered by the feed's own gate; this only pins that
        # the two layers compose (a hidden root has no page to hang a chip off)
        # instead of one of them resurrecting the other.
        root = self._link(occurred_at=T0, status=SocialMediaLinkStatus.HIDDEN)
        member = self._link(root, occurred_at=T1, position=10)

        nodes = self._feed_nodes()

        self.assertNotIn(root.id, nodes)
        # The member is a public row in its own right and is promoted on the feed
        # as such; it must not arrive carrying the hidden root's branch.
        self.assertEqual(nodes[member.id]["sublinks"], [])
        self.assertEqual(nodes[member.id]["sublinkCount"], 0)

    def test_a_community_sublink_awaiting_approval_is_still_public(self):
        # Scoped to ``is_automated`` on purpose: a hand-submitted report awaiting
        # review keeps surfacing with its pending pill. Gating it here would hide
        # community reports inside a group — a moderation regression, not a
        # safety win.
        root = self._link(occurred_at=T0)
        pending = self._link(
            root,
            occurred_at=T1,
            position=10,
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
        )

        node = self._node(root)

        self.assertEqual(node["sublinkCount"], 1)
        self.assertEqual([c["url"] for c in node["sublinks"]], [pending.url])

    def test_an_approved_automated_sublink_is_public(self):
        root = self._link(occurred_at=T0)
        official = self._link(
            root,
            occurred_at=T1,
            position=10,
            is_automated=True,
            status=SocialMediaLinkStatus.LIVE,
        )

        node = self._node(root)

        self.assertEqual(node["sublinkCount"], 1)
        self.assertEqual([c["url"] for c in node["sublinks"]], [official.url])


class LoaderUnitTests(LinkHierarchyTestCase):
    """``sublink_subtrees`` on its own, without GraphQL in the way.

    The loader's raw contract is what lets ``sublinkCount`` derive the chip from
    the very list ``sublinks`` returns, so the flat shape, the depth coverage and
    the positional alignment are pinned here (the GraphQL-level tests above cover
    the visibility filtering applied on top). These call the load function
    directly — a single key list IS a single batch, which is what DataLoader
    hands it anyway.
    """

    def test_a_childless_key_returns_an_empty_list(self):
        lonely = self._link()

        result = async_to_sync(batch_load_sublink_subtrees)([lonely.id])

        # Every key gets a list, never a missing key: a resolver indexing the
        # result positionally would otherwise get an IndexError on the most
        # common case in the feed (a plain ungrouped link).
        self.assertEqual(result, [[]])

    def test_a_key_comes_back_with_descendants_at_every_depth(self):
        root = self._link()
        child = self._link(root, position=10)
        grandchild = self._link(child, position=10)

        result = async_to_sync(batch_load_sublink_subtrees)([root.id])

        flat = result[0]
        # Descendants only — never the key itself, which the caller already has.
        self.assertNotIn(root.id, [row.id for row in flat])
        self.assertEqual({row.id for row in flat}, {child.id, grandchild.id})
        # Depth-first with siblings in position order, which is what lets a field
        # filter ``parent_id == self.id`` and inherit the order it needs.
        self.assertEqual([row.id for row in flat], [child.id, grandchild.id])

    def test_the_result_is_aligned_to_the_keys_including_duplicates(self):
        # Positional alignment and duplicate-safety live HERE: every key must get
        # a list back (empty for a childless link) and a repeated key must be
        # answered at its own position rather than merged away. DataLoader caches
        # per key so a duplicate never reaches the load function through the
        # normal path — which is exactly why this calls it directly.
        populated = self._link()
        child = self._link(populated, position=10)
        self._link(populated, position=20)
        empty = self._link()
        keys = [populated.id, empty.id, populated.id]

        result = async_to_sync(batch_load_sublink_subtrees)(keys)

        self.assertEqual([len(group) for group in result], [2, 0, 2])
        self.assertEqual([row.id for row in result[0]], [child.id, result[0][1].id])
        self.assertEqual(result[0], result[2])
        # The empty key is in the middle, so an implementation that built the
        # answer by filtering a flat list rather than by key would drop it.
        self.assertEqual(result[1], [])

    def test_a_childless_key_costs_one_query_and_no_subtree_fetch(self):
        # The existence probe is the whole reason a childless key — the common
        # case on a feed page — does not pay for a recursive CTE it cannot use.
        lonely = self._link()

        with CaptureQueriesContext(connection) as ctx:
            result = async_to_sync(batch_load_sublink_subtrees)([lonely.id])

        self.assertEqual(result, [[]])
        self.assertEqual(len(ctx.captured_queries), 1, msg=_sql_dump(ctx))
        self.assertFalse(
            any(SUBTREE_MARKER in q["sql"] for q in ctx.captured_queries),
            msg="a childless key ran a subtree query:\n" + _sql_dump(ctx),
        )

    def test_one_key_costs_one_subtree_query_however_deep_the_tree_is(self):
        # ⚠️ THE CLAIM THIS LOADER EXISTS FOR. ``node.children`` is a plain
        # ``RelatedManager``, so a tree walked level by level costs one query per
        # level: four levels would need four queries for the answer this fetches
        # in one. The bound is asserted per key rather than per page, so no
        # amount of unrelated schema traffic can hide a regression here.
        root = self._link()
        current = root
        chain = []
        for _ in range(5):
            current = self._link(current, position=10)
            chain.append(current)

        with CaptureQueriesContext(connection) as ctx:
            result = async_to_sync(batch_load_sublink_subtrees)([root.id])

        self.assertEqual([row.id for row in result[0]], [row.id for row in chain])
        self.assertEqual(len(ctx.captured_queries), 2, msg=_sql_dump(ctx))
        self.assertEqual(
            sum(1 for q in ctx.captured_queries if SUBTREE_MARKER in q["sql"]),
            1,
            msg="the subtree was fetched level by level:\n" + _sql_dump(ctx),
        )

    def test_the_probe_is_one_query_for_the_whole_batch(self):
        # Step 1 must not fan out per key: that would just move the N+1 one
        # level down, and the childless short-circuit would cost a query each.
        keys = [self._link().id for _ in range(4)]
        root = self._link()
        self._link(root, position=10)
        keys.append(root.id)

        with CaptureQueriesContext(connection) as ctx:
            async_to_sync(batch_load_sublink_subtrees)(keys)

        probes = [q for q in ctx.captured_queries if EXISTENCE_PROBE_MARKER in q["sql"]]
        self.assertEqual(len(probes), 1, msg=_sql_dump(ctx))
        # Every requested id, threaded or not, in that one statement.
        self.assertIn(str(root.id), probes[0]["sql"])


class LoaderBatchingTests(LinkHierarchyTestCase):
    """Prove the loader batches. That is the reason it exists.

    Without it, one page of rows selecting ``sublinks`` costs one child query per
    row (and ``sublinkCount``, reading the same loader, would double it): the
    optimizer cannot see a manual re-fetch, so nothing merges them for us. The
    assertions below pin the EXACT shape — one existence probe for the batch,
    one recursive CTE per key that has children — so the bound cannot be met by
    an implementation that happens to be cheap on this fixture.
    """

    ROOT_COUNT = 10
    CHILDREN_PER_ROOT = 2
    #: One ungrouped link, so the "no children" branch rides in the same batch
    #: and the probe is proved to cover keys on both sides.
    LONELY_COUNT = 2

    # Fixture: ROOT_COUNT roots x (CHILDREN_PER_ROOT children x 1 grandchild).
    # Three levels deep, so a per-level implementation costs more than a per-row
    # one and the "one query per subtree, not per level" claim is tested at the
    # depth where it is a claim at all.
    def setUp(self):
        super().setUp()
        self.roots = []
        for _ in range(self.ROOT_COUNT):
            root = self._link(occurred_at=T0)
            for _ in range(self.CHILDREN_PER_ROOT):
                child = self._link(root, occurred_at=T1, position=10)
                self._link(child, occurred_at=T2, position=10)
            self.roots.append(root)
        self.lonely = [self._link(occurred_at=T0) for _ in range(self.LONELY_COUNT)]

    @property
    def _rows(self) -> int:
        return self.ROOT_COUNT * (1 + self.CHILDREN_PER_ROOT * 2) + self.LONELY_COUNT

    @property
    def _threaded_keys(self) -> int:
        """Keys on the page that have at least one child.

        ``FEED_QUERY`` selects the hierarchy one level deep, so the loader keys
        are exactly the rows on the page — but only the roots and the children
        have children of their own.
        """
        return self.ROOT_COUNT + self.ROOT_COUNT * self.CHILDREN_PER_ROOT

    def _run(self):
        with CaptureQueriesContext(connection) as ctx:
            result = execute_graphql(FEED_QUERY, variables={"first": 100})
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return ctx

    def test_the_batch_is_one_probe_plus_one_subtree_query_per_threaded_row(self):
        ctx = self._run()

        probes = [q for q in ctx.captured_queries if EXISTENCE_PROBE_MARKER in q["sql"]]
        subtrees = [q for q in ctx.captured_queries if SUBTREE_MARKER in q["sql"]]

        self.assertEqual(len(probes), 1, msg=_sql_dump(ctx))
        self.assertEqual(
            len(subtrees),
            self._threaded_keys,
            msg=(
                f"{len(subtrees)} subtree queries for {self._threaded_keys} threaded "
                f"rows ({self._rows} on the page) — expected one per threaded key:\n"
                + _sql_dump(ctx)
            ),
        )

    def test_a_page_does_not_query_per_row_for_the_hierarchy_fields(self):
        # The regression this guards against in numbers: a naive
        # ``filter(parent_id=self.id)`` per row is ``self._rows`` queries, and
        # ``node.children`` per level is worse. The bound below is the measured
        # total for this shape, so a fan-out fails it loudly.
        ctx = self._run()

        # 2 for the feed itself (totalCount + page), 1 probe, 1 per threaded key.
        expected = 2 + 1 + self._threaded_keys
        self.assertLessEqual(
            len(ctx.captured_queries),
            expected,
            msg=(
                f"{len(ctx.captured_queries)} queries for {self._rows} rows — the "
                f"hierarchy fields are fanning out per row:\n" + _sql_dump(ctx)
            ),
        )

    def test_the_count_and_the_list_share_one_fetch(self):
        # Both fields read the same loader, which caches per request, so asking
        # for both is still ONE subtree query per key — and the chip is
        # structurally unable to drift from the list it labels. Without the
        # shared read this would be 2 x the count above.
        ctx = self._run()

        subtrees = [q for q in ctx.captured_queries if SUBTREE_MARKER in q["sql"]]

        self.assertEqual(len(subtrees), self._threaded_keys, msg=_sql_dump(ctx))

    def test_the_probe_covers_every_row_on_the_page_threaded_or_not(self):
        ctx = self._run()

        probes = [q for q in ctx.captured_queries if EXISTENCE_PROBE_MARKER in q["sql"]]

        self.assertEqual(len(probes), 1, msg=_sql_dump(ctx))
        probe_sql = probes[0]["sql"]
        for link in [*self.roots, *self.lonely]:
            self.assertIn(str(link.id), probe_sql)


class FixtureUrlTests(LinkHierarchyTestCase):
    """Guard the ``_link()`` fixture URL against the landmine it used to sit on.

    ``_url()`` used to interpolate ``self.id``, which on a ``TestCase`` is
    ``unittest.TestCase.id`` — a bound method, not a primary key. Stringified it
    is a ~180 character repr whose length tracks the test's own method name, so
    whether it overflowed ``SocialMediaLink.url`` (varchar(200)) was settled by
    naming alone: 11 of this file's tests blew the column purely because their
    names described themselves thoroughly, and the rest passed by accident — two
    characters of headroom was all that separated them. A failure that points at
    psycopg2 rather than at the helper that caused it is a failure worth a guard
    instead of a comment.

    These go through ``_url()`` itself rather than through ``unique_url``, so the
    thing being guarded is the code the other tests actually call. They pin the
    two properties it owes its callers: the URL fits the column whatever the test
    is called, and no two rows share one.
    """

    # Read off the model rather than hard-coded, so the bound cannot drift away
    # from the column the way the old token did.
    URL_LIMIT = SocialMediaLink._meta.get_field("url").max_length

    def test_the_url_length_does_not_depend_on_how_long_the_test_name_is(self):
        # ``_testMethodName`` is a plain attribute and ``_url()`` reads it, so
        # renaming this test mid-run is a faithful way to ask the real question:
        # does the token grow with the name? A name long enough to overflow
        # varchar(200) on its own must still produce a URL that fits — and, since
        # the name only ever feeds the digest, must not change the length at all.
        # (Each test gets a fresh instance, so the rename cannot leak.)
        before = self._url()
        self._testMethodName = "test_" + "a_rather_long_test_name" * 40
        after = self._url()
        # Restored before the assertions, so a failure is reported under this
        # test's own name instead of the 965-character one used as input.
        self._testMethodName = (
            "test_the_url_length_does_not_depend_on_how_long_the_test_name_is"
        )

        self.assertEqual(
            len(after),
            len(before),
            msg=f"{len(before)} -> {len(after)} chars: {after}",
        )
        self.assertLess(
            len(after),
            self.URL_LIMIT,
            msg=f"{len(after)} chars for a {self.URL_LIMIT}-char column: {after}",
        )

    def test_the_url_has_room_to_spare_against_the_column(self):
        # A deliberately verbose test name: under the old implementation this
        # class sat within two characters of the limit, so renaming anything here
        # was enough to turn a green file red. Half the column leaves the margin
        # as a number rather than a hunch.
        url = self._url()

        self.assertLess(
            len(url),
            self.URL_LIMIT // 2,
            msg=(
                f"{len(url)} chars for a {self.URL_LIMIT}-char column: {url}\n"
                "the token is no longer fixed-width — something variable-length "
                "(the test name? self.id?) leaked back into it"
            ),
        )

    def test_every_minted_url_is_distinct(self):
        # ``sublinks`` assertions identify a row by its URL and nothing else, so a
        # collision lets one row silently stand in for another. 500 is well past
        # the ~100 rows any single test here creates, because the guarantee has to
        # hold across the process and not merely per test.
        urls = [self._url() for _ in range(500)]

        self.assertEqual(len(set(urls)), len(urls))

    def test_the_url_still_names_the_test_that_minted_it(self):
        # Same test, successive rows: only the counter moves, so the digest part
        # is what makes a URL printed in a failure trace back to its test. A
        # fully random URL would be just as unique and name nothing.
        first, second = self._url(), self._url()

        self.assertNotEqual(first, second)
        self.assertEqual(first.rsplit("-", 1)[0], second.rsplit("-", 1)[0])


def _sql_dump(ctx: CaptureQueriesContext) -> str:
    """The captured statements, one per line, for a failure message.

    Query-count assertions here fail on a shape, not on a value, so the message
    has to show the shape: a bare "expected 12, got 54" leaves the reader to
    guess which of the four fan-outs produced the extra forty.
    """
    return "\n".join(f"--- {q['sql'][:300]}" for q in ctx.captured_queries)
