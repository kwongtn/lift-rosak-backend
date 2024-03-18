import json

from asgiref.sync import async_to_sync
from django.http import HttpRequest
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from telegram import Update

from telegram_provider.apps import ptb_application
from telegram_provider.enums import MessageDirection
from telegram_provider.models import TelegramLogs


class TelegramInbound(APIView):
    @async_to_sync
    async def post(self, request: Request | HttpRequest):
        body = json.loads(request.body)

        await TelegramLogs.objects.acreate(
            payload=body, direction=MessageDirection.INBOUND
        )

        await ptb_application.process_update(
            Update.de_json(data=body, bot=ptb_application.bot)
        )

        return Response(status=status.HTTP_200_OK)
