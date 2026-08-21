import typing

import requests
from asgiref.sync import sync_to_async
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
        return await has_admin_claim(info.context.user)


async def has_admin_claim(user) -> bool:
    """Admin check shared by IsAdmin and resolvers with conditional admin logic."""
    if not user:
        return False

    firebase_user = await sync_to_async(auth.get_user)(user.firebase_id)
    claims = firebase_user.custom_claims or {}
    return bool(claims.get("admin", False))
