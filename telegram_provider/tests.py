import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from django.test import TestCase, override_settings
from telegram.error import BadRequest

from operation.models import Line
from telegram_provider.enums import MessageDirection
from telegram_provider.handlers import error_handler, spotting_today
from telegram_provider.models import TelegramLogs
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
