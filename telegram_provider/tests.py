from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase, override_settings

from operation.models import Line
from telegram_provider.enums import MessageDirection
from telegram_provider.handlers import spotting_today
from telegram_provider.models import TelegramLogs
from telegram_provider.tasks import cleanup_telegram_logs


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
    async def test_spotting_today_no_date_arg(self, mock_get_daily_updates):
        mock_get_daily_updates.return_value = "Stats for today"
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "/spotting_today"
        update.message.reply_html = AsyncMock()
        update.effective_chat.id = 123456

        context = MagicMock()
        context.args = []

        await spotting_today(update, context)

        mock_get_daily_updates.assert_called_once_with(
            line_id=self.line.id, spotting_date=date.today()
        )
        update.message.reply_html.assert_awaited_once_with(text="Stats for today")

    @patch("telegram_provider.handlers.get_daily_updates")
    async def test_spotting_today_valid_date_arg(self, mock_get_daily_updates):
        mock_get_daily_updates.return_value = "Stats for 2026-08-17"
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "/spotting_today 2026-08-17"
        update.message.reply_html = AsyncMock()
        update.effective_chat.id = 123456

        context = MagicMock()
        context.args = ["2026-08-17"]

        await spotting_today(update, context)

        mock_get_daily_updates.assert_called_once_with(
            line_id=self.line.id, spotting_date=date(2026, 8, 17)
        )
        update.message.reply_html.assert_awaited_once_with(text="Stats for 2026-08-17")

    @patch("telegram_provider.handlers.get_daily_updates")
    async def test_spotting_today_invalid_date_arg(self, mock_get_daily_updates):
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "/spotting_today invalid-date"
        update.message.reply_html = AsyncMock()
        update.effective_chat.id = 123456

        context = MagicMock()
        context.args = ["invalid-date"]

        await spotting_today(update, context)

        mock_get_daily_updates.assert_not_called()
        update.message.reply_html.assert_awaited_once_with(
            text="Invalid date format. Please use yyyy-mm-dd format (e.g., 2026-08-17)"
        )
