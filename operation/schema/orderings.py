import strawberry
import strawberry_django

from operation import models


@strawberry_django.ordering.order(models.Vehicle)
class VehicleOrder:
    id: strawberry.auto
    identification_no: strawberry.auto
    status: strawberry.auto
    in_service_since: strawberry.auto
