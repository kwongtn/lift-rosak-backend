import strawberry
import strawberry_django

from jejak import models


@strawberry_django.ordering.order(models.Location)
class LocationOrder:
    id: strawberry.auto
    dt_received: strawberry.auto
    dt_gps: strawberry.auto


@strawberry_django.ordering.order(models.Bus)
class BusOrder:
    id: strawberry.auto
    identifier: strawberry.auto
