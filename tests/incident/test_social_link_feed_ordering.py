"""The public feed and the console queue order by ``occurred_at``, not ``created``.

``occurred_at`` is "when did this happen"; ``created`` is "when did someone
report it". These tests pin the distinction by *disagreeing* the two columns in
every fixture: rows whose ``created`` order is the reverse of their
``occurred_at`` order. An implementation still ordering (or windowing) on
``created`` therefore cannot pass by accident, and the pagination tests walk the
whole result set so a keyset that skips or repeats a row is caught rather than
papered over by a single page.

What is pinned here:

* ordering ``occurred_at DESC, id DESC`` (the ``-id`` tie-break is not optional —
  ``occurred_at`` is NOT NULL but not unique, so a cursor over a single key can
  skip and duplicate rows sharing an instant);
* the cursor payload and its round-trip, including what happens to a cursor
  minted by the pre-change code;
* ``currentServiceDayOnly`` / ``lastWeekOnly`` / ``alignPageToDay`` keyed on
  ``occurred_at``, since a window on a different column than the ordering puts a
  backdated row at the top of a day it does not belong to;
* ``lastWeekOnly``'s **upper** bound — today is excluded unless
  ``displayTodayInLastWeek`` restores the inclusive window, on the flat feed and
  on a collapsed one (a reply today removes the whole conversation, at any
  depth), with the recursive subquery built only on the collapsed path;
* ``collapseThreads`` — roots only (``parent_id IS NULL``), ``totalCount`` over
  roots, the flat default unchanged, and no collapse under ``mine``;
* the query SHAPE the collapse and the windows produce: a collapsed page narrows
  on ``parent_id IS NULL`` and never on the retired flat ``thread`` column, and
  only a collapsed *windowed* page carries a recursive CTE at all — the flag is
  false on every other surface, so an uncollapsed feed must not grow one;
* ``_event_window`` widening to a DESCENDANT AT ANY DEPTH (a 3-level and a
  4-level conversation), never rescuing a wholly out-of-window conversation and
  never becoming restrictive;
* the console queue's ``occurredAfter`` / ``occurredBefore`` and its ordering;
* that both link resolvers still emit ``ORDER BY occurred_at DESC, id DESC``,
  since ``Meta.ordering = ["position"]`` (inherited from ``OrderableTreeNode``)
  now applies to any queryset that forgets to order.

Runs under plain ``django.test.TestCase`` + ``asgiref.sync.async_to_sync`` and
deliberately does NOT import pytest: pytest is not installed in the app image, so
a pytest-based file here is uncollectable dead code.
"""

import base64
import copy
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from cachalot.api import cachalot_disabled
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from dotmap import DotMap

from common.models import User
from incident.models import SocialMediaLink
from incident.schema.keyset import decode_keyset_cursor, encode_keyset_cursor
from incident.schema.resolvers import last_week_start
from incident.services.line_status import service_day_start
from rosak.context import ContextLoaders
from rosak.schema import schema

FEED_QUERY = """
    query Feed(
        $first: Int
        $after: String
        $mine: Boolean
        $currentServiceDayOnly: Boolean
        $lastWeekOnly: Boolean
        $alignPageToDay: Boolean
        $displayTodayInLastWeek: Boolean
        $collapseThreads: Boolean
    ) {
        publicSocialMediaLinks(
            first: $first
            after: $after
            mine: $mine
            currentServiceDayOnly: $currentServiceDayOnly
            lastWeekOnly: $lastWeekOnly
            alignPageToDay: $alignPageToDay
            displayTodayInLastWeek: $displayTodayInLastWeek
            collapseThreads: $collapseThreads
        ) {
            totalCount
            edges { node { id created } cursor }
            pageInfo { hasNextPage endCursor }
        }
    }
"""

CONSOLE_QUERY = """
    query Queue($after: DateTime, $before: DateTime) {
        socialMediaLinks(occurredAfter: $after, occurredBefore: $before) {
            id
        }
    }
"""


def execute_graphql(query: str, variables=None, user=None):
    """Same harness ``incident/tests.py`` uses — a DotMap context, no auth."""
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


class SocialLinkFeedOrderingBase(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="feed-ordering-user")

    def _link(self, slug, *, occurred_at, created=None, user=None, **overrides):
        """Create a link with an explicit event time and (optionally) a
        disagreeing submission time.

        ``created`` comes from ``TimeStampedModel`` (auto_now_add) and cannot be
        set through ``create()``, only updated afterwards; ``occurred_at`` is an
        ordinary defaulted column, so it is passed in.
        """
        link = SocialMediaLink.objects.create(
            url=f"https://example.com/{slug}",
            title=slug,
            user=user or self.user,
            occurred_at=occurred_at,
            **overrides,
        )
        if created is not None:
            SocialMediaLink.objects.filter(pk=link.pk).update(created=created)
            link.refresh_from_db()
        return link

    def _feed(self, query=FEED_QUERY, user=None, **variables):
        result = execute_graphql(query, variables=variables, user=user)
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return result.data["publicSocialMediaLinks"]

    def _ids(self, feed):
        return [edge["node"]["id"] for edge in feed["edges"]]

    def _feed_capture(self, *, page_only=False, **variables):
        """Run the feed once and return ``(feed, sql_touching_the_link_table)``.

        The shape assertions are about the SQL the resolver EMITS, not about the
        rows it returns: "narrows on ``parent_id`` and never on ``thread``" and
        "carries a recursive CTE only when collapsed AND windowed" are claims
        about the query, and a passing result set can hide a wrong predicate.
        The query selects only ``id``/``created``, so the scalar's own subtree
        loader never runs and the only statements touching this table are the
        count and the page.

        ``cachalot_disabled`` is load-bearing, not decoration: the app has
        ``cachalot`` installed, and it serves a repeated identical query from
        cache without touching the database. A test that runs the same feed
        twice — once for the rows, once for the SQL — would then capture
        *nothing* and every shape assertion over that empty string would pass
        vacuously, which is precisely the failure these assertions exist to
        catch. ``page_only`` drops the ``totalCount`` statement, which is
        legitimately unordered because the count is taken before ``order_by``.
        """
        with cachalot_disabled(), CaptureQueriesContext(connection) as ctx:
            feed = self._feed(first=10, **variables)
        return feed, "\n".join(
            query["sql"]
            for query in ctx.captured_queries
            if "incident_socialmedialink" in query["sql"]
            and not (page_only and "COUNT(" in query["sql"])
        )

    def _link_sql(self, **variables):
        return self._feed_capture(**variables)[1]

    def _console(self, *, after=None, before=None):
        # A ``Maybe[datetime]`` argument may be OMITTED but not explicitly null
        # ("Field of type 'Maybe[datetime]' cannot be explicitly set to null"),
        # so the bounds are only sent when set. DateTime variables travel as
        # ISO strings, not datetime objects.
        variables = {
            key: value.isoformat()
            for key, value in (("after", after), ("before", before))
            if value is not None
        }
        with patch(
            "rosak.permissions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = execute_graphql(
                CONSOLE_QUERY,
                variables=variables or None,
                user=self.user,
            )
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return result.data["socialMediaLinks"]


