"""Thread grouping for ``SocialMediaLink``: root selection, the depth-1
invariant, ownership, and the ``FeedLinkInput.occurredAt`` wiring.

A thread is its ROOT row: the root has ``thread_id IS NULL``, every member
points at it, and the service (``incident.services.social_link_threads``)
guarantees ``thread`` never points at a member. That is not a nicety — the
scalar field resolvers answer ``isThreadRoot`` with ``thread_id is None`` and
size a thread as ``root.thread_members + 1`` with no second hop, the collapsed
feed filters ``thread__isnull=True`` and treats the survivor as the whole group,
and the batch loaders are keyed by root id. Depth 2 in the database would make
every one of those readers wrong, so the flatten step gets its own test.

Root selection is keyed on ``occurred_at`` (the event), never on ``created``
(the report): a user backdating a link must not end up with the newest event
rendered as the card and the oldest one tucked under it. ``id`` is only the
tie-break, and the tie-break test is here because "usually" is not a total
order.

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


def _thread_of(link_id: int) -> int | None:
    link = SocialMediaLink.objects.get(pk=link_id)
    return link.thread_id


def _assert_depth_one(test: TestCase) -> None:
    """The invariant, asserted over EVERY row: members point at roots, nobody
    points at themselves, and no root is a member of another root's thread."""
    for link in SocialMediaLink.objects.all():
        if link.thread_id is None:
            continue
        parent = SocialMediaLink.objects.get(pk=link.thread_id)
        test.assertNotEqual(link.pk, parent.pk, f"link {link.pk} points at itself")
        test.assertIsNone(
            parent.thread_id,
            f"link {link.pk} points at member {parent.pk} (depth > 1)",
        )


class GroupRootSelectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-thread-root")

    def test_the_earliest_event_becomes_the_root_and_the_rest_point_at_it(self):
        # Selected out of order, and ``created`` runs opposite to ``occurred_at``
        # on purpose: the latest event is the OLDEST submission here, so a root
        # picked on ``created`` would pick the wrong row.
        late = _link(self.user, "https://x.com/lrt/status/301", occurred_at=LATEST)
        early = _link(self.user, "https://x.com/lrt/status/302", occurred_at=EARLIEST)
        middle = _link(self.user, "https://x.com/lrt/status/303", occurred_at=MIDDLE)

        root = _group(
            self.user,
            is_admin=True,
            link_ids=[late.id, early.id, middle.id],
        )

        self.assertEqual(root.id, early.id)
        self.assertIsNone(_thread_of(early.id))
        self.assertEqual(_thread_of(late.id), early.id)
        self.assertEqual(_thread_of(middle.id), early.id)
        self.assertEqual(
            SocialMediaLink.objects.filter(thread=early).count(),
            2,
            msg="the root itself is never its own member",
        )
        _assert_depth_one(self)

    def test_links_sharing_an_event_time_are_broken_by_id(self):
        # Two links reported for the same instant. Without the ``id`` tie-break
        # the root would depend on query/insertion order, so the same selection
        # could produce two different threads.
        first = _link(self.user, "https://x.com/lrt/status/311", occurred_at=EARLIEST)
        second = _link(self.user, "https://x.com/lrt/status/312", occurred_at=EARLIEST)
        lower, higher = sorted((first.id, second.id))

        root = _group(
            self.user,
            is_admin=True,
            link_ids=[higher, lower],
        )

        self.assertEqual(root.id, lower)
        self.assertEqual(_thread_of(higher), lower)
        _assert_depth_one(self)


class GroupIntoExistingThreadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-thread-append")
        self.a = _link(self.user, "https://x.com/lrt/status/321", occurred_at=EARLIEST)
        self.b = _link(self.user, "https://x.com/lrt/status/322", occurred_at=MIDDLE)
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])

    def test_a_member_thread_id_resolves_to_the_real_root(self):
        """``threadId`` may name any link in the thread, not just the root.

        The client reads ids off a rendered thread, so it will hand back a
        member. Appending to the member literally would make
        ``member -> member`` and break every reader that assumes one hop.
        """
        c = _link(self.user, "https://x.com/lrt/status/323", occurred_at=LATEST)
        d = _link(self.user, "https://x.com/lrt/status/324", occurred_at=EARLIEST)

        root = _group(
            self.user,
            is_admin=True,
            link_ids=[c.id, d.id],
            thread_id=self.b.id,
        )

        self.assertEqual(root.id, self.a.id)
        self.assertIsNone(_thread_of(self.a.id))
        self.assertEqual(_thread_of(self.b.id), self.a.id)
        self.assertEqual(_thread_of(c.id), self.a.id)
        self.assertEqual(_thread_of(d.id), self.a.id)
        _assert_depth_one(self)

    def test_merging_two_live_threads_flattens_the_old_roots_members(self):
        """The absorb case: the whole point of the flatten step.

        ``A`` is the root of ``{A, B, X}`` and joins a new group rooted at
        ``Y``. If only the selection moved, ``B`` and ``X`` would stay on ``A``
        while ``A`` is now a member of ``Y`` — depth 2, and ``Y.thread_members``
        would report a thread that is missing two links.
        """
        x = _link(self.user, "https://x.com/lrt/status/331", occurred_at=LATEST)
        _group(self.user, is_admin=True, link_ids=[self.a.id, x.id])

        y = _link(self.user, "https://x.com/lrt/status/332", occurred_at=BEFORE)
        z = _link(self.user, "https://x.com/lrt/status/333", occurred_at=MIDDLE)

        root = _group(
            self.user,
            is_admin=True,
            link_ids=[self.a.id, y.id, z.id],
        )

        self.assertEqual(root.id, y.id)
        self.assertIsNone(_thread_of(y.id))
        # ``B`` and ``X`` came along without being selected: that is the
        # difference between a merge and a nest.
        self.assertEqual(
            set(SocialMediaLink.objects.filter(thread=y).values_list("id", flat=True)),
            {self.a.id, self.b.id, x.id, z.id},
        )
        _assert_depth_one(self)

    def test_promoting_a_member_to_root_detaches_it_from_the_old_thread(self):
        """``A`` is a member of root ``R``; grouping it with ``W`` makes ``A``
        the root, so ``A.thread`` must be cleared or the group would hang off
        a row that is itself inside a thread."""
        r = _link(self.user, "https://x.com/lrt/status/341", occurred_at=BEFORE)
        w = _link(self.user, "https://x.com/lrt/status/342", occurred_at=MIDDLE)
        _group(self.user, is_admin=True, link_ids=[r.id, self.a.id])
        self.assertEqual(_thread_of(self.a.id), r.id)

        root = _group(
            self.user,
            is_admin=True,
            link_ids=[self.a.id, w.id],
        )

        self.assertEqual(root.id, self.a.id)
        self.assertIsNone(_thread_of(self.a.id))
        self.assertEqual(_thread_of(w.id), self.a.id)
        # ``R`` is untouched: it was not selected, so it is still the root of
        # its own (now empty) thread rather than being dragged along.
        self.assertIsNone(_thread_of(r.id))
        _assert_depth_one(self)

    def test_regrouping_a_thread_is_a_no_op_success(self):
        result = _group(
            self.user,
            is_admin=True,
            link_ids=[self.b.id, self.a.id],
        )

        self.assertEqual(result.id, self.a.id)
        self.assertIsNone(_thread_of(self.a.id))
        self.assertEqual(_thread_of(self.b.id), self.a.id)

    def test_grouping_a_single_link_is_a_no_op_success(self):
        root = _group(self.user, is_admin=True, link_ids=[self.b.id])

        self.assertEqual(root.id, self.b.id)
        self.assertIsNone(_thread_of(self.b.id))


class GroupPermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(firebase_id="test-user-thread-owner")
        self.stranger = User.objects.create(firebase_id="test-user-thread-stranger")
        self.admin = User.objects.create(firebase_id="test-user-thread-admin")
        self.mine = _link(
            self.owner, "https://x.com/lrt/status/351", occurred_at=EARLIEST
        )
        self.theirs = _link(
            self.stranger, "https://x.com/lrt/status/352", occurred_at=MIDDLE
        )

    def test_a_submitter_cannot_group_someone_elses_link_and_nothing_is_written(self):
        with self.assertRaises(IncidentServiceError):
            _group(
                self.owner,
                is_admin=False,
                link_ids=[self.mine.id, self.theirs.id],
            )

        # All-or-nothing: the link the caller DOES own must not have been
        # quietly threaded to a root that is now half the stranger's.
        self.assertIsNone(_thread_of(self.mine.id))
        self.assertIsNone(_thread_of(self.theirs.id))
        _assert_depth_one(self)

    def test_a_submitter_cannot_graft_their_link_onto_a_foreign_thread(self):
        with self.assertRaises(IncidentServiceError):
            _group(
                self.owner,
                is_admin=False,
                link_ids=[self.mine.id],
                thread_id=self.theirs.id,
            )

        self.assertIsNone(_thread_of(self.mine.id))
        self.assertIsNone(_thread_of(self.theirs.id))

    def test_a_submitter_can_group_their_own_links(self):
        second = _link(self.owner, "https://x.com/lrt/status/353", occurred_at=MIDDLE)

        root = _group(self.owner, is_admin=False, link_ids=[self.mine.id, second.id])

        self.assertEqual(root.id, self.mine.id)
        self.assertEqual(_thread_of(second.id), self.mine.id)

    def test_an_admin_can_group_any_links_including_a_mixed_selection(self):
        root = _group(
            self.admin,
            is_admin=True,
            link_ids=[self.theirs.id, self.mine.id],
        )

        self.assertEqual(root.id, self.mine.id)
        self.assertEqual(_thread_of(self.theirs.id), self.mine.id)
        _assert_depth_one(self)

    def test_ungrouping_someone_elses_link_is_rejected(self):
        _group(self.admin, is_admin=True, link_ids=[self.mine.id, self.theirs.id])

        with self.assertRaises(IncidentServiceError):
            _ungroup(
                self.owner,
                is_admin=False,
                link_ids=[self.theirs.id],
            )

        self.assertEqual(_thread_of(self.theirs.id), self.mine.id)


class GroupInputValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-thread-inputs")
        self.link = _link(
            self.user, "https://x.com/lrt/status/361", occurred_at=EARLIEST
        )

    def test_an_empty_selection_is_rejected(self):
        with self.assertRaises(IncidentServiceError):
            _group(self.user, is_admin=True, link_ids=[])

    def test_a_repeated_id_is_rejected(self):
        # Not cosmetic: the flatten step acts on everything hanging off a
        # selected link, so a duplicated id hides how wide the write is.
        with self.assertRaises(IncidentServiceError):
            _group(self.user, is_admin=True, link_ids=[self.link.id, self.link.id])

    def test_an_unknown_id_is_rejected_and_nothing_is_written(self):
        with self.assertRaises(IncidentServiceError):
            _group(self.user, is_admin=True, link_ids=[self.link.id, 987654321])

        self.assertIsNone(_thread_of(self.link.id))

    def test_an_unknown_target_thread_is_rejected(self):
        with self.assertRaises(IncidentServiceError):
            _group(
                self.user,
                is_admin=True,
                link_ids=[self.link.id],
                thread_id=987654321,
            )

        self.assertIsNone(_thread_of(self.link.id))

    def test_ungrouping_repeats_is_tolerated(self):
        # Bulk "clear selection" is idempotent; failing a repeat would punish a
        # harmless client-side double click.
        _ungroup(self.user, is_admin=True, link_ids=[self.link.id, self.link.id])

        self.assertIsNone(_thread_of(self.link.id))


