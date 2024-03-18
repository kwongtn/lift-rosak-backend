from django.db import models

from telegram_provider.enums import MessageDirection


# TODO: We only record inbound for now
class TelegramLogs(models.Model):
    direction = models.IntegerField(choices=MessageDirection.choices)
    payload = models.JSONField()


class TelegramSpottingEventLog(models.Model):
    spotting_event = models.ForeignKey(
        "spotting.Event",
        on_delete=models.SET_NULL,
        null=True,
        related_name="telegram_logs",
    )
    telegram_log = models.ForeignKey(
        "telegram_provider.TelegramLogs",
        on_delete=models.CASCADE,
        related_name="telegram_logs",
    )
