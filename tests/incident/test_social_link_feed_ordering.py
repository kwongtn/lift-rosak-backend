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
* ``collapseThreads`` — roots only, ``totalCount`` over roots, the flat default
  unchanged, and no collapse under ``mine``;
* the console queue's ``occurredAfter`` / ``occurredBefore`` and its ordering.

Runs under plain ``django.test.TestCase`` + ``asgiref.sync.async_to_sync`` and
deliberately does NOT import pytest: pytest is not installed in the app image, so
a pytest-based file here is uncollectable dead code.
"""

import base64
import copy
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.test import TestCase
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
        $collapseThreads: Boolean
    ) {
        publicSocialMediaLinks(
            first: $first
            after: $after
            mine: $mine
            currentServiceDayOnly: $currentServiceDayOnly
            lastWeekOnly: $lastWeekOnly
            alignPageToDay: $alignPageToDay
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

    def test_collapsed_thread_enters_the_window_by_a_member_even_when_its_root_is_out(
        self,
    ):
        """A collapsed card is admitted by the WHOLE thread, not by its root.

        Grouping elects the EARLIEST link as root, so the root is the thread's
        first event and every member is LATER than it. That makes "the root is
        outside the window while a member is inside it" the ORDINARY shape for
        any conversation that opened before the window and got a follow-up
        inside it — it needs no ``occurredAt`` edit to happen and is not an edge
        case. A root-keyed window then drops the whole thread from a feed the
        member belongs in, and the member becomes unreachable: the collapsed
        surface renders the ROOT, and the root was filtered out.

        The window asks "what happened today". A thread is in it if any part of
        it happened today.
        """
        boundary = service_day_start(timezone.now())

        # Conversation opened yesterday, someone posts a follow-up today.
        root = self._link("window-root-stale", occurred_at=boundary - timedelta(days=1))
        member = self._link(
            "window-member-fresh", occurred_at=boundary + timedelta(hours=6)
        )
        SocialMediaLink.objects.filter(pk=member.pk).update(thread=root)

        # The root-keyed reading would return an empty page; only the thread-wide
        # reading returns anything. Assert the shape so the test cannot pass
        # vacuously on a fixture where the two readings happen to agree.
        self.assertLess(root.occurred_at, boundary)
        self.assertGreaterEqual(member.occurred_at, boundary)

        collapsed = self._feed(
            first=10, currentServiceDayOnly=True, collapseThreads=True
        )
        self.assertEqual(self._ids(collapsed), [str(root.id)])
        self.assertEqual(collapsed["totalCount"], 1)

        # The member rides inside that card rather than being dropped from the
        # feed, which is the difference between "not listed" and "not reachable".
        # The FLAT feed still judges the member on its own ``occurred_at`` — the
        # widening belongs to collapse, it does not rewrite anyone's date — and
        # returns the member as its own row.
        flat = self._feed(first=10, currentServiceDayOnly=True)
        self.assertEqual(self._ids(flat), [str(member.id)])

    def test_a_thread_entirely_outside_the_window_stays_out(self):
        # The converse guard: widening must not admit threads with nothing in
        # the window, or the flag would stop being a filter at all.
        boundary = service_day_start(timezone.now())
        # Both beyond the 7-day window (which reaches back six days).
        root = self._link("stale-root", occurred_at=boundary - timedelta(days=10))
        member = self._link("stale-member", occurred_at=boundary - timedelta(days=12))
        SocialMediaLink.objects.filter(pk=member.pk).update(thread=root)

        collapsed = self._feed(first=10, lastWeekOnly=True, collapseThreads=True)

        # Only the root is even a candidate, and neither it nor its member is in
        # the window — so the widened predicate must not rescue it.
        self.assertLess(root.occurred_at, last_week_start(timezone.now()))
        self.assertEqual(self._ids(collapsed), [])
        self.assertEqual(collapsed["totalCount"], 0)

    def test_a_root_in_window_keeps_its_thread_even_if_no_member_is(self):
        # Widening is additive, never restrictive: a root inside the window is
        # admitted on its own ``occurred_at`` exactly as the flat feed would.
        boundary = service_day_start(timezone.now())
        root = self._link("fresh-root", occurred_at=boundary + timedelta(hours=2))
        member = self._link("older-member", occurred_at=boundary - timedelta(days=10))
        SocialMediaLink.objects.filter(pk=member.pk).update(thread=root)

        collapsed = self._feed(first=10, lastWeekOnly=True, collapseThreads=True)

        self.assertLess(member.occurred_at, last_week_start(timezone.now()))
        self.assertEqual(self._ids(collapsed), [str(root.id)])

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
    def _thread_fixture(self):
        """Two threads whose members are interleaved by ``occurred_at``.

        Ordering by event time is what breaks client-side grouping: the members
        of a thread are not adjacent, so a flat page cannot be regrouped after
        the fact. ``root_a``/``root_b`` are the roots (earliest event of their
        group, matching the grouping service's root selection).
        """
        day = timezone.now().date()

        def at(hour):
            return datetime.combine(day, time(hour, 0))

        root_a = self._link("thread-root-a", occurred_at=at(9))
        solo = self._link("thread-solo", occurred_at=at(10))
        member_a = self._link("thread-member-a", occurred_at=at(11), thread=root_a)
        root_b = self._link("thread-root-b", occurred_at=at(12))
        member_b = self._link("thread-member-b", occurred_at=at(13), thread=root_b)
        return root_a, solo, member_a, root_b, member_b

    def test_collapse_returns_only_roots_and_counts_them(self):
        root_a, solo, member_a, root_b, member_b = self._thread_fixture()

        flat = self._feed(first=10, collapseThreads=False)
        collapsed = self._feed(first=10, collapseThreads=True)

        # Members are not adjacent in the flat order — the premise for
        # collapsing at all.
        self.assertEqual(
            self._ids(flat),
            [
                str(member_b.id),
                str(root_b.id),
                str(member_a.id),
                str(solo.id),
                str(root_a.id),
            ],
        )
        self.assertEqual(flat["totalCount"], 5)

        self.assertEqual(
            self._ids(collapsed), [str(root_b.id), str(solo.id), str(root_a.id)]
        )
        # "M of M" counts roots, not rows that were filtered away.
        self.assertEqual(collapsed["totalCount"], 3)

        returned = {int(node_id) for node_id in self._ids(collapsed)}
        self.assertNotIn(member_a.id, returned)
        self.assertNotIn(member_b.id, returned)
        self.assertTrue(
            all(SocialMediaLink.objects.get(pk=pk).thread_id is None for pk in returned)
        )
        # The members themselves are untouched in storage — this is a read-side
        # narrowing, not a re-parenting.
        self.assertEqual(SocialMediaLink.objects.count(), 5)
        self.assertIsNotNone(SocialMediaLink.objects.get(pk=member_a.id).thread_id)

    def test_default_flat_feed_is_identical_to_explicit_false(self):
        self._thread_fixture()

        omitted = self._feed(first=10)
        explicit = self._feed(first=10, collapseThreads=False)

        # "Byte-identical to today's behaviour": same ids, same cursors, same
        # count, same page info.
        self.assertEqual(omitted, explicit)
        self.assertEqual(omitted["totalCount"], 5)
        self.assertFalse(omitted["pageInfo"]["hasNextPage"])

    def test_collapse_is_ignored_under_mine(self):
        root_a, solo, member_a, root_b, member_b = self._thread_fixture()
        other = User.objects.create(firebase_id="feed-ordering-other")
        stranger = self._link(
            "thread-stranger",
            occurred_at=datetime.combine(timezone.now().date(), time(14, 0)),
            user=other,
        )

        flat_mine = self._feed(
            first=10, mine=True, collapseThreads=False, user=self.user
        )
        collapsed_mine = self._feed(
            first=10, mine=True, collapseThreads=True, user=self.user
        )

        # "My Submitted Links" is a personal list: every row the caller
        # submitted is a row they expect to find, members included.
        own_ids = {
            str(root_a.id),
            str(solo.id),
            str(member_a.id),
            str(root_b.id),
            str(member_b.id),
        }
        self.assertEqual(flat_mine, collapsed_mine)
        self.assertEqual(set(self._ids(collapsed_mine)), own_ids)
        self.assertEqual(collapsed_mine["totalCount"], 5)
        self.assertNotIn(str(stranger.id), self._ids(collapsed_mine))


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
