from typing import Protocol

import httpx
from django.apps import AppConfig
from django.conf import settings
from telegram import Update
from telegram.ext import Application, CommandHandler

ptb_application = None

# Help function prioritizes help_prompt. If that does not exist, the key will be used.
# Help description prioritizes help_text. If that does not exist, description will be used.
handlers_dict = {
    "ping": {
        "description": "Checks if the bot is still alive and kicking",
    },
    "help": {
        "description": "Displays detailed help text",
    },
    "dadjoke": {
        "description": "Who doesn't love those?",
    },
    "verify": {
        "help_prompt": "verify [code]",
        "description": "Enter the verification code to link your telegram account with your Google Account.",
    },
    "help_spotting": {
        "description": "Syntax for Spotting",
    },
    "fav": {
        "description": "Responds favourite vehicle for line",
    },
    "s": {
        "description": "Shorthand for /spot you lazy piece of shite",
    },
    "spot": {
        "description": "Enter spotting data",
    },
    "spotting_today": {
        "description": "Displays spotting stats for today",
    },
}


class HTTPXAppConfig(Protocol):
    httpx_client: httpx.AsyncClient


class ASGILifespanSignalHandler:
    app_config: HTTPXAppConfig

    def __init__(self, app_config: HTTPXAppConfig):
        self.app_config = app_config

    async def startup(self, **_):
        global ptb_application
        ptb_application = (
            Application.builder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .updater(None)
            .build()
        )
        await ptb_application.initialize()
        await ptb_application.start()
        await ptb_application.bot.set_webhook(
            url=f"{settings.TELEGRAM_TLD}/telegram_provider/",
            allowed_updates=Update.ALL_TYPES,
        )
        self.app_config.httpx_client = httpx.AsyncClient()

        from telegram_provider.handlers import (
            dad_joke,
            error_handler,
            favourite_vehicle,
            help,
            help_spotting,
            ping,
            spot,
            spotting_today,
            verify,
        )

        handlers_mapping = {
            "ping": ping,
            "help": help,
            "dadjoke": dad_joke,
            "verify": verify,
            "help_spotting": help_spotting,
            "fav": favourite_vehicle,
            "s": spot,
            "spot": spot,
            "spotting_today": spotting_today,
        }

        for k, v in handlers_mapping.items():
            handlers_dict[k]["handler"] = v

        await ptb_application.bot.set_my_commands(
            [(command, elem["description"]) for command, elem in handlers_dict.items()]
        )
        ptb_application.add_handlers(
            [
                CommandHandler(command, elem["handler"])
                for command, elem in handlers_dict.items()
            ]
        )
        ptb_application.add_error_handler(error_handler)

    async def shutdown(self, **_):
        await ptb_application.stop()
        await self.app_config.httpx_client.aclose()


class TelegramProviderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "telegram_provider"

    def ready(self):
        from django_asgi_lifespan.signals import asgi_shutdown, asgi_startup

        handler = ASGILifespanSignalHandler(app_config=self)

        asgi_startup.connect(handler.startup, weak=False)
        asgi_shutdown.connect(handler.shutdown, weak=False)
