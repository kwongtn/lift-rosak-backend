from datetime import date, datetime
from typing import List

import strawberry
import strawberry_django
from django.db.models import F, Q, Subquery
from strawberry.types import Info

from spotting import models


@strawberry_django.filters.filter(models.Event)
class EventFilter:
    id: strawberry.auto
    vehicle_id: strawberry.ID
    type_in: List[str]
    created_start_datetime: datetime
    created_end_datetime: datetime
    has_notes: bool
    notes_contain: str
    different_status_than_vehicle: bool
    status_in: List[str]
    spotted_start_date: date
    spotted_end_date: date
    is_read: bool
    only_mine: bool
    is_anonymous: bool
    free_search: str

    def filter_id(self, queryset):
        return queryset.filter(id=self.id)

    def filter_vehicle_id(self, queryset):
        return queryset.filter(vehicle_id=self.vehicle_id)

    def filter_type_in(self, queryset):
        return queryset.filter(type__in=self.type_in)

    def filter_created_start_datetime(self, queryset):
        date_target = self.created_start_datetime
        if self.created_end_datetime:
            date_target = min([self.created_start_datetime, self.created_end_datetime])

        return queryset.filter(created__gte=date_target)

    def filter_created_end_datetime(self, queryset):
        date_target = self.created_end_datetime
        if self.created_start_datetime:
            date_target = max([self.created_start_datetime, self.created_end_datetime])

        return queryset.filter(created__lte=date_target)

    def filter_spotted_start_date(self, queryset):
        date_target = self.spotted_start_date
        if self.spotted_end_date:
            date_target = min([self.spotted_start_date, self.spotted_end_date])

        return queryset.filter(spotting_date__gte=date_target)

    def filter_spotted_end_date(self, queryset):
        date_target = self.spotted_end_date
        if self.spotted_start_date:
            date_target = max([self.spotted_start_date, self.spotted_end_date])

        return queryset.filter(spotting_date__lte=date_target)

    def filter_is_anonymous(self, queryset):
        return queryset.filter(is_anonymous=self.is_anonymous)

    def filter_has_notes(self, queryset):
        filter = ~Q(notes="") if self.has_notes else Q(notes="")
        return queryset.filter(filter)

    def filter_different_status_than_vehicle(self, queryset):
        return queryset.filter(~Q(vehicle__status=F("status")))

    def filter_status_in(self, queryset):
        return queryset.filter(status__in=self.status_in)

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

    def filter_free_search(self, queryset):
        return queryset.filter(
            Q(notes__icontains=self.free_search)
            | Q(origin_station__display_name__icontains=self.free_search)
            | Q(destination_station__display_name__icontains=self.free_search)
            | Q(vehicle__identification_no__icontains=self.free_search)
            | Q(vehicle__nickname__icontains=self.free_search)
        )
