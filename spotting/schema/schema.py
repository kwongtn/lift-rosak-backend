import typing

from asgiref.sync import sync_to_async
from strawberry.types import Info
from strawberry_django_plus import gql

from common.schema.scalars import GenericMutationReturn
from operation.models import StationLine
from rosak.permissions import IsAdmin, IsLoggedIn, IsRecaptchaChallengePassed
from spotting import models
from spotting.enums import SpottingEventType
from spotting.schema.filters import EventFilter
from spotting.schema.inputs import EventInput, MarkEventAsReadInput
from spotting.schema.scalars import Event


@gql.type
class SpottingScalars:
    events: typing.List[Event] = gql.django.field(
        filters=EventFilter,
    )


@gql.type
class SpottingMutations:
    @gql.mutation(permission_classes=[IsLoggedIn, IsRecaptchaChallengePassed])
    @sync_to_async
    def add_event(self, input: EventInput, info: Info) -> GenericMutationReturn:
        user_id = info.context.user.id

        notes = input.notes if input.notes != gql.UNSET else ""
        is_anonymous = input.is_anonymous if input.is_anonymous != gql.UNSET else False

        origin_station_id = None
        destination_station_id = None
        if input.type == SpottingEventType.BETWEEN_STATIONS:
            station_line_dict = {
                str(station_line.id): station_line.station_id
                for station_line in StationLine.objects.filter(
                    id__in=[input.origin_station, input.destination_station]
                )
            }

            origin_station_id = (
                station_line_dict[str(input.origin_station)]
                if input.origin_station != gql.UNSET
                else None
            )

            destination_station_id = (
                station_line_dict[str(input.destination_station)]
                if input.destination_station != gql.UNSET
                else None
            )

        models.Event.objects.create(
            spotting_date=input.spotting_date,
            reporter_id=user_id,
            vehicle_id=input.vehicle,
            notes=notes,
            status=input.status,
            type=input.type,
            origin_station_id=origin_station_id,
            destination_station_id=destination_station_id,
            is_anonymous=is_anonymous,
        )

        return GenericMutationReturn(ok=True)

    @gql.mutation(permission_classes=[IsLoggedIn, IsRecaptchaChallengePassed, IsAdmin])
    @sync_to_async
    def mark_as_read(
        self, input: MarkEventAsReadInput, info: Info
    ) -> GenericMutationReturn:
        models.EventRead.objects.bulk_create(
            [
                models.EventRead(
                    event_id=event_id,
                    reader_id=info.context.user.id,
                )
                for event_id in input.event_ids
            ],
            ignore_conflicts=True,
        )

        return GenericMutationReturn(ok=True)
