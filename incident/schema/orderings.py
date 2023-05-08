from strawberry_django_plus import gql

from incident import models


@gql.django.ordering.order(models.CalendarIncident)
class CalendarIncidentOrder:
    id: gql.auto
    order: gql.auto
    impact_factor: gql.auto
