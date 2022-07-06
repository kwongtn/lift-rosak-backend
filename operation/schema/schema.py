import typing

import strawberry
import strawberry_django

from operation.schema.filters import AssetFilter, LineFilter, StationFilter
from operation.schema.inputs import (
    AssetInput,
    AssetPartialInput,
    LineInput,
    LinePartialInput,
    StationInput,
    StationPartialInput,
)
from operation.schema.scalars import Asset, Line, Station


@strawberry.type
class OperationScalars:
    lines: typing.List[Line] = strawberry_django.field(filters=LineFilter)
    assets: typing.List[Asset] = strawberry_django.field(filters=AssetFilter)
    stations: typing.List[Station] = strawberry_django.field(
        filters=StationFilter,
    )


@strawberry.type
class OperationMutations:
    create_line: Line = strawberry_django.mutations.create(LineInput)
    create_lines: typing.List[Line] = strawberry_django.mutations.create(
        LineInput,
    )
    update_lines: typing.List[Line] = strawberry_django.mutations.update(
        LinePartialInput
    )
    delete_lines: typing.List[Line] = strawberry_django.mutations.delete()

    create_asset: Asset = strawberry_django.mutations.create(AssetInput)
    create_assets: typing.List[Asset] = strawberry_django.mutations.create(
        AssetInput,
    )
    update_assets: typing.List[Asset] = strawberry_django.mutations.update(
        AssetPartialInput
    )
    delete_assets: typing.List[Asset] = strawberry_django.mutations.delete()

    create_station: Station = strawberry_django.mutations.create(StationInput)
    create_stations: typing.List[Station] = strawberry_django.mutations.create(
        StationInput
    )
    update_stations: typing.List[Station] = strawberry_django.mutations.update(
        StationPartialInput
    )
    delete_stations: typing.List[Station] = strawberry_django.mutations.delete()
