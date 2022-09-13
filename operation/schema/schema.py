from typing import List

from strawberry_django_plus import gql

from operation.schema.filters import (
    AssetFilter,
    LineFilter,
    StationFilter,
    StationLineFilter,
    VehicleFilter,
    VehicleTypeFilter,
)
from operation.schema.scalars import (
    Asset,
    Line,
    Station,
    StationLine,
    Vehicle,
    VehicleType,
)


@gql.type
class OperationScalars:
    # TODO: Add back filters
    lines: List[Line] = gql.django.field(filters=LineFilter)
    assets: List[Asset] = gql.django.field()
    stations: List[Station] = gql.django.field(filters=StationFilter)
    stationLines: List[StationLine] = gql.django.field(filters=StationLineFilter)
    vehicles: List[Vehicle] = gql.django.field(filters=VehicleFilter)
    vehicleTypes: List[VehicleType] = gql.django.field(filters=VehicleTypeFilter)
    assets: List[Asset] = gql.django.field(filters=AssetFilter)


@gql.type
class OperationMutations:
    #     create_line: Line = gql.django.mutations.create(LineInput)
    #     create_lines: List[Line] = gql.django.mutations.create(
    #         LineInput,
    #     )
    #     update_lines: List[Line] = gql.django.mutations.update(LinePartialInput)
    #     delete_lines: List[Line] = gql.django.mutations.delete()

    #     create_asset: Asset = gql.django.mutations.create(AssetInput)
    #     create_assets: List[Asset] = gql.django.mutations.create(
    #         AssetInput,
    #     )
    #     update_assets: List[Asset] = gql.django.mutations.update(AssetPartialInput)
    #     delete_assets: List[Asset] = gql.django.mutations.delete()

    #     create_station: Station = gql.django.mutations.create(StationInput)
    #     create_stations: List[Station] = gql.django.mutations.create(StationInput)
    #     update_stations: List[Station] = gql.django.mutations.update(StationPartialInput)
    #     delete_stations: List[Station] = gql.django.mutations.delete()
    pass
