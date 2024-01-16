import strawberry
import strawberry_django

from spotting import models


@strawberry_django.ordering.order(models.Event)
class EventOrder:
    id: strawberry.auto
    spotting_date: strawberry.auto
    created: strawberry.auto
