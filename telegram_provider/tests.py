from datetime import datetime, timedelta

from django.test import TestCase, override_settings

from telegram_provider.enums import MessageDirection
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
