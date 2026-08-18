from typing import List, Optional

import strawberry
import strawberry_django

from jejak.models import Location as LocationModel
from jejak.schema.filters import LocationFilter
from jejak.schema.orderings import BusOrder, LocationOrder
from jejak.schema.scalars import Bus, Location


@strawberry.type
class JejakScalars:
    locations: List[Location] = strawberry_django.field(
        filters=LocationFilter,
        order=LocationOrder,
        pagination=True,
    )
    buses: List[Bus] = strawberry_django.field(
        pagination=True,
        order=BusOrder,
    )

    @strawberry.field
    async def locations_count(self, filters: Optional[LocationFilter] = None) -> int:
        if filters is None:
            return 0

        query_dict = {}

        if filters.bus_id is not None and filters.bus_id != strawberry.UNSET:
            query_dict["bus_id"] = filters.bus_id

        if (
            filters.dt_received_range is not None
            and filters.dt_received_range != strawberry.UNSET
            and len(filters.dt_received_range) > 0
        ):
            query_dict["dt_received__range"] = (
                min(filters.dt_received_range),
                max(filters.dt_received_range),
            )

        if (
            filters.dt_gps_range is not None
            and filters.dt_gps_range != strawberry.UNSET
            and len(filters.dt_gps_range) > 0
        ):
            query_dict["dt_gps__range"] = (
                min(filters.dt_gps_range),
                max(filters.dt_gps_range),
            )

        if not query_dict:
            return 0

        return await LocationModel.objects.filter(**query_dict).acount()


@strawberry.type
class JejakMutations:
    pass
