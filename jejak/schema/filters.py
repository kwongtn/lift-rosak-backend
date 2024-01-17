from datetime import datetime
from typing import List

import strawberry
import strawberry_django

from jejak import models


@strawberry_django.filters.filter(models.Location)
class LocationFilter:
    id: strawberry.ID
    bus_id: strawberry.ID
    dt_received_range: List[datetime]
    dt_gps_range: List[datetime]

    def filter_dt_received_range(self, queryset):
        return queryset.filter(
            dt_received__range=(
                min(self.dt_received_range),
                max(self.dt_received_range),
            )
        )

    def filter_dt_gps_range(self, queryset):
        return queryset.filter(
            dt_gps__range=(
                min(self.dt_gps_range),
                max(self.dt_gps_range),
            )
        )
