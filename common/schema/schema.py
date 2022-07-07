from typing import List

import strawberry
import strawberry_django

from common.schema.filters import MediaFilter, UserFilter
from common.schema.inputs import MediaInput, UserInput
from common.schema.scalars import Media, User


@strawberry.type
class CommonScalars:
    medias: List[Media] = strawberry_django.field(filters=MediaFilter)
    users: List[User] = strawberry_django.field(filters=UserFilter)


@strawberry.type
class CommonMutations:
    create_media: Media = strawberry_django.mutations.create(MediaInput)
    create_medias: List[Media] = strawberry_django.mutations.create(MediaInput)
    delete_medias: List[Media] = strawberry_django.mutations.delete()

    create_user: User = strawberry_django.mutations.create(UserInput)
    create_users: List[User] = strawberry_django.mutations.create(UserInput)
    delete_users: List[User] = strawberry_django.mutations.delete()