class FeedOrderingTests(SocialLinkFeedOrderingBase):
    """``occurred_at DESC, id DESC`` — proven against a ``created`` order that
    points the other way."""

    def test_feed_orders_by_occurred_at_not_created(self):
        day = timezone.now().date()
        # created ascending: a, b, c. occurred_at ascending: c, b, a — the two
        # orders disagree in BOTH directions, so no tie-break can mask it.
        first = self._link(
            "order-a",
            occurred_at=datetime.combine(day, time(9, 0)),
            created=datetime.combine(day, time(8, 0)),
        )
        second = self._link(
            "order-b",
            occurred_at=datetime.combine(day, time(10, 0)),
            created=datetime.combine(day, time(10, 0)),
        )
        third = self._link(
            "order-c",
            occurred_at=datetime.combine(day, time(11, 0)),
            created=datetime.combine(day, time(12, 0)),
        )

        feed = self._feed(first=10)

        # created DESC would have been c, b, a.
        self.assertEqual(
            self._ids(feed), [str(third.id), str(second.id), str(first.id)]
        )
        self.assertEqual(feed["totalCount"], 3)

    def test_ties_on_occurred_at_break_by_descending_id(self):
        instant = datetime.combine(timezone.now().date(), time(9, 30))
        # Same event time, ascending creation order, so ``-occurred_at`` alone
        # leaves the pair unordered and the ``-id`` tie-break decides.
        older = self._link("tie-older", occurred_at=instant)
        newer = self._link("tie-newer", occurred_at=instant)

        feed = self._feed(first=10)

        self.assertGreater(newer.id, older.id)
        self.assertEqual(self._ids(feed), [str(newer.id), str(older.id)])


class FeedKeysetPaginationTests(SocialLinkFeedOrderingBase):
    def test_walking_every_page_reproduces_the_full_sequence_exactly_once(self):
        day = timezone.now().date()
        # Descending occurred_at, with a deliberate pair sharing an instant so
        # the ``occurred_at = cursor AND id < cursor_id`` branch is exercised
        # mid-walk and not only at the tail.
        expected: list[SocialMediaLink] = []
        for index, hour in enumerate([12, 11, 10, 10, 9, 8, 7]):
            expected.append(
                self._link(
                    f"walk-{index}",
                    # ``created`` runs the other way, so a ``created`` keyset
                    # would walk a different order and fail the equality.
                    occurred_at=datetime.combine(day, time(hour, 0)),
                    created=datetime.combine(day, time(6, 0)) + timedelta(hours=index),
                )
            )
        expected.sort(key=lambda link: (link.occurred_at, link.id), reverse=True)
        expected_ids = [str(link.id) for link in expected]

        walked: list[str] = []
        seen_cursors: list[str] = []
        after = None
        for _ in range(20):  # bounded: 7 rows cannot need 20 pages
            feed = self._feed(first=2, after=after)
            walked.extend(self._ids(feed))
            seen_cursors.extend(edge["cursor"] for edge in feed["edges"])
            if not feed["pageInfo"]["hasNextPage"]:
                break
            after = feed["pageInfo"]["endCursor"]
        else:
            self.fail("pagination did not terminate")

        self.assertEqual(walked, expected_ids)
        self.assertEqual(len(walked), len(set(walked)), "a row was returned twice")
        self.assertEqual(len(set(seen_cursors)), len(seen_cursors))

    def test_cursor_payload_is_the_occurred_at_id_pair(self):
        link = self._link(
            "cursor-payload",
            occurred_at=datetime.combine(timezone.now().date(), time(9, 0)),
            created=datetime.combine(timezone.now().date(), time(23, 0)),
        )

        feed = self._feed(first=10)

        cursor = feed["edges"][0]["cursor"]
        self.assertEqual(decode_keyset_cursor(cursor), (link.occurred_at, link.id))
        self.assertNotEqual(cursor, encode_keyset_cursor(link.created, link.id))
        # Round-trips: decoding then re-encoding is byte-stable.
        self.assertEqual(encode_keyset_cursor(*decode_keyset_cursor(cursor)), cursor)
        # The wire payload is the plain "<iso>|<id>" pair, base64'd.
        self.assertEqual(
            base64.b64decode(cursor.encode()).decode(),
            f"{link.occurred_at.isoformat()}|{link.id}",
        )


class LegacyCursorTests(SocialLinkFeedOrderingBase):
    """A cursor minted by the pre-change code still *decodes*.

    Decision (recorded deliberately, not overlooked): the wire format is
    unchanged — base64("<iso datetime>|<id>") — and the resolver keeps decoding
    it, so an old cursor is accepted rather than rejected. It is **not** honoured
    as before: the payload is now read as ``occurred_at``, so a cursor that was
    minted from a submission time resumes relative to an event time and may skip
    or repeat rows. Rejecting it instead would turn every in-flight page through
    a deploy into a client-visible error for no safety gain; the docstring tells
    callers to relaunch from page one.
    """

    def test_a_legacy_created_payload_cursor_still_decodes_and_is_read_as_occurred_at(
        self,
    ):
        day = timezone.now().date()
        newest = self._link(
            "legacy-newest",
            occurred_at=datetime.combine(day, time(12, 0)),
            created=datetime.combine(day, time(23, 0)),
        )
        middle = self._link(
            "legacy-middle",
            occurred_at=datetime.combine(day, time(10, 0)),
            created=datetime.combine(day, time(8, 0)),
        )
        oldest = self._link(
            "legacy-oldest",
            occurred_at=datetime.combine(day, time(8, 0)),
            created=datetime.combine(day, time(9, 0)),
        )

        # Exactly how the pre-change resolver minted it: payload is ``created``.
        legacy_cursor = encode_keyset_cursor(newest.created, newest.id)

        # It decodes: no exception, no GraphQL error.
        self.assertEqual(
            decode_keyset_cursor(legacy_cursor), (newest.created, newest.id)
        )
        feed = self._feed(first=10, after=legacy_cursor)

        # ...and is then read as ``occurred_at``. ``newest.created`` (23:00) is
        # LATER than every row's event time, so the page restarts from the top
        # and re-returns the very row the cursor was minted from — the
        # "may repeat rows" half of the documented behaviour.
        self.assertEqual(
            self._ids(feed), [str(newest.id), str(middle.id), str(oldest.id)]
        )

        # The mirror image: a legacy cursor minted from an early submission
        # time lands in the middle of the event-time order and skips the rows
        # above it — the "may skip rows" half.
        skipping_cursor = encode_keyset_cursor(oldest.created, oldest.id)
        self.assertEqual(
            self._ids(self._feed(first=10, after=skipping_cursor)), [str(oldest.id)]
        )


