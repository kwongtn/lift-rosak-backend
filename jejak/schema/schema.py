from typing import List, Optional

import strawberry
import strawberry_django
from django.conf import settings
from django.db import DatabaseError, OperationalError
from strawberry_django.pagination import OffsetPaginationInput

from jejak.models import Bus as BusModel
from jejak.models import Location as LocationModel
from jejak.schema.filters import LocationFilter
from jejak.schema.orderings import BusOrder, LocationOrder
from jejak.schema.scalars import Bus, Location


@strawberry.type
class JejakScalars:
    @strawberry_django.field(
        filters=LocationFilter,
        order=LocationOrder,
        pagination=True,
    )
    async def locations(
        self,
        info: strawberry.types.Info,
        filters: Optional[LocationFilter] = strawberry.UNSET,
        order: Optional[LocationOrder] = strawberry.UNSET,
        pagination: Optional[OffsetPaginationInput] = strawberry.UNSET,
    ) -> List[Location]:
        if not getattr(settings, "JEJAK_ENABLED", False):
            raise Exception("Jejak service unavailable")

        try:
            qs = LocationModel.objects.all()
            if filters is not None and filters != strawberry.UNSET:
                qs = strawberry_django.filters.apply(filters, qs, info)
            if order is not None and order != strawberry.UNSET:
                qs = strawberry_django.ordering.apply(order, qs)
            if pagination is not None and pagination != strawberry.UNSET:
                qs = strawberry_django.pagination.apply(pagination, qs)
            return [loc async for loc in qs]
        except (OperationalError, DatabaseError) as e:
            raise Exception(f"Jejak database unavailable: {str(e)}")

    @strawberry_django.field(
        pagination=True,
        order=BusOrder,
    )
    async def buses(
        self,
        info: strawberry.types.Info,
        order: Optional[BusOrder] = strawberry.UNSET,
        pagination: Optional[OffsetPaginationInput] = strawberry.UNSET,
    ) -> List[Bus]:
        if not getattr(settings, "JEJAK_ENABLED", False):
            raise Exception("Jejak service unavailable")

        try:
            qs = BusModel.objects.all()
            if order is not None and order != strawberry.UNSET:
                qs = strawberry_django.ordering.apply(order, qs)
            if pagination is not None and pagination != strawberry.UNSET:
                qs = strawberry_django.pagination.apply(pagination, qs)
            return [bus async for bus in qs]
        except (OperationalError, DatabaseError) as e:
            raise Exception(f"Jejak database unavailable: {str(e)}")

    @strawberry.field
    async def locations_count(self, filters: Optional[LocationFilter] = None) -> int:
        if not getattr(settings, "JEJAK_ENABLED", False):
            raise Exception("Jejak service unavailable")

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

        try:
            return await LocationModel.objects.filter(**query_dict).acount()
        except (OperationalError, DatabaseError) as e:
            raise Exception(f"Jejak database unavailable: {str(e)}")


@strawberry.type
class JejakMutations:
    pass
