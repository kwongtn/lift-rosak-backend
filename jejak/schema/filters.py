from datetime import datetime
from typing import List

from strawberry_django_plus import gql

from jejak import models


@gql.django.filters.filter(models.Location)
class LocationFilter:
    id: gql.ID
    bus_id: gql.ID
    dt_received_range: List[datetime]
    dt_gps_range: List[datetime]

    def filter_dt_received_range(self, queryset):
        return queryset.filter(
            dt_received__range=(
                min(self.dt_received_range),
                max(self.dt_received_range),
            )
        )

    def filter_gps_range(self, queryset):
        return queryset.filter(
            dt_gps__range=(
                min(self.dt_gps_range),
                max(self.dt_gps_range),
            )
        )
