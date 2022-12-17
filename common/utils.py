import dataclasses

from asgiref.sync import sync_to_async
from django.http import HttpRequest
from firebase_admin import auth

from common.models import User


@dataclasses.dataclass
class FirebaseUser:
    def __init__(self, request: HttpRequest):
        self.request = request

    @sync_to_async
    def get_current_user(self):
        auth_key: str = self.request.headers.get("Firebase-Auth-Key", None)

        if auth_key is None:
            return None

        key_contents = auth.verify_id_token(auth_key)
        user = User.objects.get_or_create(
            firebase_id=key_contents["uid"],
            defaults={"firebase_id": key_contents["uid"]},
        )[0]

        return user


def get_date_key(year: int, month: int = None, day: int = None):
    return_str = f"{year:04}"

    if month is not None:
        return_str += f"-{month:02}"

    if day is not None:
        return_str += f"-{day:02}"

    return return_str
