import strawberry
import strawberry_django

from incident import models


@strawberry_django.ordering.order(models.CalendarIncident)
class CalendarIncidentOrder:
    id: strawberry.auto
    order: strawberry.auto
    impact_factor: strawberry.auto
    start_datetime: strawberry.auto
    end_datetime: strawberry.auto
