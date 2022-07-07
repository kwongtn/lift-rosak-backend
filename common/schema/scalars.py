import strawberry
import strawberry.django

from common import models


@strawberry.django.type(models.Media)
class Media:
    id: str
    uploader: "User"


@strawberry.django.type(models.User)
class User:
    id: strawberry.auto
    firebase_id: str
