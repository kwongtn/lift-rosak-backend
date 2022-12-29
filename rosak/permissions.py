import typing

import requests
from django.conf import settings
from django.http import request as Request
from firebase_admin import auth
from strawberry.permission import BasePermission
from strawberry.types import Info


class IsRecaptchaChallengePassed(BasePermission):
    message = "You shall not pass. Contact an admin for more info."

    async def has_permission(self, source: typing.Any, info: Info, **kwargs) -> bool:
        request: Request = info.context["request"]

        if request.headers.get("G-Recaptcha-Response", None) is None:
            return False

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


class IsLoggedIn(BasePermission):
    message = "You are not logged in."

    async def has_permission(self, source: typing.Any, info: Info, **kwargs) -> bool:
        return bool(info.context.user)


class IsAdmin(BasePermission):
    message = "You don't have the appropriate permissions to perform this action."

    async def has_permission(self, source: typing.Any, info: Info, **kwargs) -> bool:
        if info.context.user:
            user = auth.get_user(info.context.user.firebase_id)
            if user.custom_claims:
                return user.custom_claims.get("admin", False)

        return False
