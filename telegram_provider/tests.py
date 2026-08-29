import asyncio
from contextlib import ExitStack, contextmanager
from ctypes import ArgumentError
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from django.test import TestCase, override_settings
from telegram.constants import ReactionEmoji
from telegram.error import BadRequest

from incident.services import IncidentServiceError, SocialMediaLinkWrite
from operation.models import Line
from telegram_provider.enums import MessageDirection
from telegram_provider.handlers import (
    delete_link,
    error_handler,
    spotting_today,
    submit_link,
)
from telegram_provider.models import TelegramLogs
from telegram_provider.parsers import link_parser
from telegram_provider.tasks import cleanup_telegram_logs
from telegram_provider.utils import (
    PerChatRateLimiter,
    TelegramBotNotReady,
    retry_on_error,
    send_message,
)


class TelegramProviderModelTests(TestCase):
    def test_telegram_logs_creation(self):
        log = TelegramLogs.objects.create(
            direction=MessageDirection.INBOUND,
            payload={
                "message": {"text": "/spot Set 40 KJ15", "from": {"id": 12345678}}
            },
        )
        self.assertIsNotNone(log.id)
        self.assertEqual(log.payload["message"]["from"]["id"], 12345678)

    def test_telegram_logs_audit_defaults(self):
        log = TelegramLogs.objects.create(
            direction=MessageDirection.OUTBOUND,
            payload={},
        )

        self.assertEqual(log.retry_count, 0)
        self.assertEqual(log.last_error, "")
        self.assertIsNone(log.sent_at)


class CleanupTelegramLogsTaskTests(TestCase):
    def test_cleanup_telegram_logs_deletes_old_records_and_keeps_recent(self):
        now = datetime.now()

        old_log = TelegramLogs.objects.create(
            direction=MessageDirection.INBOUND,
            payload={"message": {"text": "old message"}},
        )
        recent_log = TelegramLogs.objects.create(
            direction=MessageDirection.INBOUND,
            payload={"message": {"text": "recent message"}},
        )
        boundary_survivor_log = TelegramLogs.objects.create(
            direction=MessageDirection.INBOUND,
            payload={"message": {"text": "29 days old message"}},
        )

        TelegramLogs.objects.filter(id=old_log.id).update(
            created=now - timedelta(days=40)
        )
        TelegramLogs.objects.filter(id=boundary_survivor_log.id).update(
            created=now - timedelta(days=29)
        )

        cleanup_telegram_logs.apply()

        self.assertFalse(TelegramLogs.objects.filter(id=old_log.id).exists())
        self.assertTrue(TelegramLogs.objects.filter(id=recent_log.id).exists())
        self.assertTrue(
            TelegramLogs.objects.filter(id=boundary_survivor_log.id).exists()
        )

    def test_cleanup_telegram_logs_string_cleanup_days_typeerror(self):
        with override_settings(TELEGRAM_CLEANUP_DAYS="30"):
            with self.assertRaises(TypeError):
                cleanup_telegram_logs.apply(throw=True)


