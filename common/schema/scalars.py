from strawberry_django_plus import gql

from common import models


@gql.django.type(models.Media)
class Media:
    id: str
    uploader: "User"


@gql.django.type(models.User)
class User:
    id: gql.auto
    firebase_id: str


@gql.type
class GenericMutationReturn:
    ok: bool