class FeedWindowTests(SocialLinkFeedOrderingBase):
    """Both windows are on ``occurred_at``, proven by disagreeing the columns."""

    def test_current_service_day_only_windows_on_occurred_at(self):
        now = timezone.now()
        boundary = service_day_start(now)

        # Reported before the service day started, but it happened inside it.
        in_day = self._link(
            "window-in",
            occurred_at=now,
            created=boundary - timedelta(minutes=1),
        )
        # Reported now, but it happened before the service day started.
        out_of_day = self._link(
            "window-out",
            occurred_at=boundary - timedelta(minutes=1),
            created=now,
        )

        filtered = self._feed(first=10, currentServiceDayOnly=True)

        self.assertEqual(self._ids(filtered), [str(in_day.id)])
        self.assertEqual(filtered["totalCount"], 1)

        # The rows really do disagree, so the assertion above is not vacuous.
        self.assertLess(in_day.created, out_of_day.created)

    def _conversation(self, slug, *occurred_at):
        """A chain of links, each hung under the one before it.

        Returns the chain root-first, so ``chain[0]`` is the root and
        ``chain[-1]`` is the deepest sublink. Nesting is what the feed now has to
        reason about: "in the conversation" is an arbitrary-depth question, so
        the fixtures are built by descending rather than by attaching siblings
        to a single root.
        """
        chain = []
        parent = None
        for index, instant in enumerate(occurred_at):
            link = self._link(f"{slug}-{index}", occurred_at=instant, parent=parent)
            chain.append(link)
            parent = link
        return chain

    def test_a_collapsed_conversation_enters_the_window_by_a_sublink_two_levels_down(
        self,
    ):
        """A collapsed card is admitted by the WHOLE SUBTREE, not by its root.

        Grouping elects the EARLIEST link as root, so the root is the
        conversation's first event and every descendant is LATER than it. That
        makes "the root is outside the window while something below it is inside
        it" the ORDINARY shape for any conversation that opened before the
        window and got a follow-up inside it — it needs no ``occurredAt`` edit
        to happen and is not an edge case. A root-keyed window then drops the
        whole conversation from a feed the follow-up belongs in, and the
        follow-up becomes unreachable: the collapsed surface renders the ROOT,
        and the root was filtered out.

        Depth 2 is where the one-level design ran out: a sublink of a sublink is
        exactly the case a "has a parent" test could not express.
        """
        boundary = service_day_start(timezone.now())

        # Opened two days ago, a reply yesterday, and the follow-up that
        # actually happened today is two levels below the root.
        root, reply, follow_up = self._conversation(
            "window-deep",
            boundary - timedelta(days=2),
            boundary - timedelta(days=1),
            boundary + timedelta(hours=6),
        )

        # The root-keyed reading would return an empty page; only the
        # subtree-wide reading returns anything. Assert the shape so the test
        # cannot pass vacuously on a fixture where the two readings agree.
        self.assertLess(root.occurred_at, boundary)
        self.assertLess(reply.occurred_at, boundary)
        self.assertGreaterEqual(follow_up.occurred_at, boundary)
        self.assertEqual(follow_up.parent_id, reply.id)
        self.assertEqual(reply.parent_id, root.id)

        collapsed = self._feed(
            first=10, currentServiceDayOnly=True, collapseThreads=True
        )
        self.assertEqual(self._ids(collapsed), [str(root.id)])
        self.assertEqual(collapsed["totalCount"], 1)

        # The follow-up rides inside that card rather than being dropped from
        # the feed, which is the difference between "not listed" and "not
        # reachable". The FLAT feed still judges each row on its own
        # ``occurred_at`` — the widening belongs to collapse, it does not rewrite
        # anyone's date — and returns the follow-up as its own row.
        flat = self._feed(first=10, currentServiceDayOnly=True)
        self.assertEqual(self._ids(flat), [str(follow_up.id)])

    def test_a_collapsed_conversation_enters_the_window_by_a_sublink_three_levels_down(
        self,
    ):
        """Same argument one level deeper: a great-grandchild is still "in".

        Nothing about the window is depth-limited: the write side caps how deep
        real data gets, but the read side must not assume a depth it was not
        told. If the widening were rewritten as a fixed number of hops, this
        fixture is where it would start returning an empty page while every
        shallower test still passed.
        """
        boundary = service_day_start(timezone.now())

        root, level_1, level_2, level_3 = self._conversation(
            "window-deeper",
            boundary - timedelta(days=3),
            boundary - timedelta(days=2),
            boundary - timedelta(days=1),
            boundary + timedelta(hours=6),
        )

        self.assertLess(level_2.occurred_at, boundary)
        self.assertGreaterEqual(level_3.occurred_at, boundary)
        self.assertEqual(level_3.parent_id, level_2.id)

        collapsed = self._feed(
            first=10, currentServiceDayOnly=True, collapseThreads=True
        )
        self.assertEqual(self._ids(collapsed), [str(root.id)])
        self.assertEqual(collapsed["totalCount"], 1)

    def test_a_conversation_entirely_outside_the_window_stays_out(self):
        # The converse guard: widening must not admit conversations with nothing
        # in the window, or the flag would stop being a filter at all. A three-
        # level chain, because the failure mode this guards is an OR that
        # disables itself — and a naive implementation of that OR is exactly
        # what a recursive EXISTS invites.
        boundary = service_day_start(timezone.now())
        # Every level beyond the 7-day window (which reaches back six days).
        root, reply, follow_up = self._conversation(
            "stale",
            boundary - timedelta(days=10),
            boundary - timedelta(days=11),
            boundary - timedelta(days=12),
        )

        collapsed = self._feed(first=10, lastWeekOnly=True, collapseThreads=True)

        # Only the root is even a candidate, and nothing in its subtree is in the
        # window — so the widened predicate must not rescue it.
        self.assertLess(root.occurred_at, last_week_start(timezone.now()))
        self.assertLess(follow_up.occurred_at, last_week_start(timezone.now()))
        self.assertEqual(self._ids(collapsed), [])
        self.assertEqual(collapsed["totalCount"], 0)

    def test_a_root_in_window_keeps_its_conversation_even_if_no_sublink_is(self):
        # Widening is additive, never restrictive: a root inside the window is
        # admitted on its own ``occurred_at`` exactly as the flat feed would.
        # The root lands in the early hours of TODAY, which the *default*
        # window excludes, so this runs the inclusive window the flag restores:
        # the property under test is "widening never removes", and it would be
        # confounded with the today exclusion otherwise.
        #
        # Anchored to ABSOLUTE wall time, not to ``service_day_start``:
        # ``service_day_start`` rolls back to 03:00 of the previous day between
        # midnight and 03:00, so ``boundary + 2h`` would land on YESTERDAY and
        # the default-window assertion at the bottom would start passing for the
        # wrong reason. Calendar midnight plus a fixed hour offset means "today
        # 02:00" wherever in the day the suite happens to run.
        today_midnight = datetime.combine(timezone.now().date(), time.min)
        root = self._link("fresh-root", occurred_at=today_midnight + timedelta(hours=2))
        child = self._link(
            "older-child", occurred_at=today_midnight - timedelta(days=10), parent=root
        )
        grandchild = self._link(
            "older-grandchild",
            occurred_at=today_midnight - timedelta(days=11),
            parent=child,
        )

        collapsed = self._feed(
            first=10,
            lastWeekOnly=True,
            displayTodayInLastWeek=True,
            collapseThreads=True,
        )

        self.assertLess(grandchild.occurred_at, last_week_start(timezone.now()))
        self.assertEqual(self._ids(collapsed), [str(root.id)])
        # ...and the default really does exclude it, so this is not a fixture on
        # which the two windows happen to agree.
        self.assertEqual(
            self._ids(self._feed(first=10, lastWeekOnly=True, collapseThreads=True)),
            [],
        )

    def test_the_uncollapsed_feed_has_no_recursive_subquery(self):
        """The widening is built ONLY on the collapsed path.

        ``collapseThreads`` is false on every other surface, so if the recursive
        subquery were built unconditionally every one of them would inherit a
        recursive walk it has no use for. Asserted on the emitted SQL rather
        than on the results, because the rows are identical either way — that is
        the whole point.
        """
        boundary = service_day_start(timezone.now())
        self._conversation(
            "shape", boundary - timedelta(days=1), boundary + timedelta(hours=1)
        )

        self.assertNotIn("WITH RECURSIVE", self._link_sql(currentServiceDayOnly=True))
        self.assertNotIn("WITH RECURSIVE", self._link_sql(lastWeekOnly=True))
        # Collapsing without a window is likewise free of recursion: the root
        # narrowing is a plain indexed null test on ``parent_id``.
        self.assertNotIn("WITH RECURSIVE", self._link_sql(collapseThreads=True))
        # ...and turning the window on under collapse is what introduces it.
        self.assertIn(
            "WITH RECURSIVE",
            self._link_sql(collapseThreads=True, currentServiceDayOnly=True),
        )

    def test_both_window_flags_together_carry_one_recursive_cte_each(self):
        """Two windows, two subqueries, two CTEs that share a name.

        Both flags compose on one queryset, so one statement carries the
        library's ``__tree`` CTE twice, once per subquery. Each is scoped to its
        own sub-select, so the shadowing is legal — but it is exactly the kind
        of thing that turns into "WITH RECURSIVE ... duplicate" or a silent
        cross-talk between the two walks, so the combination is pinned.
        """
        # Anchored to ABSOLUTE wall time for the same reason as the other
        # clock-sensitive fixtures: ``service_day_start`` is 03:00 of TODAY
        # except between midnight and 03:00, when it is yesterday's — a fixture
        # expressed as an offset from it silently changes sides of the window in
        # the early hours. Calendar midnight plus fixed offsets says the same
        # thing at every hour: the root is a week back, out of BOTH windows, and
        # the child is at 03:00 today, inside BOTH (the service-day lower bound
        # is satisfied whether it resolved to today 00:00 or yesterday 03:00).
        today_midnight = datetime.combine(timezone.now().date(), time.min)
        root, child = self._conversation(
            "both",
            today_midnight - timedelta(days=7),
            today_midnight + timedelta(hours=3),
        )

        # The fixture's root is out of both windows, its child is in both, so
        # the collapse admits exactly that one root. ``displayTodayInLastWeek``
        # is required: the child lands in the current service day, which the
        # default ``lastWeekOnly`` window excludes, so without it this test would
        # be counting the today exclusion's subqueries instead of the two windows'.
        # One execution, both halves: the rows and the statement that produced
        # them, so the SQL assertion cannot be handed an empty capture.
        collapsed, sql = self._feed_capture(
            currentServiceDayOnly=True,
            lastWeekOnly=True,
            displayTodayInLastWeek=True,
            collapseThreads=True,
        )
        self.assertEqual(self._ids(collapsed), [str(root.id)])
        self.assertEqual(collapsed["totalCount"], 1)
        self.assertEqual(child.parent_id, root.id)
        # Two per statement — the page fetch and the ``totalCount`` query, which
        # runs the same widened predicate. Four in total, which is also the proof
        # that the count is taken AFTER the windows: a count taken before them
        # would carry no CTE at all and would disagree with the page.
        self.assertEqual(sql.count("WITH RECURSIVE"), 4)
        self.assertEqual(
            self._feed_capture(
                page_only=True,
                currentServiceDayOnly=True,
                lastWeekOnly=True,
                displayTodayInLastWeek=True,
                collapseThreads=True,
            )[1].count("WITH RECURSIVE"),
            2,
        )

    def test_last_week_only_windows_on_occurred_at(self):
        now = timezone.now()
        start = datetime.combine((now - timedelta(days=6)).date(), time.min)

        # Exactly on the boundary and reported a month ago: in.
        boundary = self._link(
            "week-in",
            occurred_at=start,
            created=now - timedelta(days=30),
        )
        # One minute earlier by event time but reported a moment ago: out.
        self._link(
            "week-out",
            occurred_at=start - timedelta(minutes=1),
            created=now,
        )

        filtered = self._feed(first=10, lastWeekOnly=True)

        self.assertEqual(self._ids(filtered), [str(boundary.id)])
        self.assertEqual(filtered["totalCount"], 1)
        # The rows really do disagree, so the assertion above is not vacuous: a
        # ``created``-keyed window would have excluded the in-window row
        # (reported a month ago) and included the out-of-window one (reported
        # just now) — the exact inverse of this result.
        self.assertLess(boundary.created, now)
        # Nothing was deleted — the window narrows the feed.
        self.assertEqual(SocialMediaLink.objects.count(), 2)


