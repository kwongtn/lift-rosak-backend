import strawberry_django

from common import models

# from strawberry.file_uploads import Upload


# @strawberry_django.input(models.Media)
# class MediaInput:
#     file: Upload


@strawberry_django.input(models.User)
class UserInput:
    nickname: str
