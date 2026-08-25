from datetime import date, timedelta

from asgiref.sync import async_to_sync

from operation.models import Line
from rosak.celery import app as celery_app
from telegram_provider.utils import get_daily_updates, send_message


@celery_app.task(bind=True)
def report_spotting_today(self, *args, **kwargs) -> None:
    # May need to rewrite as some channels have multiple lines. We only take the first one.
    for line in Line.objects.distinct("telegram_channel_id"):
        if not line.telegram_channel_id:
            continue

        # Collect stats from previous day
        inline_html = get_daily_updates(
            line_id=line.id,
            spotting_date=date.today()
            - timedelta(hours=12),  # 12 hours just in case it runs past midnight
        )

        # Send telegram message to channel through the governed egress path
        async_to_sync(send_message)(
            chat_id=line.telegram_channel_id,
            text=inline_html,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
