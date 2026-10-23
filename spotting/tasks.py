from datetime import datetime, time, timedelta
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

# A digest day runs from 03:01 to 03:00 the next day; the 03:01 beat closes it.
DIGEST_DAY_START = time(3, 1)


@celery_app.task(bind=True)
def report_spotting_today(self, *args, **kwargs) -> None:
    # Beat fires at 03:01 local, so the day to report is the one before the day now
    # belongs to (and still is if the worker picks the job up late). The default 03:00
    # cutoff, not 03:01, keeps a worker clock up to 60 s behind beat's on the same day.
    spotting_date = effective_spotting_date(
        datetime.now(ZoneInfo(settings.TIME_ZONE))
    ) - timedelta(days=1)
    # Events are picked by submission time. Event.created is naive local time
    # (USE_TZ = False), so the window bounds are too.
    start = datetime.combine(spotting_date, DIGEST_DAY_START)
    created_between = (start, start + timedelta(days=1))

    # Lines may share a channel; each channel gets one digest, for its first line by
    # code. DISTINCT ON must lead the ORDER BY, which Line.Meta.ordering would take.
    for line in Line.objects.order_by("telegram_channel_id", "code").distinct(
        "telegram_channel_id"
    ):
        if not line.telegram_channel_id:
            continue

        inline_html = get_daily_updates(
            line_id=line.id,
            spotting_date=spotting_date,
            created_between=created_between,
        )

        # Send telegram message to channel through the governed egress path
        async_to_sync(send_message)(
            chat_id=line.telegram_channel_id,
            text=inline_html,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
