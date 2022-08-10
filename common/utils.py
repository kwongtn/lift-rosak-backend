from django.http import request as Request
from firebase_admin import auth
from strawberry.types import Info

from common.models import User


def get_user_from_firebase_key(info: Info):
    request: Request = info.context["request"]

    key_contents = auth.verify_id_token(request.headers["Firebase-Auth-Key"])
    return User.objects.get_or_create(
        firebase_id=key_contents["uid"],
        defaults={"firebase_id": key_contents["uid"]},
    )[0]
