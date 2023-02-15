from strawberry_django_plus import gql

from jejak import models


@gql.django.filters.filter(models.Location)
class LocationFilter:
    id: gql.ID
    bus_id: gql.ID
