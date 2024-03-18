from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from django.apps import AppConfig
from django.conf import settings
from django_asgi_lifespan.register import register_lifespan_manager
from telegram import Update
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    ExtBot,
)

from telegram_provider.dataclasses import WebhookUpdate

if TYPE_CHECKING:
    from django_asgi_lifespan.types import State


class CustomContext(CallbackContext[ExtBot, dict, dict, dict]):
    """
    Custom CallbackContext class that makes `user_data` available for updates of type
    `WebhookUpdate`.
    """

    @classmethod
    def from_update(
        cls,
        update: object,
        application: "Application",
    ) -> "CustomContext":
        if isinstance(update, WebhookUpdate):
            return cls(application=application, user_id=update.user_id)
        return super().from_update(update, application)


context_types = ContextTypes(context=CustomContext)
ptb_application = (
    Application.builder()
    .token(settings.TELEGRAM_BOT_TOKEN)
    .updater(None)
    .context_types(context_types)
    .build()
)


@asynccontextmanager
async def httpx_lifespan_manager() -> "State":
    state = {"httpx_client": httpx.AsyncClient()}

    await ptb_application.bot.set_webhook(
        url=f"{settings.TELEGRAM_TLD}/telegram_provider/",
        allowed_updates=Update.ALL_TYPES,
    )

    async with ptb_application:
        try:
            await ptb_application.start()
            yield state
        finally:
            await state["httpx_client"].aclose()
            await ptb_application.stop()


class TelegramProviderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "telegram_provider"

    def ready(self):
        from telegram_provider.apps import httpx_lifespan_manager, ptb_application
        from telegram_provider.handlers import (
            error_handler,
            help,
            help_spotting,
            ping,
            spot,
            verify,
        )

        register_lifespan_manager(context_manager=httpx_lifespan_manager)
        ptb_application.add_handlers(
            [
                CommandHandler("ping", ping),
                CommandHandler("help", help),
                CommandHandler("verify", verify),
                CommandHandler("help_spotting", help_spotting),
                CommandHandler("spot", spot),
            ]
        )

        ptb_application.add_error_handler(error_handler)
