from typing import List

import strawberry
import strawberry_django

from operation.schema.filters import (
    AssetFilter,
    LineFilter,
    StationFilter,
    StationLineFilter,
    VehicleFilter,
    VehicleTypeFilter,
)
from operation.schema.orderings import VehicleOrder
from operation.schema.scalars import (
    Asset,
    Line,
    Station,
    StationLine,
    Vehicle,
    VehicleType,
)


@strawberry.type
class OperationScalars:
    # TODO: Add back filters
    lines: List[Line] = strawberry_django.field(filters=LineFilter)
    assets: List[Asset] = strawberry_django.field()
    stations: List[Station] = strawberry_django.field(filters=StationFilter)
    stationLines: List[StationLine] = strawberry_django.field(filters=StationLineFilter)
    vehicles: List[Vehicle] = strawberry_django.field(
        filters=VehicleFilter, order=VehicleOrder
    )
    vehicleTypes: List[VehicleType] = strawberry_django.field(filters=VehicleTypeFilter)
    assets: List[Asset] = strawberry_django.field(filters=AssetFilter)


@strawberry.type
class OperationMutations:
    #     create_line: Line = strawberry_django.mutations.create(LineInput)
    #     create_lines: List[Line] = strawberry_django.mutations.create(
    #         LineInput,
    #     )
    #     update_lines: List[Line] = strawberry_django.mutations.update(LinePartialInput)
    #     delete_lines: List[Line] = strawberry_django.mutations.delete()

    #     create_asset: Asset = strawberry_django.mutations.create(AssetInput)
    #     create_assets: List[Asset] = strawberry_django.mutations.create(
    #         AssetInput,
    #     )
    #     update_assets: List[Asset] = strawberry_django.mutations.update(AssetPartialInput)
    #     delete_assets: List[Asset] = strawberry_django.mutations.delete()

    #     create_station: Station = strawberry_django.mutations.create(StationInput)
    #     create_stations: List[Station] = strawberry_django.mutations.create(StationInput)
    #     update_stations: List[Station] = strawberry_django.mutations.update(StationPartialInput)
    #     delete_stations: List[Station] = strawberry_django.mutations.delete()
    pass
