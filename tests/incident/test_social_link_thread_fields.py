"""Thread fields on ``SocialMediaLinkScalar`` — the public read contract.

``threadId`` / ``isThreadRoot`` / ``threadSize`` / ``threadLinks`` are what the
home feed's thread UI renders, and they have two properties worth pinning:

1. **They count what a visitor could actually open.** ``threadSize`` is the
   number on the "N links" badge and ``threadLinks`` is what the badge expands
   to. If a HIDDEN member — or an unapproved automated capture — counted in one
   but not the other, the public feed advertises a link that leads nowhere; and
   if a hidden member leaked into ``threadLinks`` at all, the feed's own
   ``.exclude(status=HIDDEN)`` gate would be bypassed through a side door, since
   members are reached by the loader, not by that queryset. Both fields
   therefore filter with the shared predicate
   (``incident.services.social_link_visibility``) rather than a second copy.

2. **They batch.** A page of rows asking for ``threadLinks`` must not issue a
   query per row. The loaders exist purely for that, so the batching is asserted
   here with ``CaptureQueriesContext`` rather than left to a comment.

Plus the shape facts the frontend depends on: ``threadId`` is null on a root, a
plain unthreaded link is itself a degenerate one-member thread (``isThreadRoot``
true, ``threadSize`` 1, ``threadLinks`` empty), and members come back
oldest-first with ``id ASC`` breaking ``occurred_at`` ties.

Runs under plain ``django.test.TestCase`` + ``asgiref.sync.async_to_sync`` (the
GraphQL schema is async) and deliberately does NOT import pytest: pytest is not
installed in the app image, so a pytest-based file here is uncollectable dead
code. Every query goes through the REAL schema — the loader plumbing only
proves itself inside GraphQL execution, where the fields are actually resolved.
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
from incident.schema.loaders import batch_load_thread_members
from rosak.context import ContextLoaders
from rosak.schema import schema

# Fixed, distinct instants so ``occurred_at ASC`` ordering is distinguishable
# from insertion order (ids ascending) — otherwise a DESC-ordering regression
# would still pass.
T0 = dt.datetime(2026, 9, 20, 9, 0, 0)
T1 = dt.datetime(2026, 9, 20, 10, 0, 0)
T2 = dt.datetime(2026, 9, 20, 11, 0, 0)
T3 = dt.datetime(2026, 9, 20, 12, 0, 0)

# ``first`` is generous so the whole fixture comes back on one page: the batching
# assertion is about queries-per-row, not about pagination.
FEED_QUERY = """
    query($first: Int!) {
      publicSocialMediaLinks(first: $first) {
        edges {
          node {
            id
            url
            occurredAt
            threadId
            isThreadRoot
            threadSize
            threadLinks {
              id
              url
              occurredAt
            }
          }
        }
      }
    }