class LastWeekTodayExclusionTests(SocialLinkFeedOrderingBase):
    """``lastWeekOnly`` has an UPPER bound too: today is out by default.

    ``lastWeekStart`` only ever supplied the lower bound, so "the last week"
    silently included the day in progress — a view that changes under the reader
    and whose newest day is half-formed next to six completed ones.
    ``displayTodayInLastWeek`` restores the inclusive window; the default is the
    closed range ``[six days ago 00:00, today 00:00)``.

    The interesting half is the collapsed one. The bound has to be resolved over
    the SUBTREE for exactly the reason the lower bound is: grouping elects the
    EARLIEST link as root, so "the root is yesterday and a descendant is today"
    is the ordinary shape of any conversation with a follow-up. A root-only upper
    bound would keep the card — and, since the collapsed surface renders the
    ROOT, it would keep a today follow-up inside a view that claims to be the
    previous days.
    """

    def _today_midnight(self):
        return datetime.combine(timezone.now().date(), time.min)

    def _conversation(self, slug, *occurred_at):
        """A root-first chain; see ``FeedWindowTests._conversation``."""
        chain = []
        parent = None
        for index, instant in enumerate(occurred_at):
            link = self._link(f"{slug}-{index}", occurred_at=instant, parent=parent)
            chain.append(link)
            parent = link
        return chain

    def test_a_reply_today_takes_the_whole_conversation_out_of_the_window(self):
        today = self._today_midnight()
        root, reply = self._conversation(
            "excluded-by-reply",
            today - timedelta(days=1, hours=1),  # yesterday evening
            today + timedelta(hours=9),  # this morning
        )

        collapsed = self._feed(first=10, lastWeekOnly=True, collapseThreads=True)

        self.assertEqual(self._ids(collapsed), [])
        self.assertEqual(collapsed["totalCount"], 0)
        # Assert the fixture so this cannot pass on a shape where the two
        # readings agree: the root is genuinely inside the lower bound and only
        # the DESCENDANT is today.
        self.assertLess(root.occurred_at, today)
        self.assertGreaterEqual(reply.occurred_at, today)
        # The flag puts the conversation back, root card and all.
        self.assertEqual(
            self._ids(
                self._feed(
                    first=10,
                    lastWeekOnly=True,
                    displayTodayInLastWeek=True,
                    collapseThreads=True,
                )
            ),
            [str(root.id)],
        )
        # The FLAT feed judges each row on its own ``occurred_at``, so the reply
        # is gone but yesterday's root is still listed — the widening belongs to
        # the collapsed card, it does not rewrite anyone's date.
        self.assertEqual(
            self._ids(self._feed(first=10, lastWeekOnly=True)), [str(root.id)]
        )

    def test_a_root_that_happened_today_is_excluded(self):
        """The root itself being today is the trivially-covered case, pinned so a
        future refactor that drops the plain ``occurred_at__lt`` conjunct cannot
        hide behind the subtree subquery.

        The child is deliberately YESTERDAY: ``occurredAt`` is editable, so
        "descendants are later than the root" is a convention, not an invariant,
        and the fixture shows the root-only reading and the subtree reading
        agreeing here for the wrong reason if the times were swapped.
        """
        today = self._today_midnight()
        root, child = self._conversation(
            "excluded-by-root",
            today + timedelta(hours=10),  # this morning
            today - timedelta(days=2),  # two days ago, moved up under the root
        )

        collapsed = self._feed(first=10, lastWeekOnly=True, collapseThreads=True)

        self.assertGreaterEqual(root.occurred_at, today)
        self.assertEqual(self._ids(collapsed), [])
        self.assertEqual(
            self._ids(
                self._feed(
                    first=10,
                    lastWeekOnly=True,
                    displayTodayInLastWeek=True,
                    collapseThreads=True,
                )
            ),
            [str(root.id)],
        )

    def test_a_descendant_two_levels_down_today_takes_the_conversation_out(self):
        """Nothing about the upper bound is depth-limited either.

        Same argument, one level deeper: a great-grandchild is still "in the
        conversation". A fixed number of hops would start returning the card here
        while every shallower test still passed.
        """
        today = self._today_midnight()
        root, level_1, level_2 = self._conversation(
            "excluded-deep",
            today - timedelta(days=4),
            today - timedelta(days=3),
            today + timedelta(hours=7),
        )

        collapsed = self._feed(first=10, lastWeekOnly=True, collapseThreads=True)

        self.assertLess(level_1.occurred_at, today)
        self.assertGreaterEqual(level_2.occurred_at, today)
        self.assertEqual(self._ids(collapsed), [])
        self.assertEqual(collapsed["totalCount"], 0)

    def test_a_conversation_entirely_before_today_survives(self):
        """The converse guard, at every depth: the exclusion must not become a
        filter that swallows the six completed days it is supposed to show.

        Deliberately spans the whole window, from the exact 00:00 six-days-ago
        opening minute to the last minute of yesterday, so a bound that was
        accidentally ``<=`` today would still pass the "excludes today" tests and
        fail here.
        """
        now = timezone.now()
        start = last_week_start(now)
        root, middle, leaf = self._conversation(
            "survivor",
            start,  # the exact opening minute
            start + timedelta(days=3, hours=7),
            now - timedelta(days=1, hours=0, minutes=1),  # yesterday 23:59
        )

        collapsed = self._feed(first=10, lastWeekOnly=True, collapseThreads=True)

        self.assertEqual(self._ids(collapsed), [str(root.id)])
        self.assertEqual(collapsed["totalCount"], 1)
        self.assertEqual(middle.parent_id, root.id)
        self.assertEqual(leaf.parent_id, middle.id)

    def test_the_exclusion_walks_the_tree_only_on_the_collapsed_path(self):
        """The upper bound costs the same as the lower one: nothing off the
        collapsed path.

        Two recursive walks per statement when collapsed and windowed (one per
        bound), none on the flat feed — the rows are identical either way, so this
        is asserted on the emitted SQL.
        """
        today = self._today_midnight()
        self._conversation(
            "shape-upper",
            today - timedelta(days=2),
            today + timedelta(hours=1),
        )

        # The flat default window is one comparison on one column.
        self.assertNotIn("WITH RECURSIVE", self._link_sql(lastWeekOnly=True))
        # Collapsing alone, and the flag on its own, stay flat: neither is a
        # window, so neither builds a subquery.
        self.assertNotIn("WITH RECURSIVE", self._link_sql(collapseThreads=True))
        self.assertNotIn(
            "WITH RECURSIVE",
            self._link_sql(lastWeekOnly=True, displayTodayInLastWeek=True),
        )
        # Both bounds on the collapsed path: two walks per statement, and the
        # count query runs the same predicate, so four.
        self.assertEqual(
            self._link_sql(lastWeekOnly=True, collapseThreads=True).count(
                "WITH RECURSIVE"
            ),
            4,
        )


