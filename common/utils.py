from asgiref.sync import sync_to_async
from django.http import HttpRequest
from firebase_admin import auth

from common.models import User


@sync_to_async
def get_user_from_firebase_key(request: HttpRequest):
    auth_key: str = request.headers.get("Firebase-Auth-Key", None)

    if auth_key is None:
        return None

    key_contents = auth.verify_id_token(auth_key)
    user = User.objects.get_or_create(
        firebase_id=key_contents["uid"],
        defaults={"firebase_id": key_contents["uid"]},
    )[0]

    return user
