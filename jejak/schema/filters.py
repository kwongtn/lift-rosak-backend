from datetime import datetime
from typing import List

import strawberry
import strawberry_django

from jejak import models


@strawberry_django.filters.filter(models.Location)
class LocationFilter:
    id: strawberry.Maybe[strawberry.ID] = None
    bus_id: strawberry.Maybe[strawberry.ID] = None
    dt_received_range: strawberry.Maybe[List[datetime]] = None
    dt_gps_range: strawberry.Maybe[List[datetime]] = None

    def filter_dt_received_range(self, queryset):
        if self.dt_received_range is None:
            return queryset
        return queryset.filter(
            dt_received__range=(
                min(self.dt_received_range.value),
                max(self.dt_received_range.value),
            )
        )

    def filter_dt_gps_range(self, queryset):
        if self.dt_gps_range is None:
            return queryset
        return queryset.filter(
            dt_gps__range=(
                min(self.dt_gps_range.value),
                max(self.dt_gps_range.value),
            )
        )
