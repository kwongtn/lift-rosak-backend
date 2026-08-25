from django.db import models
from model_utils.models import TimeStampedModel

from telegram_provider.enums import MessageDirection


class TelegramLogs(TimeStampedModel):
    direction = models.IntegerField(choices=MessageDirection.choices)
    payload = models.JSONField()
    retry_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)


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
