import typing

import strawberry
import strawberry_django

from spotting.schema.scalars import Event


@strawberry.type
class SpottingScalars:
    events: typing.List[Event] = strawberry_django.field(
        # filters=EventFilter,
    )
