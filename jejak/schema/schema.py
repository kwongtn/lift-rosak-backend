from typing import List, Optional

from strawberry_django_plus import gql

from jejak.models import Location as LocationModel
from jejak.schema.filters import LocationFilter
from jejak.schema.orderings import BusOrder, LocationOrder
from jejak.schema.scalars import Bus, Location


@gql.type
class JejakScalars:
    locations: List[Location] = gql.django.field(
        filters=LocationFilter,
        order=LocationOrder,
        pagination=True,
    )
    buses: List[Bus] = gql.django.field(
        pagination=True,
        order=BusOrder,
    )

    @gql.field
    async def locations_count(self, filters: Optional[LocationFilter] = None) -> int:
        query_dict = {
            "bus_id": filters.bus_id,
        }

        if filters.dt_received_range:
            query_dict["dt_received__range"] = (
                min(filters.dt_received_range),
                max(filters.dt_received_range),
            )

        if filters.dt_gps_range:
            query_dict["dt_gps__range"] = (
                min(filters.dt_gps_range),
                max(filters.dt_gps_range),
            )

        return await LocationModel.objects.filter(**query_dict).acount()


@gql.type
class JejakMutations:
    pass
