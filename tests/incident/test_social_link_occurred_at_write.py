"""Write-path tests for ``SocialMediaLink.occurred_at`` and the visibility rule.

``occurred_at`` is the "when did this happen" instant the card renders and every
feed ordering is built on; ``created`` stays the provenance column for moderation
("when did someone report this?"). These tests pin the *write* contract the
service layer implements, which is deliberately not "assign what you were given":

* **submit** — omitted / explicit null both let the column default fire, because
  the column is NOT NULL. Passing ``None`` into the INSERT would raise
  ``IntegrityError``, so the kwarg has to be absent, not null.
* **update** — three states that mean three *different* things: omitted leaves
  the value alone, a value sets it, explicit null resets it to ``created``
  ("this happened when it was reported"). Collapsing any two of them silently
  rewrites the displayed time, which is why the omitted state travels as a
  sentinel rather than ``None``.

Runs under plain ``django.test.TestCase`` + ``asgiref.sync.async_to_sync`` (the
services are coroutines) and deliberately does NOT import pytest: pytest is not
installed in the app image, so a pytest-based file here is uncollectable dead
code. ``occurred_at`` is NOT NULL, so a silent regression here is a 500 on
write, not a wrong-looking card.
"""

import copy
import datetime as dt
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.test import TestCase
from dotmap import DotMap

from common.models import User
from incident.enums import SocialMediaLinkStatus
from incident.models import SocialMediaLink
from incident.services import (
    SocialMediaLinkWrite,
    submit_social_media_link,
    update_social_media_link,
)
from incident.services.errors import IncidentServiceError
from incident.services.social_link_visibility import is_publicly_visible
from rosak.context import ContextLoaders
from rosak.schema import schema

# A fixed event instant, deliberately NOT the submission time so "stored
# verbatim" cannot pass by accident.
EVENT_AT = datetime(2026, 9, 25, 8, 30, 0)

# The services are coroutines; these tests are sync so ``setUp``/assertions can
# touch the ORM directly (an async TestCase method cannot).
_submit = async_to_sync(submit_social_media_link)
_update = async_to_sync(update_social_media_link)


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


def _link(user: User, **overrides) -> SocialMediaLink:
    fields = {"url": "https://x.com/lrt/status/900000000000000000", "user": user}
    fields.update(overrides)
    return SocialMediaLink.objects.create(**fields)


class SubmitOccurredAtTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-occurred-write")

    def test_an_explicit_event_time_is_stored_verbatim(self):
        link = _submit(
            self.user,
            is_admin=True,
            write=SocialMediaLinkWrite(
                url="https://x.com/lrt/status/100", occurred_at=EVENT_AT
            ),
        )
        link.refresh_from_db()

        self.assertEqual(link.occurred_at, EVENT_AT)
        # Byte-identical, not merely equal to the right minute.
        self.assertEqual(link.occurred_at.isoformat(), "2026-09-25T08:30:00")
        # And it is genuinely a different column from the submission time.
        self.assertNotEqual(link.occurred_at, link.created)

    def test_omitting_the_event_time_falls_back_to_now_rather_than_null(self):
        before = dt.datetime.now()
        link = _submit(
            self.user,
            is_admin=True,
            write=SocialMediaLinkWrite(url="https://x.com/lrt/status/101"),
        )
        after = dt.datetime.now()
        link.refresh_from_db()

        # The default fired instead of a NULL sneaking in (NOT NULL).
        self.assertIsNotNone(link.occurred_at)
        self.assertGreaterEqual(link.occurred_at, before)
        self.assertLessEqual(link.occurred_at, after)
        # ``created`` is generated in the same INSERT, so the two agree to well
        # under a second: a submit with no event time reads as "it happened
        # just now", which is what the UI shows.
        self.assertLess(abs(link.occurred_at - link.created), timedelta(seconds=1))

    def test_an_explicit_null_on_submit_also_falls_back_to_now(self):
        # Some(None) on submit is not a "clear it" request: the column cannot
        # hold null, so it must degrade to the model default rather than raise.
        link = _submit(
            self.user,
            is_admin=True,
            write=SocialMediaLinkWrite(
                url="https://x.com/lrt/status/102", occurred_at=None
            ),
        )
        link.refresh_from_db()

        self.assertIsNotNone(link.occurred_at)
        self.assertLess(abs(link.occurred_at - link.created), timedelta(seconds=1))

    def test_an_aware_event_time_is_stored_as_naive_local_not_re_shifted(self):
        # Strawberry hands us an aware datetime (GraphQL DateTime). With
        # USE_TZ = False the ORM converts it to naive local on the way in; the
        # service must pass it through untouched, because a make_aware/astimezone
        # here would shift every caller-supplied time by a second +08:00 —
        # invisible at minute precision, wrong by a day near midnight.
        aware = datetime(2026, 9, 25, 0, 30, tzinfo=UTC)
        link = _submit(
            self.user,
            is_admin=True,
            write=SocialMediaLinkWrite(
                url="https://x.com/lrt/status/103", occurred_at=aware
            ),
        )
        link.refresh_from_db()

        self.assertIsNone(link.occurred_at.tzinfo)
        # 00:30 UTC -> 08:30 local. Not 00:30 (unconverted) and not 16:30
        # (converted twice).
        self.assertEqual(link.occurred_at, dt.datetime(2026, 9, 25, 8, 30))
        self.assertNotEqual(link.occurred_at, dt.datetime(2026, 9, 25, 0, 30))


class UpdateOccurredAtTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-occurred-update")
        self.link = _link(self.user, occurred_at=EVENT_AT)

    def _update_as_admin(self, **write_kwargs) -> SocialMediaLink:
        return _update(
            self.user,
            is_admin=True,
            link_id=self.link.id,
            write=SocialMediaLinkWrite(url=self.link.url, **write_kwargs),
        )

    def test_omitting_the_field_leaves_the_stored_event_time_alone(self):
        # The REPLACE-NOT-PATCH trap: every other field of the write is applied
        # unconditionally, so if the omitted state collapsed into "set to
        # created" then any caller re-sending a payload without ``occurredAt``
        # would silently restamp the event as "happened when reported".
        updated = self._update_as_admin(title="Restamped title")
        updated.refresh_from_db()

        self.assertEqual(updated.occurred_at, EVENT_AT)
        self.assertNotEqual(updated.occurred_at, updated.created)
        # The rest of the replace still happened, i.e. this is not a no-op test.
        self.assertEqual(updated.title, "Restamped title")

    def test_a_new_event_time_is_applied(self):
        later = datetime(2026, 9, 26, 21, 15, 0)
        updated = self._update_as_admin(occurred_at=later)
        updated.refresh_from_db()

        self.assertEqual(updated.occurred_at, later)
        self.assertNotEqual(updated.occurred_at, EVENT_AT)

    def test_an_explicit_null_resets_to_the_submission_time(self):
        # The documented escape hatch: "this happened when it was reported".
        # ``created`` is the only always-present non-null value (posted_at is
        # provider-only and NULL on every community link).
        updated = self._update_as_admin(occurred_at=None)
        updated.refresh_from_db()

        self.assertEqual(updated.occurred_at, updated.created)
        self.assertNotEqual(updated.occurred_at, EVENT_AT)

    def test_a_non_admin_editing_their_own_link_keeps_the_tri_state(self):
        # Own-link edits go back into the approval queue, which rewrites
        # ``status`` — the event time must be untouched by that side effect.
        updated = _update(
            self.user,
            is_admin=False,
            link_id=self.link.id,
            write=SocialMediaLinkWrite(url=self.link.url),
        )
        updated.refresh_from_db()

        self.assertEqual(updated.status, SocialMediaLinkStatus.PENDING_APPROVAL)
        self.assertEqual(updated.occurred_at, EVENT_AT)

    def test_a_non_admin_still_cannot_edit_someone_elses_link(self):
        other = User.objects.create(firebase_id="test-user-occurred-other")
        with self.assertRaises(IncidentServiceError):
            _update(
                other,
                is_admin=False,
                link_id=self.link.id,
                write=SocialMediaLinkWrite(
                    url="https://x.com/lrt/status/hijack", occurred_at=EVENT_AT
                ),
            )
        # Rejected means untouched.
        self.link.refresh_from_db()
        self.assertEqual(self.link.url, "https://x.com/lrt/status/900000000000000000")
        self.assertEqual(self.link.occurred_at, EVENT_AT)

    def test_an_admin_still_can_edit_someone_elses_link(self):
        other = User.objects.create(firebase_id="test-user-occurred-other-admin")
        later = datetime(2026, 9, 27, 7, 0, 0)
        updated = _update(
            other,
            is_admin=True,
            link_id=self.link.id,
            write=SocialMediaLinkWrite(url=self.link.url, occurred_at=later),
        )
        updated.refresh_from_db()

        self.assertEqual(updated.occurred_at, later)


