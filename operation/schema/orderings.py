from strawberry_django_plus import gql

from operation import models


@gql.django.ordering.order(models.Vehicle)
class VehicleOrder:
    id: gql.auto
    identification_no: gql.auto
    status: gql.auto
    in_service_since: gql.auto
