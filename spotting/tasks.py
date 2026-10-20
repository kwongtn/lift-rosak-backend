from datetime import datetime
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from django.conf import settings

from operation.models import Line
from rosak.celery import app as celery_app
from telegram_provider.utils import (
    effective_spotting_date,
    get_daily_updates,
    send_message,
)


@celery_app.task(bind=True)
def report_spotting_today(self, *args, **kwargs) -> None:
    # Beat fires at 00:00 local, before the 03:00 service-day cutoff, so this is the
    # day that just ended (and still is if the worker picks the job up late).
    spotting_date = effective_spotting_date(datetime.now(ZoneInfo(settings.TIME_ZONE)))

    # May need to rewrite as some channels have multiple lines. We only take the first one.
    for line in Line.objects.distinct("telegram_channel_id"):
        if not line.telegram_channel_id:
            continue

        inline_html = get_daily_updates(line_id=line.id, spotting_date=spotting_date)

        # Send telegram message to channel through the governed egress path
        async_to_sync(send_message)(
            chat_id=line.telegram_channel_id,
            text=inline_html,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
