from datetime import date, timedelta

from django.db.models import F, Q
from strawberry_django_plus import gql

from spotting import models


@gql.django.filters.filter(models.Event)
class EventFilter:
    days_before: int
    has_notes: bool
    last_n: int
    different_status_than_vehicle: bool

    def filter_days_before(self, queryset):
        return queryset.filter(
            created__gt=date.today() - timedelta(days=self.days_before)
        )

    def filter_has_notes(self, queryset):
        filter = ~Q(notes="") if self.has_notes else Q(notes="")
        return queryset.filter(filter)

    def filter_last_n(self, queryset):
        return queryset.order_by("-created")[: self.last_n]

    def filter_different_status_than_vehicle(self, queryset):
        return queryset.filter(~Q(vehicle__status=F("status")))