class SpottingTodayHandlerTests(TestCase):
    def setUp(self):
        self.line = Line.objects.create(
            code="KJL",
            display_name="Kelana Jaya Line",
            display_color="#FF0000",
            telegram_channel_id="123456",
        )

    @patch("telegram_provider.handlers.get_daily_updates")
    @patch("telegram_provider.handlers.Line")
    def test_spotting_today_no_date_arg(self, mock_line_model, mock_get_daily_updates):
        # spotting_today opens with a real async-ORM Line lookup, which cannot
        # see TestCase's transaction from its worker thread — stub it so the
        # handler proceeds past the channel resolution deterministically.
        mock_line_model.objects.filter.return_value.afirst = AsyncMock(
            return_value=self.line
        )
        mock_get_daily_updates.return_value = "Stats for today"
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "/spotting_today"
        update.message.reply_html = AsyncMock()
        update.effective_chat.id = 123456

        context = MagicMock()
        context.args = []

        asyncio.run(spotting_today(update, context))

        mock_get_daily_updates.assert_called_once_with(
            line_id=self.line.id, spotting_date=date.today()
        )
        update.message.reply_html.assert_awaited_once_with(text="Stats for today")

    @patch("telegram_provider.handlers.get_daily_updates")
    @patch("telegram_provider.handlers.Line")
    def test_spotting_today_valid_date_arg(
        self, mock_line_model, mock_get_daily_updates
    ):
        # Same async-ORM Line-lookup stub as above (TestCase transaction is
        # invisible to the handler's worker thread).
        mock_line_model.objects.filter.return_value.afirst = AsyncMock(
            return_value=self.line
        )
        mock_get_daily_updates.return_value = "Stats for 2026-08-17"
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "/spotting_today 2026-08-17"
        update.message.reply_html = AsyncMock()
        update.effective_chat.id = 123456

        context = MagicMock()
        context.args = ["2026-08-17"]

        asyncio.run(spotting_today(update, context))

        mock_get_daily_updates.assert_called_once_with(
            line_id=self.line.id, spotting_date=date(2026, 8, 17)
        )
        update.message.reply_html.assert_awaited_once_with(text="Stats for 2026-08-17")

    @patch("telegram_provider.handlers.get_daily_updates")
    @patch("telegram_provider.handlers.Line")
    def test_spotting_today_invalid_date_arg(
        self, mock_line_model, mock_get_daily_updates
    ):
        # Same async-ORM Line-lookup stub as above (TestCase transaction is
        # invisible to the handler's worker thread).
        mock_line_model.objects.filter.return_value.afirst = AsyncMock(
            return_value=self.line
        )
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "/spotting_today invalid-date"
        update.message.reply_html = AsyncMock()
        update.effective_chat.id = 123456

        context = MagicMock()
        context.args = ["invalid-date"]

        asyncio.run(spotting_today(update, context))

        mock_get_daily_updates.assert_not_called()
        update.message.reply_html.assert_awaited_once_with(
            text="Invalid date format. Please use yyyy-mm-dd format (e.g., 2026-08-17)"
        )


class PerChatRateLimiterTests(TestCase):
    """Sliding-window limiter: default budget, per-chat isolation, rollover."""

    def test_allows_exactly_max_per_window_then_throttles(self):
        limiter = PerChatRateLimiter()

        for _ in range(30):
            self.assertEqual(limiter.acquire("chat-a"), 0.0)

        self.assertGreater(limiter.acquire("chat-a"), 0.0)

    def test_per_chat_isolation(self):
        limiter = PerChatRateLimiter()

        for _ in range(30):
            limiter.acquire("chat-a")

        self.assertEqual(limiter.acquire("chat-b"), 0.0)

    def test_window_rollover_reopens_slots(self):
        limiter = PerChatRateLimiter()
        clock = {"now": 1000.0}

        def fake_monotonic():
            return clock["now"]

        with patch(
            "telegram_provider.utils.time.monotonic", side_effect=fake_monotonic
        ):
            for _ in range(30):
                self.assertEqual(limiter.acquire("chat-c"), 0.0)
            self.assertGreater(limiter.acquire("chat-c"), 0.0)

            clock["now"] = 1002.0

            self.assertEqual(limiter.acquire("chat-c"), 0.0)