class LockOrderTests(TestCase):
    """Every ``select_for_update`` in the service must carry a deterministic
    ``order_by``.

    An unordered lock takes its rows in whatever order the planner returns, and
    two concurrent groupings over overlapping selections that then take the same
    rows in OPPOSITE orders deadlock — Postgres detects the cycle and aborts one
    (40P01), which reaches the client as a 500. The single ``transaction.atomic()``
    around each write bounds that to availability, not correctness, so nothing
    here can catch a deadlock by asserting on state; the only thing testable is
    the presence of the ordering itself, which is why these assert on SQL.
    """

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-thread-lockorder")
        self.a = _link(self.user, "https://x.com/lrt/status/361", occurred_at=EARLIEST)
        self.b = _link(self.user, "https://x.com/lrt/status/362", occurred_at=MIDDLE)
        self.c = _link(self.user, "https://x.com/lrt/status/363", occurred_at=LATEST)

    def _lock_sql(self, run) -> list[str]:
        """Every ``SELECT ... FOR UPDATE`` the run issued, in order."""
        with CaptureQueriesContext(connection) as ctx:
            run()
        return [q["sql"] for q in ctx.captured_queries if "FOR UPDATE" in q["sql"]]

    def test_the_absorbed_member_lock_is_ordered(self):
        # The flatten step's lock is the one that has no natural ordering, so it
        # is the one that must be pinned explicitly. ``pk`` is a total order over
        # the locked set and ``thread_id`` is constant across it (it is the
        # filter key), so it is also the cheapest.
        # ``a`` + ``b`` become a thread FIRST (outside the capture), so the
        # grouping under test has a real member to absorb off ``a`` and really
        # does take the absorbed lock — a grouping with nothing to absorb would
        # still issue the query but would not prove the point.
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])

        locks = self._lock_sql(
            lambda: _group(self.user, is_admin=True, link_ids=[self.a.id, self.c.id])
        )
        self.assertTrue(locks, "expected the grouping to issue row locks")
        absorbed = [sql for sql in locks if '"thread_id" IN' in sql]
        self.assertEqual(
            len(absorbed),
            1,
            msg="expected exactly one absorbed-member lock:\n" + "\n".join(locks),
        )
        self.assertIn(
            'ORDER BY "incident_socialmedialink"."id" ASC',
            absorbed[0],
            msg=(
                "the absorbed-member lock is unordered, so two concurrent "
                "overlapping groupings can lock the same rows in opposite "
                "orders and deadlock:\n" + absorbed[0]
            ),
        )

    def test_the_selection_lock_is_ordered(self):
        # Pre-existing and correct (``occurred_at, id`` IS the root-election
        # rule), pinned so the flatten fix cannot be read as permission to drop
        # the ordering the selection already had.
        locks = self._lock_sql(
            lambda: _group(self.user, is_admin=True, link_ids=[self.a.id, self.c.id])
        )
        selection = [sql for sql in locks if '"id" IN' in sql]
        self.assertEqual(len(selection), 1, msg="\n".join(locks))
        self.assertIn(
            'ORDER BY "incident_socialmedialink"."occurred_at" ASC', selection[0]
        )
        self.assertIn('"incident_socialmedialink"."id" ASC', selection[0])

    def test_the_ungroup_lock_is_ordered(self):
        # Same defect, sibling path: two operators bulk-clearing overlapping
        # selections on the console is the ordinary way to produce it.
        locks = self._lock_sql(
            lambda: _ungroup(self.user, is_admin=True, link_ids=[self.a.id, self.c.id])
        )
        self.assertEqual(len(locks), 1, msg="\n".join(locks))
        self.assertIn(
            'ORDER BY "incident_socialmedialink"."id" ASC',
            locks[0],
            msg=(
                "the ungroup lock is unordered, so two concurrent ungroupings "
                "overlapping on the same links can deadlock:\n" + locks[0]
            ),
        )


class UngroupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-ungroup")
        self.root = _link(
            self.user, "https://x.com/lrt/status/371", occurred_at=EARLIEST
        )
        self.m1 = _link(self.user, "https://x.com/lrt/status/372", occurred_at=MIDDLE)
        self.m2 = _link(self.user, "https://x.com/lrt/status/373", occurred_at=LATEST)
        _group(
            self.user, is_admin=True, link_ids=[self.root.id, self.m1.id, self.m2.id]
        )

    def test_ungrouping_members_leaves_the_root_intact(self):
        _ungroup(self.user, is_admin=True, link_ids=[self.m1.id])

        self.assertIsNone(_thread_of(self.m1.id))
        # The root is untouched and still roots what is left of the thread.
        self.assertIsNone(_thread_of(self.root.id))
        self.assertEqual(_thread_of(self.m2.id), self.root.id)
        self.assertEqual(SocialMediaLink.objects.filter(thread=self.root).count(), 1)
        _assert_depth_one(self)

    def test_ungrouping_the_root_leaves_its_members_attached(self):
        """Asymmetric on purpose: the members were never named in the request.

        They are not orphaned, not deleted and not re-rooted — the thread simply
        continues under a representative that is now itself ungrouped, and
        ungrouping those members afterwards dissolves it.
        """
        _ungroup(self.user, is_admin=True, link_ids=[self.root.id])

        self.assertIsNone(_thread_of(self.root.id))
        self.assertEqual(_thread_of(self.m1.id), self.root.id)
        self.assertEqual(_thread_of(self.m2.id), self.root.id)
        _assert_depth_one(self)

    def test_ungrouping_every_member_leaves_a_singleton_root(self):
        _ungroup(self.user, is_admin=True, link_ids=[self.m1.id, self.m2.id])

        self.assertIsNone(_thread_of(self.root.id))
        self.assertIsNone(_thread_of(self.m1.id))
        self.assertIsNone(_thread_of(self.m2.id))
        self.assertEqual(
            SocialMediaLink.objects.filter(thread__isnull=False).count(), 0
        )


