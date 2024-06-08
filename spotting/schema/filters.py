from datetime import datetime
from typing import Optional

import strawberry
import strawberry_django
from django.db.models import F, Q, QuerySet, Subquery
from strawberry.types import Info
from strawberry_django import (
    BaseFilterLookup,
    DateFilterLookup,
    DatetimeFilterLookup,
    FilterLookup,
)

from operation.schema.filters import VehicleFilter
from spotting import models


@strawberry_django.filters.filter(models.Event)
class EventFilter:
    id: strawberry.auto
    type: Optional[BaseFilterLookup[str]]
    created: Optional[DatetimeFilterLookup[datetime]]
    spotted: Optional[DateFilterLookup[datetime]]
    notes: Optional[FilterLookup[str]]
    status: Optional[FilterLookup[str]]
    is_anonymous: Optional[bool]

    vehicle: Optional["VehicleFilter"]

    @strawberry_django.filter_field
    def has_notes(self, value: Optional[bool], prefix) -> Q:
        return ~Q(notes="") if value else Q(notes="")

    @strawberry_django.filter_field
    def different_status_than_vehicle(self, value: Optional[bool], prefix) -> Q:
        return (
            ~Q(vehicle__status=F("status")) if value else Q(vehicle__status=F("status"))
        )

    @strawberry_django.filter_field
    def is_read(
        self, queryset: QuerySet, value: Optional[bool], prefix, info: Info
    ) -> tuple[QuerySet, Q]:
        if not info.context.user:
            return queryset.none(), Q()

        read_filter = models.EventRead.objects.filter(reader_id=info.context.user.id)

        if value:
            return queryset, Q(
                id__in=Subquery(read_filter.values_list("event_id", flat=True))
            )
        else:
            return queryset, ~Q(
                id__in=Subquery(read_filter.values_list("event_id", flat=True))
            )

    @strawberry_django.filter_field
    def only_mine(
        self, queryset: QuerySet, value: Optional[bool], prefix, info: Info
    ) -> tuple[QuerySet, Q]:
        if not info.context.user:
            return queryset.none(), Q()

        return queryset, Q(reporter_id=info.context.user.id)

    @strawberry_django.filter_field
    def free_search(self, value: Optional[str], prefix) -> Q:
        return (
            Q(notes__icontains=value)
            | Q(origin_station__display_name__icontains=value)
            | Q(destination_station__display_name__icontains=value)
            | Q(vehicle__identification_no__icontains=value)
            | Q(vehicle__nickname__icontains=value)
        )