class AlignPageToDayTests(SocialLinkFeedOrderingBase):
    """Whole-day completion, keyed on the *event* day."""

    def test_day_is_completed_by_occurred_at_and_the_cursor_continues(self):
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        a0 = self._link(
            "align-a0",
            occurred_at=datetime.combine(today, time(12, 0)),
            created=datetime.combine(today, time(9, 0)),
        )
        a1 = self._link(
            "align-a1",
            occurred_at=datetime.combine(today, time(11, 0)),
            created=datetime.combine(today, time(10, 0)),
        )
        # Reported yesterday, happened today: under a ``created``-keyed day this
        # row would have been the lookahead on a *different* day and alignment
        # would have stopped one row early.
        a2 = self._link(
            "align-a2",
            occurred_at=datetime.combine(today, time(10, 0)),
            created=datetime.combine(yesterday, time(10, 0)),
        )
        b0 = self._link(
            "align-b0",
            occurred_at=datetime.combine(yesterday, time(9, 0)),
            created=datetime.combine(today, time(8, 0)),
        )

        page_one = self._feed(first=2, alignPageToDay=True)

        self.assertEqual(self._ids(page_one), [str(a0.id), str(a1.id), str(a2.id)])
        self.assertEqual(
            page_one["pageInfo"]["endCursor"], page_one["edges"][-1]["cursor"]
        )
        self.assertTrue(page_one["pageInfo"]["hasNextPage"])

        page_two = self._feed(
            first=2, after=page_one["pageInfo"]["endCursor"], alignPageToDay=True
        )
        self.assertEqual(self._ids(page_two), [str(b0.id)])
        self.assertFalse(page_two["pageInfo"]["hasNextPage"])

    def test_a_day_larger_than_first_lands_whole_with_no_cap(self):
        today = timezone.now().date()
        links = [
            self._link(
                f"align-uncapped-{index}",
                occurred_at=datetime.combine(today, time(12 - index, 0)),
            )
            for index in range(5)
        ]

        feed = self._feed(first=2, alignPageToDay=True)

        # 5 rows on one event day, ``first`` is 2, and there is no cap.
        self.assertEqual(len(feed["edges"]), 5)
        self.assertEqual(set(self._ids(feed)), {str(link.id) for link in links})
        self.assertFalse(feed["pageInfo"]["hasNextPage"])


