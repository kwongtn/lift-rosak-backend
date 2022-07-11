import typing

import strawberry
import strawberry_django

from spotting.schema.inputs import EventInput
from spotting.schema.scalars import Event


@strawberry.type
class SpottingScalars:
    events: typing.List[Event] = strawberry_django.field(
        # filters=EventFilter,
    )


@strawberry.type
class SpottingMutations:
    add_event: Event = strawberry_django.mutations.create(EventInput)
    delete_event: Event = strawberry_django.mutations.delete(EventInput)
