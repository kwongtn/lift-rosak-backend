"""Regression tests for the incident 0032 official-link auto-approval backfill.

Official-post ingestion now writes ``LIVE`` (auto-published by policy). Migration
0032 flips the rows the old policy left parked in ``PENDING_APPROVAL`` — and only
those: a ``HIDDEN`` row is a moderation decision, so the backfill must never
move it, and a community link keeps its pending state.

Like ``test_social_link_occurred_at_backfill.py`` (whose direct-call pattern this
mirrors — the interesting behaviour is the single ``UPDATE`` the migration
emits), these tests call the migration's own module-level function against real
rows in the live test database rather than replaying the executor. A full schema
rebuild would exercise the same one statement.

The migration is deliberately irreversible (``RunPython.noop`` reverse): a
reverse that re-pended every row would resurrect the old policy. That is
asserted below, so a future "add a reverse" change is a deliberate decision
rather than a silent resurrection.
"""

import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from common.models import User
from incident.enums import SocialMediaLinkStatus
from incident.models import SocialMediaLink

migration_0032 = importlib.import_module(
    "incident.migrations.0032_autoapprove_official_links"
)


def _link(user, *, status, is_automated):
    return SocialMediaLink.objects.create(
        url=f"https://example.com/{status}-{is_automated}-{user.id}",
        title="backfill",
        user=user,
        status=status,
        is_automated=is_automated,
    )


class AutoApproveOfficialLinksBackfillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-0032-backfill")

    def test_only_automated_pending_rows_are_flipped_to_live(self):
        auto_pending = _link(
            self.user,
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
            is_automated=True,
        )
        auto_hidden = _link(
            self.user,
            status=SocialMediaLinkStatus.HIDDEN,
            is_automated=True,
        )
        auto_live = _link(
            self.user,
            status=SocialMediaLinkStatus.LIVE,
            is_automated=True,
        )
        community_pending = _link(
            self.user,
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
            is_automated=False,
        )
        community_hidden = _link(
            self.user,
            status=SocialMediaLinkStatus.HIDDEN,
            is_automated=False,
        )

        migration_0032.approve_pending_official_links(django_apps, None)

        for link in (
            auto_pending,
            auto_hidden,
            auto_live,
            community_pending,
            community_hidden,
        ):
            link.refresh_from_db()

        # The policy gap: approved-by-us-but-parked automated rows go public.
        self.assertEqual(auto_pending.status, SocialMediaLinkStatus.LIVE)
        # HIDDEN is a moderation decision, never a lifecycle stage — untouched
        # even on an automated row.
        self.assertEqual(auto_hidden.status, SocialMediaLinkStatus.HIDDEN)
        # A LIVE row is already where the policy wants it; the UPDATE is a no-op.
        self.assertEqual(auto_live.status, SocialMediaLinkStatus.LIVE)
        # Community links are out of scope entirely.
        self.assertEqual(
            community_pending.status, SocialMediaLinkStatus.PENDING_APPROVAL
        )
        self.assertEqual(community_hidden.status, SocialMediaLinkStatus.HIDDEN)

    def test_the_backfill_is_idempotent(self):
        auto_pending = _link(
            self.user,
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
            is_automated=True,
        )

        migration_0032.approve_pending_official_links(django_apps, None)
        migration_0032.approve_pending_official_links(django_apps, None)

        auto_pending.refresh_from_db()
        self.assertEqual(auto_pending.status, SocialMediaLinkStatus.LIVE)