class CollapseThreadsTests(SocialLinkFeedOrderingBase):
    def _tree_fixture(self):
        """Two conversations whose sublinks are interleaved by ``occurred_at``.

        Ordering by event time is what breaks client-side grouping: a
        conversation's sublinks are not adjacent, so a flat page cannot be
        regrouped after the fact. ``root_a``/``root_b`` are the roots (earliest
        event of their conversation, matching the grouping service's root
        selection), and ``child_a``/``grandchild_a`` make it a real TREE rather
        than the flat one-level group the flag used to describe.
        """
        day = timezone.now().date()

        def at(hour):
            return datetime.combine(day, time(hour, 0))

        root_a = self._link("thread-root-a", occurred_at=at(9))
        solo = self._link("thread-solo", occurred_at=at(10))
        child_a = self._link("thread-child-a", occurred_at=at(11), parent=root_a)
        root_b = self._link("thread-root-b", occurred_at=at(12))
        child_b = self._link("thread-child-b", occurred_at=at(13), parent=root_b)
        grandchild_a = self._link(
            "thread-grandchild-a", occurred_at=at(14), parent=child_a
        )
        return root_a, solo, child_a, root_b, child_b, grandchild_a

    def test_collapse_returns_only_roots_and_counts_them(self):
        root_a, solo, child_a, root_b, child_b, grandchild_a = self._tree_fixture()

        flat = self._feed(first=10, collapseThreads=False)
        collapsed = self._feed(first=10, collapseThreads=True)

        # Sublinks are not adjacent in the flat order — the premise for
        # collapsing at all.
        self.assertEqual(
            self._ids(flat),
            [
                str(grandchild_a.id),
                str(child_b.id),
                str(root_b.id),
                str(child_a.id),
                str(solo.id),
                str(root_a.id),
            ],
        )
        self.assertEqual(flat["totalCount"], 6)

        self.assertEqual(
            self._ids(collapsed), [str(root_b.id), str(solo.id), str(root_a.id)]
        )
        # "M of M" counts roots, not rows that were filtered away.
        self.assertEqual(collapsed["totalCount"], 3)

        returned = {int(node_id) for node_id in self._ids(collapsed)}
        self.assertNotIn(child_a.id, returned)
        self.assertNotIn(child_b.id, returned)
        self.assertNotIn(grandchild_a.id, returned)
        self.assertTrue(
            all(SocialMediaLink.objects.get(pk=pk).parent_id is None for pk in returned)
        )
        # The sublinks themselves are untouched in storage — this is a read-side
        # narrowing, not a re-parenting.
        self.assertEqual(SocialMediaLink.objects.count(), 6)
        self.assertEqual(
            SocialMediaLink.objects.get(pk=child_a.id).parent_id, root_a.id
        )
        self.assertEqual(
            SocialMediaLink.objects.get(pk=grandchild_a.id).parent_id, child_a.id
        )

    def test_collapse_narrows_on_parent_id_and_never_on_the_retired_thread_column(self):
        # The predicate is a claim about the schema, not about the rows: the
        # flat ``thread`` self-FK is gone, and "is a root" is now the single
        # structural statement ``parent_id IS NULL``. Captured from the SQL the
        # resolver emitted, because a result-set assertion cannot tell a correct
        # predicate from a fixture that happens to agree with a wrong one.
        self._tree_fixture()

        collapsed = self._link_sql(collapseThreads=True)
        self.assertIn('"incident_socialmedialink"."parent_id" IS NULL', collapsed)
        self.assertNotIn("thread_id", collapsed)

        flat = self._link_sql(collapseThreads=False)
        self.assertNotIn('"incident_socialmedialink"."parent_id" IS NULL', flat)
        self.assertNotIn("thread_id", flat)

    def test_a_three_level_conversation_collapses_to_its_root_alone(self):
        # The nesting case: two hops below the root, so a collapse that still
        # thought in terms of "one member per thread" would put a sublink of a
        # sublink on the page as if it were a card of its own.
        root_a, solo, child_a, root_b, child_b, grandchild_a = self._tree_fixture()

        collapsed = self._feed(first=10, collapseThreads=True)

        self.assertEqual(grandchild_a.parent_id, child_a.id)
        self.assertEqual(child_a.parent_id, root_a.id)
        self.assertEqual(
            self._ids(collapsed), [str(root_b.id), str(solo.id), str(root_a.id)]
        )
        self.assertNotIn(str(grandchild_a.id), self._ids(collapsed))
        # Still one card per conversation, so the count is roots — three
        # conversations (root_a's two-level one, root_b's, and the unthreaded
        # link), not six links.
        self.assertEqual(collapsed["totalCount"], 3)

    def test_default_flat_feed_is_identical_to_explicit_false(self):
        self._tree_fixture()

        omitted = self._feed(first=10)
        explicit = self._feed(first=10, collapseThreads=False)

        # "Byte-identical to today's behaviour": same ids, same cursors, same
        # count, same page info.
        self.assertEqual(omitted, explicit)
        self.assertEqual(omitted["totalCount"], 6)
        self.assertFalse(omitted["pageInfo"]["hasNextPage"])

    def test_collapse_is_ignored_under_mine(self):
        root_a, solo, child_a, root_b, child_b, grandchild_a = self._tree_fixture()
        other = User.objects.create(firebase_id="feed-ordering-other")
        stranger = self._link(
            "thread-stranger",
            occurred_at=datetime.combine(timezone.now().date(), time(15, 0)),
            user=other,
        )

        flat_mine = self._feed(
            first=10, mine=True, collapseThreads=False, user=self.user
        )
        collapsed_mine = self._feed(
            first=10, mine=True, collapseThreads=True, user=self.user
        )

        # "My Submitted Links" is a personal list: every row the caller
        # submitted is a row they expect to find, sublinks included — at every
        # depth, since a submitter nesting a reply is still their own row.
        own_ids = {
            str(root_a.id),
            str(solo.id),
            str(child_a.id),
            str(root_b.id),
            str(child_b.id),
            str(grandchild_a.id),
        }
        self.assertEqual(flat_mine, collapsed_mine)
        self.assertEqual(set(self._ids(collapsed_mine)), own_ids)
        self.assertEqual(collapsed_mine["totalCount"], 6)
        self.assertNotIn(str(stranger.id), self._ids(collapsed_mine))
        # ...and the suppression is visible in the SQL: no root narrowing at all.
        self.assertNotIn(
            '"incident_socialmedialink"."parent_id" IS NULL',
            self._link_sql(mine=True, collapseThreads=True),
        )

    def test_the_collapsed_page_cursor_still_encodes_occurred_at_and_id(self):
        # The collapse must not disturb the cursor contract: a page unit is a
        # root, but the keyset is still the (occurred_at, id) pair the ordering
        # uses, or a cursor minted from this page would not resume anywhere.
        root_a, solo, child_a, root_b, child_b, grandchild_a = self._tree_fixture()

        collapsed = self._feed(first=10, collapseThreads=True)

        for edge in collapsed["edges"]:
            node = SocialMediaLink.objects.get(pk=int(edge["node"]["id"]))
            self.assertEqual(
                decode_keyset_cursor(edge["cursor"]), (node.occurred_at, node.id)
            )
        self.assertEqual(
            collapsed["pageInfo"]["endCursor"], collapsed["edges"][-1]["cursor"]
        )

    def test_collapse_reaches_only_the_public_feed_and_the_other_hosts_stay_flat(self):
        """``/insiden``, the situasi tab and the per-incident lists stay flat.

        They are separate surfaces that render every link as its own card, so
        they must keep returning the whole tree un-collapsed and complete. The
        structural half of that is in the schema: ``collapseThreads`` exists on
        exactly one field, so those hosts cannot ask for a collapse even by
        accident. The behavioural half is below — the console queue (the same
        flat-list shape) returns all three levels of a conversation.
        """
        sdl = schema.as_str()
        carriers = [
            line.strip() for line in sdl.splitlines() if "collapseThreads" in line
        ]
        self.assertEqual(
            len(carriers),
            1,
            f"collapseThreads must exist on exactly one field, found: {carriers}",
        )
        self.assertTrue(carriers[0].startswith("publicSocialMediaLinks("))
        # The per-incident ``CalendarIncidentScalar.links`` (the /insiden and
        # situasi shape) takes no collapse argument either.
        scalar_block = sdl.split("type CalendarIncidentScalar {")[1].split("\n}")[0]
        self.assertIn("links(first:", scalar_block)
        self.assertNotIn("collapseThreads", scalar_block)
        # ...and the console queue's own signature is collapse-free by
        # construction, so the assertion above is not an artefact of this file.
        self.assertNotIn("collapseThreads", CONSOLE_QUERY)

        root_a, solo, child_a, root_b, child_b, grandchild_a = self._tree_fixture()

        rows = self._console()

        # Every level of every conversation, flat and complete, in the queue's
        # own ``-occurred_at, -id`` order.
        self.assertEqual(
            [row["id"] for row in rows],
            [
                str(grandchild_a.id),
                str(child_b.id),
                str(root_b.id),
                str(child_a.id),
                str(solo.id),
                str(root_a.id),
            ],
        )
        self.assertEqual(SocialMediaLink.objects.filter(parent__isnull=True).count(), 3)