class PublicVisibilityTests(TestCase):
    """The rule extracted from the public feed's two inline exclusion gates.

    These pin the *row-level* predicate, not the queryset. The resolver keeps
    its inline ``.exclude(...)`` pair until the threading work replaces them, so
    the two must currently agree on every combination of status/is_automated.
    """

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-occurred-visible")

    def test_a_live_link_is_public(self):
        self.assertTrue(is_publicly_visible(_link(self.user, status="live")))

    def test_hidden_is_never_public(self):
        # Absolute: it beats an explicit ``status: HIDDEN`` narrowing, which is
        # why the predicate is applied AFTER narrowing rather than instead of it.
        self.assertFalse(
            is_publicly_visible(_link(self.user, status=SocialMediaLinkStatus.HIDDEN))
        )
        self.assertFalse(
            is_publicly_visible(
                _link(self.user, status=SocialMediaLinkStatus.HIDDEN, is_automated=True)
            )
        )

    def test_an_unapproved_automated_post_is_not_public(self):
        self.assertFalse(
            is_publicly_visible(
                _link(
                    self.user,
                    status=SocialMediaLinkStatus.PENDING_APPROVAL,
                    is_automated=True,
                )
            )
        )

    def test_a_community_link_awaiting_approval_is_still_public(self):
        # Scoped to is_automated on purpose: hiding pending rows wholesale would
        # hide hand-submitted reports too. It surfaces with its pending pill.
        self.assertTrue(
            is_publicly_visible(
                _link(
                    self.user,
                    status=SocialMediaLinkStatus.PENDING_APPROVAL,
                    is_automated=False,
                )
            )
        )

    def test_an_approved_automated_post_is_public(self):
        self.assertTrue(
            is_publicly_visible(
                _link(
                    self.user,
                    status=SocialMediaLinkStatus.LIVE,
                    is_automated=True,
                )
            )
        )


SUBMIT_MUTATION = """
    mutation Submit($input: SocialMediaLinkInput!) {
        submitSocialMediaLink(input: $input) { ok }
    }
"""

UPDATE_MUTATION = """
    mutation Update($linkId: ID!, $input: SocialMediaLinkInput!) {
        updateSocialMediaLink(socialMediaLinkId: $linkId, input: $input) { ok }
    }
"""


class OccurredAtMutationTriStateTests(TestCase):
    """The mutation layer's job: keep the three GraphQL states apart on the wire.

    Everything here goes through the real schema, because the mapping is the
    fragile part — ``Maybe``/``Some`` arrive from Strawberry's coercion and a
    naive ``input.occurred_at.value`` (without the UNSET guard) raises
    ``AttributeError`` on an omitted field, while a naive
    ``input.occurred_at or None`` collapses "omitted" into "reset to created"
    and restamps the event time on every partial re-send.
    """

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-occurred-mutation")
        self.link = _link(self.user, occurred_at=EVENT_AT)

    def _submit(self, input_payload: dict):
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=True,
        ):
            return execute_graphql(
                SUBMIT_MUTATION,
                variables={"input": input_payload},
                user=self.user,
            )

    def _update(self, input_payload: dict):
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=True,
        ):
            return execute_graphql(
                UPDATE_MUTATION,
                variables={"linkId": str(self.link.id), "input": input_payload},
                user=self.user,
            )

    def test_submit_stores_the_supplied_event_time(self):
        result = self._submit(
            {
                "url": "https://x.com/lrt/status/200",
                "occurredAt": "2026-09-25T08:30:00+00:00",
            }
        )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["submitSocialMediaLink"]["ok"])
        link = SocialMediaLink.objects.get(url="https://x.com/lrt/status/200")
        # 08:30 UTC -> 16:30 local (+08:00), stored naive — the ORM's
        # conversion, applied once.
        self.assertIsNone(link.occurred_at.tzinfo)
        self.assertEqual(link.occurred_at, dt.datetime(2026, 9, 25, 16, 30))

    def test_submit_without_occurred_at_lands_on_the_submission_time(self):
        result = self._submit({"url": "https://x.com/lrt/status/201"})

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        link = SocialMediaLink.objects.get(url="https://x.com/lrt/status/201")
        self.assertLess(abs(link.occurred_at - link.created), timedelta(seconds=1))

    def test_submit_with_an_explicit_null_also_lands_on_the_submission_time(self):
        # The column cannot hold null, so Some(None) must degrade to the model
        # default rather than raise IntegrityError on a 500.
        result = self._submit(
            {"url": "https://x.com/lrt/status/202", "occurredAt": None}
        )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        link = SocialMediaLink.objects.get(url="https://x.com/lrt/status/202")
        self.assertIsNotNone(link.occurred_at)
        self.assertLess(abs(link.occurred_at - link.created), timedelta(seconds=1))

    def test_update_omitting_occurred_at_does_not_touch_it(self):
        result = self._update({"url": self.link.url, "title": "Touched title only"})

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.link.refresh_from_db()
        self.assertEqual(self.link.occurred_at, EVENT_AT)
        self.assertEqual(self.link.title, "Touched title only")

    def test_update_with_a_value_replaces_it(self):
        result = self._update(
            {
                "url": self.link.url,
                "occurredAt": "2026-09-26T05:00:00+00:00",
            }
        )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.link.refresh_from_db()
        self.assertEqual(self.link.occurred_at, dt.datetime(2026, 9, 26, 13, 0))

    def test_update_with_an_explicit_null_resets_to_the_submission_time(self):
        result = self._update({"url": self.link.url, "occurredAt": None})

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.link.refresh_from_db()
        self.assertEqual(self.link.occurred_at, self.link.created)
        self.assertNotEqual(self.link.occurred_at, EVENT_AT)
