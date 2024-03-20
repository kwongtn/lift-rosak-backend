from typing import Protocol

import httpx
from django.apps import AppConfig
from django.conf import settings
from telegram import Update
from telegram.ext import Application, CommandHandler

ptb_application = None


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
            help,
            help_spotting,
            ping,
            spot,
            verify,
        )

        handlers_dict = {
            "ping": {
                "description": "Checks if the bot is still alive and kicking",
                "handler": ping,
            },
            "help": {
                "description": "Displays detailed help text",
                "handler": help,
            },
            "dadjoke": {
                "description": "Who doesn't love those?",
                "handler": dad_joke,
            },
            "verify": {
                "description": "Link with Google Account",
                "handler": verify,
            },
            "help_spotting": {
                "description": "Syntax for Spotting",
                "handler": help_spotting,
            },
            "spot": {
                "description": "Enter spotting data",
                "handler": spot,
            },
        }

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
