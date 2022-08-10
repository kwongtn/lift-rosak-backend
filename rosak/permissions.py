import typing

import requests
from django.conf import settings
from starlette.requests import Request
from starlette.websockets import WebSocket
from strawberry.permission import BasePermission
from strawberry.types import Info


class IsRecaptchaChallengePassed(BasePermission):
    message = "You shall not pass. Contact an admin for more info."

    async def has_permission(self, source: typing.Any, info: Info, **kwargs) -> bool:
        request: typing.Union[Request, WebSocket] = info.context["request"]

        # Check if captcha is valid
        response = requests.request(
            "POST",
            "https://www.google.com/recaptcha/api/siteverify",
            params={
                "secret": settings.RECAPTCHA_KEY,
                "response": request.headers["G-Recaptcha-Response"],
            },
        ).json()

        if not response["success"] or response["score"] < settings.RECAPTCHA_MIN_SCORE:
            return False

        return True
