from typing import List

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
        filters: strawberry.Maybe[LocationFilter] = None,
        order: strawberry.Maybe[LocationOrder] = None,
        pagination: strawberry.Maybe[OffsetPaginationInput] = None,
    ) -> List[Location]:
        if not getattr(settings, "JEJAK_ENABLED", False):
            raise Exception("Jejak service unavailable")

        try:
            qs = LocationModel.objects.all()
            if filters is not None:
                filters_val = filters.value
                qs = strawberry_django.filters.apply(filters_val, qs, info)
            if order is not None:
                order_val = order.value
                qs = strawberry_django.ordering.apply(order_val, qs)
            if pagination is not None:
                pagination_val = pagination.value
                qs = strawberry_django.pagination.apply(pagination_val, qs)
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
        order: strawberry.Maybe[BusOrder] = None,
        pagination: strawberry.Maybe[OffsetPaginationInput] = None,
    ) -> List[Bus]:
        if not getattr(settings, "JEJAK_ENABLED", False):
            raise Exception("Jejak service unavailable")

        try:
            qs = BusModel.objects.all()
            if order is not None:
                order_val = order.value
                qs = strawberry_django.ordering.apply(order_val, qs)
            if pagination is not None:
                pagination_val = pagination.value
                qs = strawberry_django.pagination.apply(pagination_val, qs)
            return [bus async for bus in qs]
        except (OperationalError, DatabaseError) as e:
            raise Exception(f"Jejak database unavailable: {str(e)}")

    @strawberry.field
    async def locations_count(
        self, filters: strawberry.Maybe[LocationFilter] = None
    ) -> int:
        if not getattr(settings, "JEJAK_ENABLED", False):
            raise Exception("Jejak service unavailable")

        if filters is None:
            return 0

        filters_val = filters.value
        query_dict = {}

        if filters_val.bus_id is not None:
            query_dict["bus_id"] = filters_val.bus_id.value

        if (
            filters_val.dt_received_range is not None
            and len(filters_val.dt_received_range.value) > 0
        ):
            dt_received_range = filters_val.dt_received_range.value
            query_dict["dt_received__range"] = (
                min(dt_received_range),
                max(dt_received_range),
            )

        if (
            filters_val.dt_gps_range is not None
            and len(filters_val.dt_gps_range.value) > 0
        ):
            dt_gps_range = filters_val.dt_gps_range.value
            query_dict["dt_gps__range"] = (
                min(dt_gps_range),
                max(dt_gps_range),
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