"""

# A batched member fetch is the ONLY query that filters on ``thread_id IN (...)``.
# Matching on that clause rather than on the column name keeps this off the
# feed's own page query, which selects every column (thread_id included).
MEMBER_BATCH_MARKER = '"thread_id" IN ('

# ``SocialMediaLink.url`` is a ``URLField`` (varchar(200)) and nothing in the
# database constrains it, so a ``threadLinks`` assertion can only say which row
# it means by comparing URLs: they have to be distinct, and they have to fit.
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

    The obvious way to reach for a "unique id" here is ``self.id``, and that is a
    trap of its own: on a ``TestCase`` ``id`` is not a row id, it is
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


class ThreadFieldTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-thread-fields")

    def _url(self) -> str:
        # Unique per row so a ``threadLinks`` URL assertion is unambiguous even
        # though only (socmed_account, post_id) is constrained in the DB.
        # Note there is deliberately NO ``self.id`` here — on a TestCase that is
        # ``unittest.TestCase.id``, a bound method, not a row id. See
        # ``unique_url`` and ``FixtureUrlTests`` below.
        return unique_url(self._testMethodName)

    def _link(self, **overrides) -> SocialMediaLink:
        """A publicly-visible LIVE link unless the test says otherwise.

        LIVE + not automated is the only unconditionally public combination, so
        a test that forgets to set a status still exercises the visible path
        instead of silently testing the hidden one.
        """
        fields = {
            "url": self._url(),
            "user": self.user,
            "status": SocialMediaLinkStatus.LIVE,
        }
        fields.update(overrides)
        return SocialMediaLink.objects.create(**fields)

    def _feed_nodes(self, first: int = 100) -> dict:
        result = execute_graphql(FEED_QUERY, variables={"first": first})
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        edges = result.data["publicSocialMediaLinks"]["edges"]
        return {int(e["node"]["id"]): e["node"] for e in edges}

    def _node(self, link: SocialMediaLink) -> dict:
        nodes = self._feed_nodes()
        self.assertIn(link.id, nodes, msg=f"link {link.id} missing from the feed")
        return nodes[link.id]


class OccurredAtFieldTests(ThreadFieldTestCase):
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

    def test_occurred_at_distinguishes_members_that_were_created_together(self):
        # Members of one thread are submitted in a burst, so ``created`` is
        # nearly identical across them; ``occurred_at`` is what orders the
        # expanded thread. Without this the frontend has nothing to sort on.
        root = self._link(occurred_at=T0)
        early = self._link(occurred_at=T1, thread=root)
        late = self._link(occurred_at=T3, thread=root)

        members = self._node(root)["threadLinks"]

        self.assertEqual(
            [m["occurredAt"] for m in members],
            ["2026-09-20T10:00:00", "2026-09-20T12:00:00"],
        )
        self.assertLess(early.id, late.id)


class RootAndUnthreadedTests(ThreadFieldTestCase):
    def test_thread_id_is_null_for_a_root(self):
        root = self._link(occurred_at=T0)
        self._link(occurred_at=T1, thread=root)

        self.assertIsNone(self._node(root)["threadId"])

    def test_thread_id_on_a_member_is_the_roots_id(self):
        root = self._link(occurred_at=T0)
        member = self._link(occurred_at=T1, thread=root)

        self.assertEqual(self._node(member)["threadId"], str(root.id))

    def test_is_thread_root_is_true_for_a_root(self):
        root = self._link(occurred_at=T0)
        self._link(occurred_at=T1, thread=root)

        self.assertTrue(self._node(root)["isThreadRoot"])

    def test_is_thread_root_is_false_for_a_member(self):
        root = self._link(occurred_at=T0)
        member = self._link(occurred_at=T1, thread=root)

        self.assertFalse(self._node(member)["isThreadRoot"])

    def test_an_unthreaded_link_is_a_degenerate_one_member_thread(self):
        # ``isThreadRoot`` is ``thread_id is None``, which is true for a plain
        # link too. The client must therefore drive the "N links" badge off
        # threadSize/threadLinks rather than inventing a "0 links" state — the
        # collapsed feed renders every root through the same component.
        lonely = self._link(occurred_at=T0)

        node = self._node(lonely)

        self.assertIsNone(node["threadId"])
        self.assertTrue(node["isThreadRoot"])
        self.assertEqual(node["threadSize"], 1)
        self.assertEqual(node["threadLinks"], [])


class ThreadSizeAndLinksTests(ThreadFieldTestCase):
    def _three_member_thread(self):
        root = self._link(occurred_at=T0)
        m1 = self._link(occurred_at=T1, thread=root)
        m2 = self._link(occurred_at=T2, thread=root)
        m3 = self._link(occurred_at=T3, thread=root)
        return root, m1, m2, m3

    def test_a_three_member_thread_reports_four_including_the_root(self):
        root, *_ = self._three_member_thread()

        node = self._node(root)

        # Root + 3 members. An off-by-one here is invisible on a lone link (both
        # sides read 1), so it takes a real thread to catch.
        self.assertEqual(node["threadSize"], 4)
        self.assertEqual(len(node["threadLinks"]), 3)

    def test_thread_links_holds_members_only_and_never_the_root(self):
        root, m1, m2, m3 = self._three_member_thread()

        urls = [m["url"] for m in self._node(root)["threadLinks"]]

        self.assertEqual(len(urls), 3)
        self.assertNotIn(root.url, urls)
        self.assertEqual(set(urls), {m1.url, m2.url, m3.url})

    def test_thread_links_is_ordered_oldest_first_by_occurred_at(self):
        # Members are created in DESCENDING event order on purpose: insertion
        # order and event order disagree, so a resolver that forgot the sort (and
        # got insertion order by luck) is caught here.
        root = self._link(occurred_at=T0)
        late = self._link(occurred_at=T3, thread=root)
        early = self._link(occurred_at=T1, thread=root)
        middle = self._link(occurred_at=T2, thread=root)
        # late, early, middle — so id ASC says late/early/middle and
        # occurred_at ASC says early/middle/late.
        self.assertLess(late.id, early.id)
        self.assertLess(early.id, middle.id)

        members = self._node(root)["threadLinks"]

        self.assertEqual([m["url"] for m in members], [early.url, middle.url, late.url])
        self.assertEqual(
            [m["occurredAt"] for m in members],
            ["2026-09-20T10:00:00", "2026-09-20T11:00:00", "2026-09-20T12:00:00"],
        )

    def test_members_are_id_ascending_when_two_share_an_instant(self):
        # ``occurred_at`` alone is not a total order; without the ``id``
        # tie-break Postgres may return same-instant rows in any order, and a
        # client re-sorting by time alone would see a thread reorder itself
        # between two page loads.
        root = self._link(occurred_at=T0)
        first = self._link(occurred_at=T1, thread=root)
        second = self._link(occurred_at=T1, thread=root)
        self.assertLess(first.id, second.id)

        members = self._node(root)["threadLinks"]

        self.assertEqual([m["id"] for m in members], [str(first.id), str(second.id)])

    def test_a_member_reports_no_members_of_its_own(self):
        # Depth is exactly 1 by model invariant: nothing points at a member, so a
        # member's own threadLinks is empty rather than a copy of the thread. If
        # this ever came back non-empty the client would recurse forever.
        root, m1, *_ = self._three_member_thread()

        node = self._node(m1)

        self.assertEqual(node["threadSize"], 1)
        self.assertEqual(node["threadLinks"], [])

    def test_two_threads_are_independent(self):
        root_a = self._link(occurred_at=T0)
        root_b = self._link(occurred_at=T0)
        a_member = self._link(occurred_at=T1, thread=root_a)
        b1 = self._link(occurred_at=T1, thread=root_b)
        b2 = self._link(occurred_at=T2, thread=root_b)

        nodes = self._feed_nodes()

        self.assertEqual(
            [m["url"] for m in nodes[root_a.id]["threadLinks"]], [a_member.url]
        )
        self.assertEqual(
            {m["url"] for m in nodes[root_b.id]["threadLinks"]}, {b1.url, b2.url}
        )
        self.assertEqual(nodes[root_a.id]["threadSize"], 2)
        self.assertEqual(nodes[root_b.id]["threadSize"], 3)


class VisibilityGatingTests(ThreadFieldTestCase):
    """The moderation rule must apply to members, not just to the root row.

    A root is filtered by the feed's own ``.exclude(...)`` pair. Its members are
    reached through ``threadLinks``, which no queryset-level gate touches — so
    without the per-row predicate a hidden link's URL and title come straight
    out of a public feed through a nested field.
    """

    def test_a_hidden_member_is_excluded_from_thread_links(self):
        root = self._link(occurred_at=T0)
        visible = self._link(occurred_at=T1, thread=root)
        hidden = self._link(
            occurred_at=T2, thread=root, status=SocialMediaLinkStatus.HIDDEN
        )

        urls = [m["url"] for m in self._node(root)["threadLinks"]]

        self.assertEqual(urls, [visible.url])
        self.assertNotIn(hidden.url, urls)

    def test_a_hidden_member_does_not_inflate_thread_size(self):
        root = self._link(occurred_at=T0)
        self._link(occurred_at=T1, thread=root)
        self._link(occurred_at=T2, thread=root, status=SocialMediaLinkStatus.HIDDEN)

        node = self._node(root)

        # Root + 1 visible member. The hidden row is attached but not openable.
        self.assertEqual(node["threadSize"], 2)

    def test_an_unapproved_automated_member_is_excluded_from_thread_links(self):
        # Same second gate as the feed's own filter: an official post nobody has
        # approved is not public, member or not.
        root = self._link(occurred_at=T0)
        visible = self._link(occurred_at=T1, thread=root)
        pending = self._link(
            occurred_at=T2,
            thread=root,
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
            is_automated=True,
        )

        urls = [m["url"] for m in self._node(root)["threadLinks"]]

        self.assertEqual(urls, [visible.url])
        self.assertNotIn(pending.url, urls)

    def test_an_unapproved_automated_member_does_not_inflate_thread_size(self):
        root = self._link(occurred_at=T0)
        self._link(occurred_at=T1, thread=root)
        self._link(
            occurred_at=T2,
            thread=root,
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
            is_automated=True,
        )

        self.assertEqual(self._node(root)["threadSize"], 2)

    def test_a_hidden_member_of_a_fully_hidden_thread_does_not_leak_the_root(self):
        # The root itself is filtered by the feed's own gate; this only pins
        # that the two layers compose (a hidden root has no page to hang a
        # badge off) instead of one of them resurrecting the other.
        root = self._link(occurred_at=T0, status=SocialMediaLinkStatus.HIDDEN)
        member = self._link(occurred_at=T1, thread=root)

        nodes = self._feed_nodes()

        self.assertNotIn(root.id, nodes)
        self.assertEqual(nodes[member.id]["threadLinks"], [])

    def test_a_community_member_awaiting_approval_is_still_public(self):
        # Scoped to ``is_automated`` on purpose: a hand-submitted report awaiting
        # review keeps surfacing with its pending pill. Gating it here would hide
        # community reports inside a thread — a moderation regression, not a
        # safety win.
        root = self._link(occurred_at=T0)
        pending = self._link(
            occurred_at=T1, thread=root, status=SocialMediaLinkStatus.PENDING_APPROVAL
        )

        node = self._node(root)

        self.assertEqual(node["threadSize"], 2)
        self.assertEqual([m["url"] for m in node["threadLinks"]], [pending.url])

    def test_an_approved_automated_member_is_public(self):
        root = self._link(occurred_at=T0)
        official = self._link(
            occurred_at=T1,
            thread=root,
            is_automated=True,
            status=SocialMediaLinkStatus.LIVE,
        )

        node = self._node(root)

        self.assertEqual(node["threadSize"], 2)
        self.assertEqual([m["url"] for m in node["threadLinks"]], [official.url])


class LoaderUnitTests(ThreadFieldTestCase):
    """The ``thread_members`` loader on its own, without GraphQL in the way.

    The loader's raw contract is what lets ``threadSize`` derive the public badge
    from the very list ``threadLinks`` returns, so the unfiltered shape and the
    positional alignment are pinned here (the GraphQL-level tests above cover the
    visibility filtering applied on top). These call the load function directly (a
    single key list == a single batch, which is what DataLoader hands it anyway).
    """

    def test_thread_members_returns_empty_for_a_root_with_no_members(self):
        lonely = self._link()

        result = async_to_sync(batch_load_thread_members)([lonely.id])

        # Every key gets a list, never a missing key: a resolver indexing the
        # result positionally would otherwise get an IndexError on the most
        # common case in the feed (a plain unthreaded link).
        self.assertEqual(result, [[]])

    def test_thread_members_is_empty_for_a_member_as_a_key(self):
        # Depth 1 by invariant: nothing points at a member, so this is what
        # stops the client recursing if it ever asked a member for its thread.
        root = self._link()
        member = self._link(thread=root)

        result = async_to_sync(batch_load_thread_members)([member.id, root.id])

        self.assertEqual([m.id for group in result for m in group], [member.id])

    def test_thread_members_batches_a_mixed_key_list(self):
        # Positional alignment and duplicate-safety live HERE, not in a separate
        # count loader: every key must get a list back (empty for no members), and
        # a repeated key must be answered at its own position rather than merged.
        populated = self._link()
        self._link(thread=populated)
        empty = self._link()
        keys = [populated.id, empty.id, populated.id]

        result = async_to_sync(batch_load_thread_members)(keys)

        self.assertEqual([len(group) for group in result], [1, 0, 1])


class LoaderBatchingTests(ThreadFieldTestCase):
    """Prove the loader batches. That is the reason it exists.

    Without it, one page of rows selecting ``threadLinks`` costs one member query
    per row (and ``threadSize``, reading the same loader, would double it): the
    optimizer cannot see a manual re-fetch, so nothing merges them for us. The
    budget below asserts "bounded, not proportional to rows" — the property that
    actually breaks — and tolerates the feed's own count/page queries.
    """

    ROOT_COUNT = 12
    MEMBERS_PER_ROOT = 2
    # feed count + feed page + one batched member fetch + a small constant for
    # anything else the schema legitimately adds. The per-row implementation
    # this guards against needs 2x per root even before threadSize is selected.
    QUERY_BUDGET = 6

    def setUp(self):
        super().setUp()
        self.roots = []
        for _ in range(self.ROOT_COUNT):
            root = self._link(occurred_at=T0)
            for _ in range(self.MEMBERS_PER_ROOT):
                self._link(occurred_at=T1, thread=root)
            self.roots.append(root)
        # One unthreaded link so the "no members" branch rides in the same batch.
        self.lonely = self._link(occurred_at=T0)

    def _run(self):
        with CaptureQueriesContext(connection) as ctx:
            result = execute_graphql(FEED_QUERY, variables={"first": 100})
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return ctx

    def _member_batches(self, ctx):
        return [
            q["sql"]
            for q in ctx.captured_queries
            if MEMBER_BATCH_MARKER in q["sql"] and "COUNT(" not in q["sql"].upper()
        ]

    def test_a_page_of_roots_does_not_query_per_row_for_thread_links(self):
        ctx = self._run()

        self.assertLessEqual(
            len(ctx.captured_queries),
            self.QUERY_BUDGET,
            msg=(
                f"{len(ctx.captured_queries)} queries for "
                f"{self.ROOT_COUNT * (self.MEMBERS_PER_ROOT + 1) + 1} rows — "
                f"the thread fields are fanning out per row:\n"
                + "\n".join(q["sql"][:200] for q in ctx.captured_queries)
            ),
        )

    def test_thread_size_and_thread_links_share_one_batch(self):
        # ``threadSize`` and ``threadLinks`` both read the same loader, and
        # DataLoader caches per request, so asking for both is still ONE member
        # query — and the badge is structurally unable to drift from the list it
        # labels.
        ctx = self._run()

        batches = self._member_batches(ctx)

        self.assertEqual(
            len(batches),
            1,
            msg="expected exactly one batched member fetch, got:\n"
            + "\n".join(batches),
        )

    def test_the_batch_covers_every_row_in_the_page(self):
        ctx = self._run()

        batch_sql = self._member_batches(ctx)[0]

        for root in self.roots:
            self.assertIn(str(root.id), batch_sql)
        self.assertIn(str(self.lonely.id), batch_sql)

    def test_the_batch_orders_members_by_occurred_at_then_id(self):
        # The sort has to live in SQL: doing it in Python over a single global
        # ordering would work by accident for one root and interleave threads.
        ctx = self._run()

        batch_sql = self._member_batches(ctx)[0]

        self.assertIn(
            'ORDER BY "incident_socialmedialink"."occurred_at" ASC', batch_sql
        )
        self.assertIn('"incident_socialmedialink"."id" ASC', batch_sql)


class FixtureUrlTests(ThreadFieldTestCase):
    """Guard the ``_link()`` fixture URL against the landmine it used to sit on.

    ``_url()`` used to interpolate ``self.id``, which on a ``TestCase`` is
    ``unittest.TestCase.id`` — a bound method, not a primary key. Stringified it
    is a ~180 character repr whose length tracks the test's own method name, so
    whether it overflowed ``SocialMediaLink.url`` (varchar(200)) was settled by
    naming alone: 11 of this file's 29 tests blew the column purely because
    their names described themselves thoroughly, and the 18 that passed did so
    by accident — two characters of headroom was all that separated them. A
    failure that points at psycopg2 rather than at the helper that caused it is
    a failure worth a guard instead of a comment.

    These go through ``_url()`` itself rather than through ``unique_url``, so the
    thing being guarded is the code the other 29 tests actually call. They pin
    the two properties it owes its callers: the URL fits the column whatever the
    test is called, and no two rows share one.
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
        # ``threadLinks`` assertions identify a member by its URL and nothing
        # else, so a collision lets one row silently stand in for another. 500 is
        # well past the ~37 rows any single test here creates, because the
        # guarantee has to hold across the process and not merely per test.
        urls = [self._url() for _ in range(500)]

        self.assertEqual(len(set(urls)), len(urls))

    def test_the_url_still_names_the_test_that_minted_it(self):
        # Same test, successive rows: only the counter moves, so the digest part
        # is what makes a URL printed in a failure trace back to its test. A
        # fully random URL would be just as unique and name nothing.
        first, second = self._url(), self._url()

        self.assertNotEqual(first, second)
        self.assertEqual(first.rsplit("-", 1)[0], second.rsplit("-", 1)[0])
