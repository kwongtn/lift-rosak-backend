from strawberry_django_plus import gql

from spotting import models


@gql.django.ordering.order(models.Event)
class EventOrder:
    id: gql.auto
    spotting_date: gql.auto
    created: gql.auto
