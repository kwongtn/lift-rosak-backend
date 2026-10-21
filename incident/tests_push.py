"""Web push: token registration, MAJOR-incident alerts and the approval trigger.

Nothing here reaches FCM: every test that could send patches
``messaging.send_each_for_multicast``, and the approval tests patch the task's
``delay``.
"""

import random
import string
from datetime import datetime
from unittest.mock import call, patch

from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from firebase_admin import exceptions, messaging

from common.models import User
from incident import services
from incident.enums import CalendarIncidentSeverity, CalendarIncidentStatus
from incident.models import CalendarIncident, PushSubscription
from incident.services import push
from incident.tasks import notify_push_subscribers
from incident.tests import execute_graphql
from operation.models import Line

#: The cooldown needs a real cache; local DEBUG runs use DummyCache.
LOCMEM_CACHES = {
    **settings.CACHES,
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "incident-push-tests",
    },
}

REGISTER = """
mutation ($token: String!, $lineIds: [ID!]!) {
  registerPushToken(token: $token, lineIds: $lineIds) { ok }
}
"""
UNREGISTER = """
mutation ($token: String!) { unregisterPushToken(token: $token) { ok } }
"""
SUBSCRIPTION = """
query ($token: String!) { pushSubscription(token: $token) { token lines { code } } }
"""


def _line(code: str) -> Line:
    return Line.objects.create(
        code=code, display_name=f"{code} line", display_color="#123456"
    )


def _subscribe(user: User, token: str, *lines: Line) -> PushSubscription:
    subscription = PushSubscription.objects.create(user=user, token=token)
    subscription.lines.set(lines)
    return subscription


def _batch(message: messaging.MulticastMessage, failures=None):
    """FCM's answer for ``message``: delivered, unless ``failures[token]`` says."""
    failures = failures or {}
    return messaging.BatchResponse(
        [
            messaging.SendResponse(
                None if token in failures else {"name": f"projects/p/messages/{i}"},
                failures.get(token),
            )
            for i, token in enumerate(message.tokens)
        ]
    )


class PushRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create(firebase_id="push-alice")
        cls.bob = User.objects.create(firebase_id="push-bob")
        cls.kjl = _line("KJL")
        cls.agl = _line("AGL")

    def register(self, user, token, line_ids):
        return execute_graphql(
            REGISTER, {"token": token, "lineIds": [str(i) for i in line_ids]}, user
        )

    def lines_of(self, token):
        return set(PushSubscription.objects.get(token=token).lines.all())

    def test_register_creates_the_subscription(self):
        result = self.register(self.alice, "tok-1", [self.kjl.pk])

        self.assertIsNone(result.errors)
        self.assertTrue(result.data["registerPushToken"]["ok"])
        subscription = PushSubscription.objects.get(token="tok-1")
        self.assertEqual(subscription.user, self.alice)
        self.assertEqual(self.lines_of("tok-1"), {self.kjl})

    def test_register_again_upserts_and_replaces_the_lines(self):
        self.register(self.alice, "tok-1", [self.kjl.pk])
        result = self.register(self.alice, "tok-1", [self.agl.pk, self.agl.pk])

        self.assertIsNone(result.errors)
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.assertEqual(self.lines_of("tok-1"), {self.agl})

    def test_register_reowns_a_token_registered_by_another_account(self):
        self.register(self.alice, "tok-1", [self.kjl.pk])
        result = self.register(self.bob, "tok-1", [self.agl.pk])

        self.assertIsNone(result.errors)
        subscription = PushSubscription.objects.get()
        self.assertEqual(subscription.user, self.bob)
        self.assertEqual(self.lines_of("tok-1"), {self.agl})

    def test_register_rejects_an_anonymous_caller(self):
        result = self.register(None, "tok-1", [self.kjl.pk])

        self.assertEqual(result.errors[0].message, "You are not logged in.")
        self.assertFalse(PushSubscription.objects.exists())

    def test_register_rejects_unknown_or_non_numeric_line_ids(self):
        unknown = Line.objects.order_by("-pk").first().pk + 1000
        too_many = range(1, push.MAX_LINE_IDS + 2)
        cases = [
            ([self.kjl.pk, unknown], f"Unknown line ids: {unknown}."),
            ([2**63], f"Unknown line ids: {2**63}."),  # past bigint, no DataError
            (["KJL"], "lineIds must be numeric line ids."),
            (too_many, f"lineIds must hold at most {push.MAX_LINE_IDS} distinct ids."),
        ]
        for line_ids, message in cases:
            with self.subTest(line_ids=line_ids):
                result = self.register(self.alice, "tok-1", line_ids)

                self.assertEqual(result.errors[0].message, message)
                self.assertFalse(PushSubscription.objects.exists())

    def test_register_rejects_a_malformed_token(self):
        for token in ("   ", "x" * (push.MAX_TOKEN_LENGTH + 1), "tök"):
            with self.subTest(token=token[:8]):
                result = self.register(self.alice, token, [self.kjl.pk])

                self.assertEqual(
                    result.errors[0].message,
                    f"token must be 1 to {push.MAX_TOKEN_LENGTH} ASCII characters.",
                )
                self.assertFalse(PushSubscription.objects.exists())

    def test_register_stores_a_max_length_token_under_the_unique_index(self):
        # Random characters do not compress, so this is the real index row size.
        token = "".join(
            random.Random(0).choices(
                string.ascii_letters + string.digits, k=push.MAX_TOKEN_LENGTH
            )
        )

        result = self.register(self.alice, token, [self.kjl.pk])

        self.assertIsNone(result.errors)
        self.assertTrue(PushSubscription.objects.filter(token=token).exists())

    def test_registering_past_the_per_user_cap_evicts_the_stalest_token(self):
        self.register(self.bob, "bob-1", [self.kjl.pk])
        for i in range(push.MAX_TOKENS_PER_USER):
            self.register(self.alice, f"tok-{i}", [self.kjl.pk])
        self.register(self.alice, "tok-0", [self.agl.pk])  # tok-1 is stalest now

        result = self.register(self.alice, "tok-new", [self.kjl.pk])

        self.assertIsNone(result.errors)
        tokens = set(
            PushSubscription.objects.filter(user=self.alice).values_list(
                "token", flat=True
            )
        )
        self.assertEqual(len(tokens), push.MAX_TOKENS_PER_USER)
        self.assertNotIn("tok-1", tokens)
        self.assertLessEqual({"tok-0", "tok-new"}, tokens)
        self.assertTrue(PushSubscription.objects.filter(token="bob-1").exists())

    def test_unregister_deletes_only_the_callers_row(self):
        _subscribe(self.alice, "tok-1", self.kjl)

        by_bob = execute_graphql(UNREGISTER, {"token": "tok-1"}, self.bob)
        self.assertTrue(by_bob.data["unregisterPushToken"]["ok"])
        self.assertTrue(PushSubscription.objects.filter(token="tok-1").exists())

        for _ in range(2):  # the second call finds nothing and is still ok
            by_alice = execute_graphql(UNREGISTER, {"token": "tok-1"}, self.alice)
            self.assertIsNone(by_alice.errors)
            self.assertTrue(by_alice.data["unregisterPushToken"]["ok"])
        self.assertFalse(PushSubscription.objects.exists())

    def test_push_subscription_returns_only_the_callers_own_row(self):
        _subscribe(self.alice, "tok-1", self.kjl, self.agl)

        mine = execute_graphql(SUBSCRIPTION, {"token": "tok-1"}, self.alice)
        theirs = execute_graphql(SUBSCRIPTION, {"token": "tok-1"}, self.bob)
        anonymous = execute_graphql(SUBSCRIPTION, {"token": "tok-1"}, None)

        self.assertIsNone(mine.errors)
        self.assertEqual(
            mine.data["pushSubscription"],
            {"token": "tok-1", "lines": [{"code": "AGL"}, {"code": "KJL"}]},
        )
        self.assertIsNone(theirs.errors)
        self.assertIsNone(theirs.data["pushSubscription"])
        self.assertEqual(anonymous.errors[0].message, "You are not logged in.")


