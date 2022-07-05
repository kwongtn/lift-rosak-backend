import typing

import strawberry
import strawberry_django

from operation.schema.filters import AssetFilter, LineFilter, StationFilter
from operation.schema.scalars import Asset, Line, Station


@strawberry.type
class OperationScalars:
    lines: typing.List[Line] = strawberry_django.field(filters=LineFilter)
    assets: typing.List[Asset] = strawberry_django.field(filters=AssetFilter)
    stations: typing.List[Station] = strawberry_django.field(
        filters=StationFilter,
    )
