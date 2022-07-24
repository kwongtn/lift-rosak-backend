import typing

from firebase_admin import auth
from strawberry_django_plus import gql

from common.models import User
from common.schema.scalars import GenericMutationReturn
from spotting import models
from spotting.schema.inputs import EventInput
from spotting.schema.scalars import Event


@gql.type
class SpottingScalars:
    events: typing.List[Event] = gql.django.field(
        # filters=EventFilter,
    )


@gql.type
class SpottingMutations:
    @gql.mutation
    def add_event(self, input: EventInput) -> GenericMutationReturn:
        key_contents = auth.verify_id_token(input.auth_key)
        reporter_id = User.objects.get_or_create(
            firebase_id=key_contents["uid"],
            defaults={"firebase_id": key_contents["uid"]},
        )[0].id

        notes = input.notes if input.notes != gql.UNSET else ""
        origin_station_id = (
            input.origin_station if input.origin_station != gql.UNSET else None
        )

        destination_station_id = (
            input.destination_station
            if input.destination_station != gql.UNSET
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
