import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import ListConnectionWithTotalCount

from common.models import User
from common.schema.inputs import UserInput
from common.schema.scalars import MediaType, UserScalar
from rosak.permissions import IsLoggedIn


@strawberry.type
class CommonScalars:
    medias: ListConnectionWithTotalCount[MediaType] = strawberry_django.connection()

    @strawberry.field(permission_classes=[IsLoggedIn])
    async def user(self, info: Info) -> UserScalar:
        if not info.context.user:
            return None

        from common.models import User

        return await User.objects.aget(id=info.context.user.id)


@strawberry.type
class CommonMutations:
    #     create_medias: List[Media] = strawberry_django.mutations.create(MediaInput)
    #     delete_medias: List[Media] = strawberry_django.mutations.delete()
    pass

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def update_user(self, input: UserInput, info: Info) -> UserScalar:
        user: User = info.context.user
        user.nickname = input.nickname
        await user.asave()

        return user
