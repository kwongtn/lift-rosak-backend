import strawberry
import strawberry_django

from common import models


@strawberry_django.input(models.Media)
class MediaInput:
    # file: fileupload
    uploader_id: strawberry.ID


@strawberry_django.input(models.User)
class UserInput:
    firebase_id: str