class ConsoleQueueOrderingTests(SocialLinkFeedOrderingBase):
    """The admin queue orders and windows on ``occurred_at`` too."""

    def test_queue_orders_by_occurred_at_then_descending_id(self):
        day = timezone.now().date()
        # ``created`` runs the opposite way, so a ``-created`` queue fails.
        newest = self._link(
            "queue-a",
            occurred_at=datetime.combine(day, time(12, 0)),
            created=datetime.combine(day, time(8, 0)),
        )
        oldest = self._link(
            "queue-b",
            occurred_at=datetime.combine(day, time(9, 0)),
            created=datetime.combine(day, time(20, 0)),
        )

        rows = self._console()

        self.assertEqual([row["id"] for row in rows], [str(newest.id), str(oldest.id)])

    def test_queue_breaks_occurred_at_ties_by_descending_id(self):
        instant = datetime.combine(timezone.now().date(), time(9, 30))
        first = self._link("queue-tie-1", occurred_at=instant)
        second = self._link("queue-tie-2", occurred_at=instant)

        rows = self._console()

        self.assertEqual([row["id"] for row in rows], [str(second.id), str(first.id)])

    def test_queue_occurred_after_and_before_filter_on_occurred_at(self):
        day = timezone.now().date()
        boundary = datetime.combine(day, time(10, 0))
        in_range = self._link(
            "queue-in-range",
            occurred_at=datetime.combine(day, time(11, 0)),
            created=datetime.combine(day, time(8, 0)),
        )
        too_old = self._link(
            "queue-too-old",
            occurred_at=datetime.combine(day, time(9, 0)),
            created=datetime.combine(day, time(8, 0)),
        )
        too_new = self._link(
            "queue-too-new",
            occurred_at=datetime.combine(day, time(13, 0)),
            created=datetime.combine(day, time(14, 0)),
        )

        rows = self._console(after=boundary, before=boundary + timedelta(hours=1))

        # Both bounds are inclusive; only the in-range event time survives. Under
        # a ``created`` filter ``too_old``/``too_new`` would swap sides.
        self.assertEqual([row["id"] for row in rows], [str(in_range.id)])
        # The rows exist — this is a filter, not a deletion.
        self.assertEqual(SocialMediaLink.objects.count(), 3)
        # Each bound on its own selects its own side, which a ``created`` filter
        # cannot do here: ``too_old`` and ``in_range`` share a ``created`` value
        # and ``too_new`` was reported after the upper bound but happened
        # inside it.
        self.assertEqual(
            [row["id"] for row in self._console(before=boundary)],
            [str(too_old.id)],
        )
        self.assertEqual(
            [row["id"] for row in self._console(after=boundary)],
            # Newest event first, which is the queue's own ordering.
            [str(too_new.id), str(in_range.id)],
        )

    def test_console_rejects_the_renamed_away_arguments(self):
        """``createdAfter`` / ``createdBefore`` are gone, not aliased.

        Documented as a breaking rename; asserting it keeps the rename honest
        (a silent alias would quietly keep filtering on ``created``, which is
        the bug the rename exists to fix).
        """
        query = """
            query Legacy($after: DateTime) {
                socialMediaLinks(createdAfter: $after) { id }
            }
        """
        with patch(
            "rosak.permissions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = execute_graphql(
                query,
                variables={"after": datetime(2026, 9, 30, 8, 0, 0).isoformat()},
                user=self.user,
            )
        self.assertIsNotNone(result.errors)
        self.assertIn("createdAfter", str(result.errors))