class RetryOnErrorTests(TestCase):
    """Pure-async retry helper, each coroutine driven via asyncio.run().

    Deliberately NOT unittest.IsolatedAsyncioTestCase: its instances hold a
    _contextvars.Context, which Django's --parallel runner cannot pickle
    when distributing subsuites to workers. asyncio.run() still awaits each
    coroutine to completion, so every assertion genuinely executes (unlike
    bare ``async def`` methods under TestCase, which the runner never
    awaits).
    """

    def test_success_on_first_attempt_returns_value_without_sleep(self):
        source = MagicMock()
        source.method = AsyncMock(return_value="ok")

        with patch(
            "telegram_provider.utils.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            result = asyncio.run(retry_on_error(source, "method", "arg1", kwarg1="v1"))

        self.assertEqual(result, "ok")
        source.method.assert_awaited_once_with("arg1", kwarg1="v1")
        mock_sleep.assert_not_awaited()

    def test_transient_failures_retry_with_backoff_then_succeed(self):
        source = MagicMock()
        source.method = AsyncMock(
            side_effect=[
                RuntimeError("transient-1"),
                RuntimeError("transient-2"),
                "recovered",
            ]
        )

        with patch(
            "telegram_provider.utils.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            result = asyncio.run(
                retry_on_error(source, "method", max_retries=3, backoff_base=2.0)
            )

        self.assertEqual(result, "recovered")
        self.assertEqual(mock_sleep.await_args_list, [call(2.0), call(4.0)])

    def test_exhaustion_reraises_last_exception(self):
        source = MagicMock()
        source.method = AsyncMock(side_effect=ValueError("boom"))

        with patch("telegram_provider.utils.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(ValueError):
                asyncio.run(retry_on_error(source, "method", max_retries=3))

        self.assertEqual(source.method.await_count, 3)

    def test_react_not_found_bad_request_returns_none_immediately(self):
        source = MagicMock()
        source.set_reaction = AsyncMock(
            side_effect=BadRequest("Message to react not found")
        )

        with patch(
            "telegram_provider.utils.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            result = asyncio.run(retry_on_error(source, "set_reaction"))

        self.assertIsNone(result)
        source.set_reaction.assert_awaited_once()
        mock_sleep.assert_not_awaited()

    def test_none_source_returns_none_without_calling(self):
        result = asyncio.run(retry_on_error(None, "method"))

        self.assertIsNone(result)


class SendMessageTests(TestCase):
    """Governed egress end-to-end with the DB layer mocked out.

    TestCase (not IsolatedAsyncioTestCase): the latter's instances hold a
    _contextvars.Context, which Django's --parallel runner cannot pickle
    when distributing subsuites to workers. asyncio.run() still awaits
    each coroutine to completion, so every assertion genuinely executes.
    The async-ORM writes are mocked (``acreate``/``asave``), so no real
    rows are written and no table truncation is needed.
    """

    def _fake_app(self, send_side_effect=None, send_return_value=None):
        fake_app = MagicMock(name="ptb_application")
        fake_app.bot.send_message = AsyncMock(
            side_effect=send_side_effect, return_value=send_return_value
        )
        return fake_app

    @staticmethod
    def _log():
        # Model-default seed: an unset MagicMock attr auto-creates a child
        # mock on read, which would break assertIsNone(sent_at).
        log = MagicMock(name="audit_log")
        log.asave = AsyncMock()
        log.sent_at = None
        log.retry_count = 0
        log.last_error = ""
        return log

    def test_success_writes_single_outbound_audit_row_and_returns_message(self):
        sentinel_message = MagicMock(name="sent_message")
        fake_app = self._fake_app(send_return_value=sentinel_message)
        log = self._log()

        with (
            patch(
                "telegram_provider.utils.get_ptb_application",
                new_callable=AsyncMock,
                return_value=fake_app,
            ),
            patch(
                "telegram_provider.utils.TelegramLogs.objects.acreate",
                new_callable=AsyncMock,
                return_value=log,
            ) as mock_acreate,
            patch("telegram_provider.utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = asyncio.run(send_message("111001", "hello world"))

        self.assertIs(result, sentinel_message)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(log.retry_count, 0)
        log.asave.assert_awaited_once()
        mock_acreate.assert_awaited_once()
        acreate_kwargs = mock_acreate.await_args.kwargs
        self.assertEqual(acreate_kwargs["direction"], MessageDirection.OUTBOUND)
        self.assertEqual(acreate_kwargs["payload"]["chat_id"], "111001")
        self.assertEqual(acreate_kwargs["payload"]["text"], "hello world")
        fake_app.bot.send_message.assert_awaited_once_with(
            chat_id="111001", text="hello world"
        )

    def test_transient_failures_stamp_retry_count_and_sent_at(self):
        sentinel_message = MagicMock(name="sent_message")
        fake_app = self._fake_app(
            send_side_effect=[
                RuntimeError("flap-1"),
                RuntimeError("flap-2"),
                sentinel_message,
            ]
        )
        log = self._log()

        with (
            patch(
                "telegram_provider.utils.get_ptb_application",
                new_callable=AsyncMock,
                return_value=fake_app,
            ),
            patch(
                "telegram_provider.utils.TelegramLogs.objects.acreate",
                new_callable=AsyncMock,
                return_value=log,
            ),
            patch("telegram_provider.utils.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = asyncio.run(send_message("111002", "retry me"))

        self.assertIs(result, sentinel_message)
        self.assertEqual(log.retry_count, 2)
        self.assertIsNotNone(log.sent_at)
        # One asave per attempt-state change: two failures + final success.
        self.assertEqual(log.asave.await_count, 3)
        self.assertEqual(fake_app.bot.send_message.await_count, 3)

    def test_permanent_failure_dead_letters_row_and_notifies_admin(self):
        fake_app = self._fake_app(send_side_effect=RuntimeError("down"))
        log = self._log()

        with override_settings(TELEGRAM_ADMIN_CHAT_ID="999"):
            with (
                patch(
                    "telegram_provider.utils.get_ptb_application",
                    new_callable=AsyncMock,
                    return_value=fake_app,
                ),
                patch(
                    "telegram_provider.utils.TelegramLogs.objects.acreate",
                    new_callable=AsyncMock,
                    return_value=log,
                ),
                patch("telegram_provider.utils.asyncio.sleep", new_callable=AsyncMock),
            ):
                result = asyncio.run(send_message("111003", "doomed"))

        self.assertIsNone(result)
        self.assertIsNone(log.sent_at)
        self.assertEqual(log.retry_count, 3)
        self.assertNotEqual(log.last_error, "")
        # One asave per failed attempt — the dead-letter state.
        self.assertEqual(log.asave.await_count, 3)
        # 3 delivery attempts + 1 best-effort admin ping.
        self.assertEqual(fake_app.bot.send_message.await_count, 4)
        admin_call = fake_app.bot.send_message.await_args_list[-1]
        self.assertEqual(admin_call.kwargs["chat_id"], "999")
        self.assertIn("[rosak]", admin_call.kwargs["text"])

    def test_permanent_failure_skips_admin_notify_when_chat_id_empty(self):
        fake_app = self._fake_app(send_side_effect=RuntimeError("down"))
        log = self._log()

        with override_settings(TELEGRAM_ADMIN_CHAT_ID=""):
            with (
                patch(
                    "telegram_provider.utils.get_ptb_application",
                    new_callable=AsyncMock,
                    return_value=fake_app,
                ),
                patch(
                    "telegram_provider.utils.TelegramLogs.objects.acreate",
                    new_callable=AsyncMock,
                    return_value=log,
                ),
                patch("telegram_provider.utils.asyncio.sleep", new_callable=AsyncMock),
            ):
                result = asyncio.run(send_message("111004", "doomed quietly"))

        self.assertIsNone(result)
        # Only the 3 delivery attempts — no admin ping.
        self.assertEqual(fake_app.bot.send_message.await_count, 3)
        for delivery_call in fake_app.bot.send_message.await_args_list:
            self.assertNotEqual(delivery_call.kwargs["chat_id"], "999")

    def test_bot_not_ready_raises_without_creating_audit_row(self):
        log = self._log()

        with (
            patch(
                "telegram_provider.utils.get_ptb_application",
                new_callable=AsyncMock,
                side_effect=TelegramBotNotReady("no token"),
            ),
            patch(
                "telegram_provider.utils.TelegramLogs.objects.acreate",
                new_callable=AsyncMock,
                return_value=log,
            ) as mock_acreate,
        ):
            with self.assertRaises(TelegramBotNotReady):
                asyncio.run(send_message("111005", "never sent"))

        mock_acreate.assert_not_awaited()


class ErrorHandlerTests(TestCase):
    """Admin notification branch of the PTB error handler.

    Touches no DB — ``send_message`` is mocked — so no table truncation
    is needed. Coroutines are driven via asyncio.run() under plain
    TestCase so instances stay picklable under --parallel.
    """

    def _error_with_traceback(self):
        try:
            raise ValueError("kaboom")
        except ValueError as exc:
            return exc

    def _make_update_and_context(self):
        # Plain object exercises the non-Update branch (handler uses str(update)).
        update = object()
        context = SimpleNamespace(
            error=self._error_with_traceback(), chat_data={}, user_data={}
        )
        return update, context

    def test_notifies_admin_chat_with_html_parse_mode(self):
        update, context = self._make_update_and_context()

        with override_settings(TELEGRAM_ADMIN_CHAT_ID="999"):
            with patch(
                "telegram_provider.handlers.send_message", new_callable=AsyncMock
            ) as mock_send:
                asyncio.run(error_handler(update, context))

        mock_send.assert_awaited_once()
        sent_kwargs = mock_send.await_args.kwargs
        self.assertEqual(sent_kwargs["chat_id"], "999")
        self.assertEqual(sent_kwargs["parse_mode"], "HTML")
        self.assertIn("kaboom", sent_kwargs["text"])

    def test_sends_nothing_when_admin_chat_id_unset(self):
        update, context = self._make_update_and_context()

        with override_settings(TELEGRAM_ADMIN_CHAT_ID=""):
            with patch(
                "telegram_provider.handlers.send_message", new_callable=AsyncMock
            ) as mock_send:
                asyncio.run(error_handler(update, context))

        mock_send.assert_not_awaited()


class LinkHandlerTests(TestCase):
    """Coverage for /link (submit_link) and /deletelink (delete_link) handlers.

    Plain TestCase (not IsolatedAsyncioTestCase): its instances hold a
    _contextvars.Context which Django's --parallel runner cannot pickle.
    Coroutines are driven via asyncio.run() so every assertion executes.

    The handlers perform several async-ORM lookups (User, Line, Vehicle,
    StationLine, TelegramLogs, TelegramSocialMediaLinkLog) that would hit a
    separate connection invisible to the TestCase transaction, so each model
    class is patched and its queryset methods stubbed with AsyncMock —
    mirroring the SpottingTodayHandlerTests pattern. The incident services are
    stubbed with AsyncMock so no real rows are written.
    """

    def setUp(self):
        self.line = MagicMock(name="line")
        self.line.id = 42
        self.vehicle = MagicMock(name="vehicle")
        self.vehicle.id = 7
        self.station_line = MagicMock(name="station_line")
        self.station_line.station_id = 13
        self.user = MagicMock(name="user")
        self.user.id = 99
        self.link = MagicMock(name="social_media_link")
        self.link.id = 555
        self.telegram_log = MagicMock(name="telegram_log")
        self.telegram_log.id = 888
        self.link_log = MagicMock(name="telegram_social_media_link_log")
        self.link_log.social_media_link = self.link

    @contextmanager
    def _mock_handlers(self):
        with ExitStack() as stack:
            mocks = {}
            mocks["user"] = stack.enter_context(
                patch("telegram_provider.handlers.User")
            )
            mocks["line"] = stack.enter_context(
                patch("telegram_provider.handlers.Line")
            )
            mocks["vehicle"] = stack.enter_context(
                patch("telegram_provider.handlers.Vehicle")
            )
            mocks["station_line"] = stack.enter_context(
                patch("telegram_provider.handlers.StationLine")
            )
            mocks["telegram_log"] = stack.enter_context(
                patch("telegram_provider.handlers.TelegramLogs")
            )
            mocks["link_log"] = stack.enter_context(
                patch("telegram_provider.handlers.TelegramSocialMediaLinkLog")
            )
            mocks["submit"] = stack.enter_context(
                patch(
                    "telegram_provider.handlers.services.submit_social_media_link",
                    new_callable=AsyncMock,
                )
            )
            mocks["delete"] = stack.enter_context(
                patch(
                    "telegram_provider.handlers.services.delete_social_media_link",
                    new_callable=AsyncMock,
                )
            )
            mocks["retry"] = stack.enter_context(
                patch(
                    "telegram_provider.handlers.retry_on_error",
                    new_callable=AsyncMock,
                )
            )
            yield mocks

    def _make_update(self, text, reply_to_message=object()):
        update = MagicMock(name="update")
        update.message = MagicMock(name="message")
        update.message.text = text
        update.message.from_user = MagicMock()
        update.message.from_user.id = 12345
        update.message.message_id = 777
        update.message.reply_to_message = reply_to_message
        update.message.reply_html = AsyncMock()
        update.message.reply_text = AsyncMock()
        update.message.set_reaction = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = 123456
        return update

    def _context(self, args=None):
        context = MagicMock(name="context")
        context.args = args
        return context

    def _stub_user(self, mocks, user):
        mocks["user"].objects.filter.return_value.afirst = AsyncMock(return_value=user)

    def _stub_line(self, mocks, exists=True, line=None):
        line = line or self.line
        qs = mocks["line"].objects.filter.return_value
        qs.aexists = AsyncMock(return_value=exists)
        qs.afirst = AsyncMock(return_value=line if exists else None)

    def _stub_telegram_log(self, mocks):
        qs = mocks["telegram_log"].objects.filter.return_value
        qs.order_by.return_value.afirst = AsyncMock(return_value=self.telegram_log)

    def _stub_link_log_acreate(self, mocks):
        mocks["link_log"].objects.acreate = AsyncMock()

    def test_submit_link_not_verified_prompts_verify_and_skips_service(self):
        update = self._make_update("/link https://example.com")
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, None)
            asyncio.run(submit_link(update, context))

        mocks["submit"].assert_not_awaited()
        update.message.reply_html.assert_awaited_once()
        self.assertIn("/verify", update.message.reply_html.await_args.kwargs["text"])
        mocks["retry"].assert_not_awaited()

    def test_submit_link_no_line_replies_and_reacts_down(self):
        update = self._make_update("/link https://example.com")
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            self._stub_line(mocks, exists=False)
            with self.assertRaises(Exception):
                asyncio.run(submit_link(update, context))

        mocks["submit"].assert_not_awaited()
        update.message.reply_html.assert_awaited_once_with(
            text="No line assigned for this channel."
        )
        mocks["retry"].assert_awaited_once_with(
            update.message, "set_reaction", ReactionEmoji.THUMBS_DOWN
        )

    def test_submit_link_with_incident_id_calls_service_once(self):
        update = self._make_update("/link https://example.com -id 5")
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            self._stub_line(mocks, exists=True)
            self._stub_telegram_log(mocks)
            self._stub_link_log_acreate(mocks)
            mocks["submit"].return_value = self.link
            asyncio.run(submit_link(update, context))

        mocks["submit"].assert_awaited_once()
        call_kwargs = mocks["submit"].await_args.kwargs
        self.assertIs(call_kwargs["user"], self.user)
        self.assertEqual(
            call_kwargs["write"],
            SocialMediaLinkWrite(
                url="https://example.com",
                title="",
                incident_id=5,
                line_ids=(self.line.id,),
                vehicle_ids=(),
                station_ids=(),
            ),
        )
        mocks["retry"].assert_awaited_once_with(
            update.message, "set_reaction", ReactionEmoji.THUMBS_UP
        )

    def test_submit_link_line_only_sets_incident_id_none(self):
        update = self._make_update("/link https://example.com")
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            self._stub_line(mocks, exists=True)
            self._stub_telegram_log(mocks)
            self._stub_link_log_acreate(mocks)
            mocks["submit"].return_value = self.link
            asyncio.run(submit_link(update, context))

        mocks["submit"].assert_awaited_once()
        write = mocks["submit"].await_args.kwargs["write"]
        self.assertIsNone(write.incident_id)
        self.assertEqual(write.line_ids, (self.line.id,))
        self.assertEqual(write.vehicle_ids, ())
        self.assertEqual(write.station_ids, ())
        mocks["retry"].assert_awaited_once_with(
            update.message, "set_reaction", ReactionEmoji.THUMBS_UP
        )

    def test_submit_link_with_vehicle_resolves_vehicle_id(self):
        update = self._make_update("/link https://example.com -v KJL01")
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            self._stub_line(mocks, exists=True)
            mocks["vehicle"].objects.filter.return_value.afirst = AsyncMock(
                return_value=self.vehicle
            )
            self._stub_telegram_log(mocks)
            self._stub_link_log_acreate(mocks)
            mocks["submit"].return_value = self.link
            asyncio.run(submit_link(update, context))

        write = mocks["submit"].await_args.kwargs["write"]
        self.assertEqual(write.vehicle_ids, (self.vehicle.id,))
        self.assertEqual(write.station_ids, ())
        mocks["retry"].assert_awaited_once_with(
            update.message, "set_reaction", ReactionEmoji.THUMBS_UP
        )

    def test_submit_link_with_station_resolves_station_id(self):
        update = self._make_update("/link https://example.com -st KG05")
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            self._stub_line(mocks, exists=True)
            st_qs = MagicMock(name="stationline_qs")
            st_qs.filter.return_value = st_qs
            st_qs.select_related.return_value = st_qs
            st_qs.afirst = AsyncMock(return_value=self.station_line)
            mocks["station_line"].objects.filter.return_value = st_qs
            self._stub_telegram_log(mocks)
            self._stub_link_log_acreate(mocks)
            mocks["submit"].return_value = self.link
            asyncio.run(submit_link(update, context))

        write = mocks["submit"].await_args.kwargs["write"]
        self.assertEqual(write.station_ids, (self.station_line.station_id,))
        self.assertEqual(write.vehicle_ids, ())
        mocks["retry"].assert_awaited_once_with(
            update.message, "set_reaction", ReactionEmoji.THUMBS_UP
        )

    def test_submit_link_invalid_incident_id_replies_error_and_reacts_down(self):
        update = self._make_update("/link https://example.com -id 999")
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            self._stub_line(mocks, exists=True)
            self._stub_telegram_log(mocks)
            self._stub_link_log_acreate(mocks)
            mocks["submit"].side_effect = IncidentServiceError("Incident 999 not found")
            asyncio.run(submit_link(update, context))

        mocks["submit"].assert_awaited_once()
        update.message.reply_html.assert_awaited_once_with(
            text="Failed to submit link: Incident 999 not found"
        )
        mocks["retry"].assert_awaited_once_with(
            update.message, "set_reaction", ReactionEmoji.THUMBS_DOWN
        )

    def test_delete_link_owner_success_calls_service_and_reacts_up(self):
        reply = MagicMock(name="reply_to_message")
        reply.message_id = 777
        reply.chat = MagicMock()
        reply.chat.id = 123456
        update = self._make_update("/deletelink", reply_to_message=reply)
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            ll_qs = MagicMock(name="linklog_qs")
            ll_qs.select_related.return_value = ll_qs
            ll_qs.afirst = AsyncMock(return_value=self.link_log)
            mocks["link_log"].objects.filter.return_value = ll_qs
            asyncio.run(delete_link(update, context))

        mocks["delete"].assert_awaited_once_with(user=self.user, link_id=self.link.id)
        mocks["retry"].assert_awaited_once_with(
            update.message, "set_reaction", ReactionEmoji.THUMBS_UP
        )

    def test_delete_link_not_owner_replies_error_and_reacts_down(self):
        reply = MagicMock(name="reply_to_message")
        reply.message_id = 777
        reply.chat = MagicMock()
        reply.chat.id = 123456
        update = self._make_update("/deletelink", reply_to_message=reply)
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            ll_qs = MagicMock(name="linklog_qs")
            ll_qs.select_related.return_value = ll_qs
            ll_qs.afirst = AsyncMock(return_value=self.link_log)
            mocks["link_log"].objects.filter.return_value = ll_qs
            mocks["delete"].side_effect = IncidentServiceError(
                "SocialMediaLink 555 is not owned by this user."
            )
            asyncio.run(delete_link(update, context))

        mocks["delete"].assert_awaited_once()
        update.message.reply_html.assert_awaited_once_with(
            text="Failed to delete link: SocialMediaLink 555 is not owned by this user."
        )
        mocks["retry"].assert_awaited_once_with(
            update.message, "set_reaction", ReactionEmoji.THUMBS_DOWN
        )

    def test_delete_link_no_reply_target_prompts_and_skips_service(self):
        update = self._make_update("/deletelink", reply_to_message=None)
        context = self._context()

        with self._mock_handlers() as mocks:
            self._stub_user(mocks, self.user)
            asyncio.run(delete_link(update, context))

        mocks["delete"].assert_not_awaited()
        update.message.reply_html.assert_awaited_once_with(
            text="Please reply to the link entry you want to delete."
        )
        mocks["retry"].assert_not_awaited()

    def test_link_parser_valid_argv_parses(self):
        args = link_parser().parse_args(
            ["https://example.com", "-id", "5", "-t", "My Title"]
        )
        self.assertEqual(args.url, "https://example.com")
        self.assertEqual(args.incident_id, 5)
        self.assertEqual(args.title, "My Title")

    def test_link_parser_missing_url_raises_argument_error(self):
        with self.assertRaises(ArgumentError):
            link_parser().parse_args([])

    def test_link_parser_invalid_incident_id_raises_argument_error(self):
        with self.assertRaises(ArgumentError):
            link_parser().parse_args(["https://example.com", "-id", "notanint"])