class SelfReferenceTests(TestCase):
    """A link pointing at itself is a single row that reads as its own thread."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-self-ref")
        self.a = _link(self.user, "https://x.com/lrt/status/381", occurred_at=EARLIEST)
        self.b = _link(self.user, "https://x.com/lrt/status/382", occurred_at=MIDDLE)
        _group(self.user, is_admin=True, link_ids=[self.a.id, self.b.id])

    def test_using_a_member_as_the_thread_id_never_makes_it_its_own_root(self):
        for target in (self.a.id, self.b.id):
            root = _group(
                self.user,
                is_admin=True,
                link_ids=[self.a.id, self.b.id],
                thread_id=target,
            )

            self.assertEqual(root.id, self.a.id)
            self.assertIsNone(_thread_of(self.a.id))
            self.assertEqual(_thread_of(self.b.id), self.a.id)

        _assert_depth_one(self)


GROUP_MUTATION = """
    mutation Group($linkIds: [ID!]!, $threadId: ID) {
        groupSocialMediaLinks(linkIds: $linkIds, threadId: $threadId) { ok id }
    }
"""

UNGROUP_MUTATION = """
    mutation Ungroup($linkIds: [ID!]!) {
        ungroupSocialMediaLinks(linkIds: $linkIds) { ok id }
    }
"""


class ThreadGroupingMutationTests(TestCase):
    """The mutation layer's job: the wire shape, the admin flag, and the
    ``id`` the client refetches from."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-thread-mutation")
        self.other = User.objects.create(firebase_id="test-user-thread-mutation-2")
        self.first = _link(
            self.user, "https://x.com/lrt/status/391", occurred_at=EARLIEST
        )
        self.second = _link(
            self.user, "https://x.com/lrt/status/392", occurred_at=MIDDLE
        )
        self.foreign = _link(
            self.other, "https://x.com/lrt/status/393", occurred_at=EARLIEST
        )

    def _group(self, link_ids, *, is_admin=True, thread_id=None):
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=is_admin,
        ):
            return execute_graphql(
                GROUP_MUTATION,
                variables={
                    "linkIds": [str(link_id) for link_id in link_ids],
                    "threadId": str(thread_id) if thread_id is not None else None,
                },
                user=self.user,
            )

    def _ungroup(self, link_ids, *, is_admin=True):
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=is_admin,
        ):
            return execute_graphql(
                UNGROUP_MUTATION,
                variables={"linkIds": [str(link_id) for link_id in link_ids]},
                user=self.user,
            )

    def test_grouping_returns_the_root_id_so_the_client_can_refresh_one_thread(self):
        result = self._group([self.second.id, self.first.id])

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["groupSocialMediaLinks"]["ok"])
        # The root's id, as an int (GenericMutationReturn.id is int | None), so
        # the client can refetch exactly that thread.
        self.assertEqual(result.data["groupSocialMediaLinks"]["id"], self.first.id)
        self.assertEqual(_thread_of(self.second.id), self.first.id)

    def test_a_non_admin_cannot_group_a_foreign_link_through_the_mutation(self):
        result = self._group([self.first.id, self.foreign.id], is_admin=False)

        self.assertIsNotNone(result.errors)
        # Nothing written, including the caller's own link.
        self.assertIsNone(_thread_of(self.first.id))
        self.assertIsNone(_thread_of(self.foreign.id))

    def test_ungrouping_returns_ok_and_detaches_only_the_named_links(self):
        self._group([self.first.id, self.second.id])

        result = self._ungroup([self.second.id])

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["ungroupSocialMediaLinks"]["ok"])
        self.assertIsNone(_thread_of(self.second.id))
        self.assertIsNone(_thread_of(self.first.id))


class FeedLinkOccurredAtTests(TestCase):
    """``FeedLinkInput.occurredAt`` was declared and unwired — a schema field
    that silently did nothing. These pin the fixed contract: a value is stored
    verbatim, an omission falls back to the NOT NULL column default, and the
    canonical-URL dedup is untouched by either."""

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
