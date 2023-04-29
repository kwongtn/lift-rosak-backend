from strawberry.types import Info
from strawberry_django_plus import gql

from common.models import User
from common.schema.inputs import UserInput
from common.schema.scalars import UserScalar
from rosak.permissions import IsLoggedIn


@gql.type
class CommonScalars:
    @gql.field(permission_classes=[IsLoggedIn])
    async def user(self, info: Info) -> UserScalar:
        if not info.context.user:
            return None

        from common.models import User

        return await User.objects.aget(id=info.context.user.id)


@gql.type
class CommonMutations:
    #     create_media: Media = gql.django.mutations.create(MediaInput)
    #     create_medias: List[Media] = gql.django.mutations.create(MediaInput)
    #     delete_medias: List[Media] = gql.django.mutations.delete()

    @gql.mutation(permission_classes=[IsLoggedIn])
    async def update_user(self, input: UserInput, info: Info) -> UserScalar:
        user: User = info.context.user
        user.nickname = input.nickname
        await user.asave()

        return user
