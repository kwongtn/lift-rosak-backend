import dataclasses
from datetime import date
from typing import List

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


def date_splitter(input_date: date, type: str = "days") -> List[int]:
    return_list = []
    if type in ["years", "months", "days"]:
        return_list.append(input_date.year)
        if type in ["months", "days"]:
            return_list.append(input_date.month)
            if type == "days":
                return_list.append(input_date.day)
    return return_list
