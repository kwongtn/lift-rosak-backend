from strawberry_django_plus import gql

from jejak import models


@gql.django.ordering.order(models.Location)
class LocationOrder:
    id: gql.auto
    dt_received: gql.auto
    dt_gps: gql.auto
