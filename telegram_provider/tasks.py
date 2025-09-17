from datetime import datetime, timedelta

from django.conf import settings

from rosak.celery import app as celery_app
from telegram_provider.models import TelegramLogs


@celery_app.task(bind=True)
def cleanup_telegram_logs(
    self,
    *args,
    **kwargs,
):
    TelegramLogs.objects.filter(
        created__lte=datetime.now() - timedelta(days=settings.TELEGRAM_CLEANUP_DAYS)
    ).delete()
