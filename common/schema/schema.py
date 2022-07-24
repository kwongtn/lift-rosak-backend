from strawberry_django_plus import gql


@gql.type
class CommonScalars:
    # TODO: Filters
    # medias: List[Media] = gql.django.field()
    # users: List[User] = gql.django.field()
    pass


@gql.type
class CommonMutations:
    #     create_media: Media = gql.django.mutations.create(MediaInput)
    #     create_medias: List[Media] = gql.django.mutations.create(MediaInput)
    #     delete_medias: List[Media] = gql.django.mutations.delete()

    #     create_user: User = gql.django.mutations.create(UserInput)
    #     create_users: List[User] = gql.django.mutations.create(UserInput)
    #     delete_users: List[User] = gql.django.mutations.delete()
    pass