@override_settings(CACHES=LOCMEM_CACHES)
class NotifyMajorIncidentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = user = User.objects.create(firebase_id="push-subscriber")
        cls.kjl = _line("KJL")
        cls.agl = _line("AGL")
        cls.spl = _line("SPL")
        cls.incident = CalendarIncident.objects.create(
            title="Signal fault",
            brief="Trains held at KL Sentral",
            severity=CalendarIncidentSeverity.MAJOR,
            status=CalendarIncidentStatus.LIVE,
            start_datetime=datetime(2026, 10, 22, 8, 0),
        )
        cls.incident.lines.set([cls.kjl, cls.agl])
        _subscribe(user, "tok-kjl", cls.kjl)
        _subscribe(user, "tok-agl", cls.agl)
        _subscribe(user, "tok-both", cls.kjl, cls.agl)
        _subscribe(user, "tok-spl", cls.spl)

    def setUp(self):
        cache.clear()

    def send(self, **kwargs):
        kwargs.setdefault("side_effect", _batch)
        return patch.object(messaging, "send_each_for_multicast", **kwargs)

    def test_a_live_major_incident_reaches_each_affected_subscriber_once(self):
        with self.send() as send:
            sent = push.notify_major_incident(self.incident.pk)

        self.assertEqual(sent, 3)
        send.assert_called_once()
        message = send.call_args.args[0]
        self.assertCountEqual(message.tokens, ["tok-kjl", "tok-agl", "tok-both"])
        self.assertEqual(message.notification.title, "AGL, KJL: Signal fault")
        self.assertEqual(message.notification.body, "Trains held at KL Sentral")
        self.assertEqual(
            message.webpush.fcm_options.link,
            f"{settings.FRONTEND_BASE_URL}/insiden/2026-10-22",
        )

    def test_a_minor_or_unapproved_incident_sends_nothing(self):
        cases = [
            (CalendarIncidentSeverity.MINOR, CalendarIncidentStatus.LIVE),
            (CalendarIncidentSeverity.MAJOR, CalendarIncidentStatus.PENDING_APPROVAL),
        ]
        for severity, status in cases:
            with self.subTest(severity=severity, status=status):
                CalendarIncident.objects.filter(pk=self.incident.pk).update(
                    severity=severity, status=status
                )
                with self.send() as send:
                    self.assertEqual(push.notify_major_incident(self.incident.pk), 0)
                send.assert_not_called()

    def test_each_line_pushes_at_most_once_per_cooldown(self):
        other = CalendarIncident.objects.create(
            title="Power trip",
            brief="",
            severity=CalendarIncidentSeverity.MAJOR,
            status=CalendarIncidentStatus.LIVE,
            start_datetime=datetime(2026, 10, 22, 9, 0),
        )
        other.lines.set([self.kjl, self.spl])

        with self.send() as send:
            first = push.notify_major_incident(self.incident.pk)
            again = push.notify_major_incident(self.incident.pk)
            # KJL is cooling down; SPL is not, so only its subscriber hears.
            spl_only = push.notify_major_incident(other.pk)

        self.assertEqual((first, again, spl_only), (3, 0, 1))
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args.args[0].tokens, ["tok-spl"])

    def test_only_lines_with_subscribers_are_put_in_cooldown(self):
        quiet = _line("BRT")
        self.incident.lines.add(quiet)

        with self.send():
            self.assertEqual(push.notify_major_incident(self.incident.pk), 3)

        self.assertIsNone(cache.get(push._cooldown_key(quiet.pk)))
        self.assertIsNotNone(cache.get(push._cooldown_key(self.kjl.pk)))

    def test_dead_tokens_are_pruned_and_other_failures_kept(self):
        _subscribe(self.user, "tok-junk", self.kjl)
        _subscribe(self.user, "tok-busy", self.agl)
        failures = {
            "tok-kjl": messaging.UnregisteredError("gone"),
            "tok-agl": messaging.SenderIdMismatchError("other sender"),
            # tok-both is delivered, so the payload is fine and the token is bad.
            "tok-junk": exceptions.InvalidArgumentError("not a token"),
            "tok-busy": exceptions.UnavailableError("try later"),
        }

        with (
            self.send(side_effect=lambda message: _batch(message, failures)),
            self.assertLogs("incident.services.push", "WARNING") as logs,
        ):
            sent = push.notify_major_incident(self.incident.pk)

        self.assertEqual(sent, 1)
        self.assertCountEqual(
            PushSubscription.objects.values_list("token", flat=True),
            ["tok-both", "tok-busy", "tok-spl"],
        )
        self.assertIn("UnavailableError", logs.output[0])
        # Something went out, so no retry and the claim stands.
        self.assertIsNotNone(cache.get(push._cooldown_key(self.kjl.pk)))

    def test_invalid_argument_with_nothing_delivered_prunes_nothing(self):
        failures = dict.fromkeys(
            ["tok-kjl", "tok-agl", "tok-both"],
            exceptions.InvalidArgumentError("bad payload"),
        )

        with (
            self.send(side_effect=lambda message: _batch(message, failures)),
            self.assertLogs("incident.services.push", "WARNING"),
        ):
            self.assertEqual(push.notify_major_incident(self.incident.pk), 0)

        self.assertEqual(PushSubscription.objects.count(), 4)

    def test_an_fcm_outage_is_retried_three_times_with_the_cooldown_released(self):
        outage = dict.fromkeys(
            ["tok-kjl", "tok-agl", "tok-both"], exceptions.UnavailableError("503")
        )
        cases = [
            # What firebase_admin really does: one UnavailableError per token.
            ("per token", lambda message: _batch(message, outage)),
            ("raised", exceptions.UnknownError("executor failed")),
        ]
        for label, side_effect in cases:
            with self.subTest(label), self.send(side_effect=side_effect) as send:
                result = notify_push_subscribers.apply(args=[self.incident.pk])

                self.assertTrue(result.failed())
                self.assertIsInstance(result.result, exceptions.FirebaseError)
                # 1 run + 3 retries; each retry could claim the cooldown again.
                self.assertEqual(send.call_count, 4)
                self.assertIsNone(cache.get(push._cooldown_key(self.kjl.pk)))
                self.assertIsNone(cache.get(push._cooldown_key(self.agl.pk)))


class ApprovalEnqueuesPushTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create(firebase_id="push-admin")
        cls.line = _line("KJL")

    def incident(self, status, **fields):
        fields.setdefault("severity", CalendarIncidentSeverity.MAJOR)
        return CalendarIncident.objects.create(
            title="Signal fault",
            brief="",
            start_datetime=datetime(2026, 10, 22, 8, 0),
            status=status,
            **fields,
        )

    def approve(self, incident, **delay_kwargs):
        with (
            patch.object(notify_push_subscribers, "delay", **delay_kwargs) as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            async_to_sync(services.approve_incident)(
                self.admin, incident_id=incident.pk
            )
        return delay

    def test_approving_a_pending_incident_enqueues_its_push(self):
        incident = self.incident(CalendarIncidentStatus.PENDING_APPROVAL)

        self.approve(incident).assert_called_once_with(incident.pk)

    def test_a_minor_approval_enqueues_a_task_that_sends_nothing(self):
        incident = self.incident(
            CalendarIncidentStatus.PENDING_APPROVAL,
            severity=CalendarIncidentSeverity.MINOR,
        )

        self.approve(incident).assert_called_once_with(incident.pk)
        with patch.object(messaging, "send_each_for_multicast") as send:
            self.assertEqual(notify_push_subscribers(incident.pk), 0)
        send.assert_not_called()

    def test_merging_a_revision_enqueues_only_when_the_parent_turns_live_major(self):
        live, rejected = CalendarIncidentStatus.LIVE, CalendarIncidentStatus.REJECTED
        major, minor = CalendarIncidentSeverity.MAJOR, CalendarIncidentSeverity.MINOR
        for parent_status, parent_severity, revision_severity, enqueued in (
            (live, major, major, False),  # an edit
            (live, minor, major, True),  # escalated
            (live, minor, minor, False),
            (rejected, major, major, True),  # newly LIVE
        ):
            with self.subTest(
                parent=(parent_status, parent_severity), revision=revision_severity
            ):
                parent = self.incident(parent_status, severity=parent_severity)
                revision = self.incident(
                    CalendarIncidentStatus.DRAFT,
                    parent_incident=parent,
                    severity=revision_severity,
                )

                delay = self.approve(revision)

                self.assertEqual(
                    delay.call_args_list,
                    [call(parent.pk)] if enqueued else [],
                )

    def test_a_broker_outage_does_not_fail_the_approval(self):
        incident = self.incident(CalendarIncidentStatus.PENDING_APPROVAL)

        with self.assertLogs("django.test", "ERROR"):
            self.approve(incident, side_effect=ConnectionError("broker down"))

        incident.refresh_from_db()
        self.assertEqual(incident.status, CalendarIncidentStatus.LIVE)
