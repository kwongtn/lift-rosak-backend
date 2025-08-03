import asyncio
import pickle
from datetime import datetime, timedelta

from django.conf import settings
from telegram import Bot, Update
from telegram.constants import ReactionEmoji

from rosak.celery import app as celery_app
from telegram_provider.models import TelegramLogs


# TODO: When everything is finalized, check if this is still needed
# from telegram_provider.apps import ptb_application
@celery_app.task(bind=True)
def set_telegram_reaction(
    self,
    *,
    update_payload: dict,
    bot_payload: dict,
    reaction: ReactionEmoji,
    pickled_update: bytes,
    # pickled_bot: bytes,
    **kwargs,
):
    # bot: "Bot" = Bot.de_json(bot_payload)
    # update: "Update" = Update.de_json(update_payload)
    # update.set_bot(bot)
    update: "Update" = pickle.loads(pickled_update)
    # update.set_bot(pickle.loads(pickled_bot))
    bot: "Bot" = Bot.de_json(bot_payload)
    update.set_bot(bot)

    async def asyncfunc(*args, **kwargs):
        await update.message.set_reaction(*args, **kwargs)

    # update.message.set_reaction(reaction=reaction)
    asyncio.run(asyncfunc(reaction=reaction))


@celery_app.task(bind=True)
def cleanup_telegram_logs(
    self,
    *args,
    **kwargs,
):
    TelegramLogs.objects.filter(
        created__lte=datetime.now() - timedelta(days=settings.TELEGRAM_CLEANUP_DAYS)
    ).delete()
