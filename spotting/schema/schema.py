import typing

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from firebase_admin import auth

from common.models import User
from common.schema.scalars import GenericMutationReturn
from spotting import models
from spotting.schema.inputs import EventInput
from spotting.schema.scalars import Event


@strawberry.type
class SpottingScalars:
    events: typing.List[Event] = strawberry_django.field(
        # filters=EventFilter,
    )


@strawberry.type
class SpottingMutations:
    delete_events: typing.List[Event] = strawberry_django.mutations.delete()

    # add_event: Event = strawberry_django.mutations.create(EventInput)

    @strawberry.mutation
    @sync_to_async
    def add_event(self, input: EventInput) -> GenericMutationReturn:
        key_contents = auth.verify_id_token(input.auth_key)
        reporter_id = User.objects.get_or_create(
            firebase_id=key_contents["uid"],
            defaults={"firebase_id": key_contents["uid"]},
        ).id

        notes = input.notes if input.notes != strawberry.UNSET else ""
        origin_station_id = (
            input.origin_station if input.origin_station != strawberry.UNSET else None
        )

        destination_station_id = (
            input.destination_station
            if input.destination_station != strawberry.UNSET
            else None
        )
        models.Event.objects.create(
            spotting_date=input.spotting_date,
            reporter_id=reporter_id,
            vehicle_id=input.vehicle,
            notes=notes,
            status=input.status,
            type=input.type,
            origin_station_id=origin_station_id,
            destination_station_id=destination_station_id,
        )

        return GenericMutationReturn(ok=True)