class ExplicitOrderByTests(SocialLinkFeedOrderingBase):
    """``Meta.ordering`` is now ``["position"]``, so ``-occurred_at, -id`` is
    an EXPLICIT choice on every link surface — not an inherited default.

    ``SocialMediaLink`` inherits ``OrderableTreeNode``, which sets
    ``Meta.ordering = ["position"]`` for sibling sequencing. That default now
    applies to any queryset that forgets to order itself, and it is a perfectly
    plausible order to inherit by accident: a plain queryset would come back
    clustered by insertion, ordered by a column that is global rather than
    grouped by parent. Both link resolvers already ordered explicitly, so this
    is a re-confirmation rather than a fix — but "already correct" is exactly
    the kind of claim that silently stops being true, and the emitted SQL is the
    only place it is visible.
    """

    FEED_ORDER = 'ORDER BY "incident_socialmedialink"."occurred_at" DESC, "incident_socialmedialink"."id" DESC'

    def test_the_public_feed_still_orders_by_occurred_at_desc_id_desc(self):
        day = timezone.now().date()
        self._link("order-explicit-a", occurred_at=datetime.combine(day, time(9)))
        self._link("order-explicit-b", occurred_at=datetime.combine(day, time(12)))

        page_sql = self._feed_capture(page_only=True)[1]

        self.assertIn(self.FEED_ORDER, page_sql)
        # Not the inherited default, in either spelling.
        self.assertNotIn('ORDER BY "incident_socialmedialink"."position"', page_sql)

    def test_a_collapsed_page_still_orders_by_occurred_at_desc_id_desc(self):
        day = timezone.now().date()
        root = self._link("order-root", occurred_at=datetime.combine(day, time(9)))
        self._link(
            "order-child",
            occurred_at=datetime.combine(day, time(10)),
            parent=root,
        )

        page_sql = self._feed_capture(page_only=True, collapseThreads=True)[1]

        self.assertIn(self.FEED_ORDER, page_sql)
        self.assertNotIn('ORDER BY "incident_socialmedialink"."position"', page_sql)

    def test_the_console_queue_still_orders_by_occurred_at_desc_id_desc(self):
        day = timezone.now().date()
        self._link("queue-order-a", occurred_at=datetime.combine(day, time(9)))
        self._link("queue-order-b", occurred_at=datetime.combine(day, time(12)))

        with cachalot_disabled(), CaptureQueriesContext(connection) as ctx:
            self._console()

        queue_sql = "\n".join(
            query["sql"]
            for query in ctx.captured_queries
            if "incident_socialmedialink" in query["sql"]
        )
        self.assertIn(self.FEED_ORDER, queue_sql)
        self.assertNotIn('ORDER BY "incident_socialmedialink"."position"', queue_sql)
