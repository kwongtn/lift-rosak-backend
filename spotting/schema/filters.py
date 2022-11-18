from datetime import date, timedelta

from django.db.models import F, Q, Subquery
from strawberry.types import Info
from strawberry_django_plus import gql

from spotting import models


@gql.django.filters.filter(models.Event)
class EventFilter:
    id: gql.auto
    days_before: int
    has_notes: bool
    last_n: int
    different_status_than_vehicle: bool
    is_read: bool
    only_mine: bool
    is_anonymous: bool

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_days_before(self, queryset):
        return queryset.filter(
            created__gt=date.today() - timedelta(days=self.days_before)
        )

    def filter_is_anonymous(self, queryset):
        return queryset.filter(is_anonymous=self.is_anonymous)

    def filter_has_notes(self, queryset):
        filter = ~Q(notes="") if self.has_notes else Q(notes="")
        return queryset.filter(filter)

    def filter_last_n(self, queryset):
        return queryset.order_by("-created")[: self.last_n]

    def filter_different_status_than_vehicle(self, queryset):
        return queryset.filter(~Q(vehicle__status=F("status")))

    def filter_is_read(self, queryset, info: Info):
        if not info.context.user:
            return queryset.none()

        read_filter = models.EventRead.objects.filter(reader_id=info.context.user.id)

        if self.is_read:
            query = Q(id__in=Subquery(read_filter.values_list("event_id", flat=True)))
        else:
            query = ~Q(id__in=Subquery(read_filter.values_list("event_id", flat=True)))

        return queryset.filter(query)

    def filter_only_mine(self, queryset, info: Info):
        if not info.context.user:
            return queryset.none()

        return queryset.filter(reporter_id=info.context.user.id)
