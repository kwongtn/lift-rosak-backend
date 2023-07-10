import typing
from datetime import timedelta

import strawberry
from asgiref.sync import sync_to_async
from django.contrib.gis.geos import Point
from django.utils.timezone import now
from strawberry import relay
from strawberry.types import Info

from common.schema.scalars import GenericMutationReturn
from operation.models import StationLine
from rosak.permissions import IsAdmin, IsLoggedIn, IsRecaptchaChallengePassed
from spotting import models
from spotting.enums import SpottingEventType
from spotting.schema.filters import EventFilter
from spotting.schema.inputs import DeleteEventInput, EventInput, MarkEventAsReadInput
from spotting.schema.orderings import EventOrder
from spotting.schema.resolvers import get_events_count
from spotting.schema.scalars import EventRelay, EventScalar


@strawberry.type
class SpottingScalars:
    events: typing.List[EventScalar] = strawberry.django.field(
        filters=EventFilter, pagination=True, order=EventOrder
    )
    events_count: int = strawberry.django.field(
        resolver=get_events_count,
        description="Number of events",
    )
    # event_relay: typing.Optional[EventRelay] = relay.node()
    event_relay_connection: relay.Connection[EventRelay] = relay.connection()


@strawberry.type
class SpottingMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn, IsRecaptchaChallengePassed])
    async def delete_event(
        self, input: DeleteEventInput, info: Info
    ) -> GenericMutationReturn:
        user_id = info.context.user.id

        to_delete = models.Event.objects.filter(
            reporter_id=user_id,
            id=input.id,
            # User can only delete events from last 3 days
            created__gte=now() - timedelta(days=3),
        )
        if await to_delete.aexists():
            await to_delete.adelete()
            return GenericMutationReturn(ok=True)
        else:
            return GenericMutationReturn(ok=False)

    @strawberry.mutation(
        permission_classes=[
            IsLoggedIn,
            # IsRecaptchaChallengePassed,
        ]
    )
    @sync_to_async
    def add_event(self, input: EventInput, info: Info) -> EventScalar:
        user_id = info.context.user.id

        notes = input.notes if input.notes != strawberry.UNSET else ""
        is_anonymous = (
            input.is_anonymous if input.is_anonymous != strawberry.UNSET else False
        )

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
                if input.origin_station != strawberry.UNSET
                else None
            )

            destination_station_id = (
                station_line_dict[str(input.destination_station)]
                if input.destination_station != strawberry.UNSET
                else None
            )

        if input.type == SpottingEventType.AT_STATION:
            origin_station_id = (
                StationLine.objects.get(id=input.origin_station).station_id
                if input.origin_station != strawberry.UNSET
                else None
            )

        event = models.Event.objects.create(
            spotting_date=input.spotting_date,
            reporter_id=user_id,
            vehicle_id=input.vehicle,
            notes=notes,
            status=input.status,
            type=input.type,
            origin_station_id=origin_station_id,
            destination_station_id=destination_station_id,
            is_anonymous=is_anonymous,
            run_number=input.run_number,
        )

        if input.location != strawberry.UNSET:
            location_input = input.location
            accuracy = (
                location_input.accuracy
                if location_input.accuracy != strawberry.UNSET
                else None
            )
            altitude_accuracy = (
                location_input.altitude_accuracy
                if location_input.altitude_accuracy != strawberry.UNSET
                else None
            )
            heading = (
                location_input.heading
                if location_input.heading != strawberry.UNSET
                else None
            )
            speed = (
                location_input.speed
                if location_input.speed != strawberry.UNSET
                else None
            )

            location = Point(x=location_input.longitude, y=location_input.latitude)
            altitude = (
                location_input.altitude
                if location_input.altitude != strawberry.UNSET
                else None
            )

            models.LocationEvent.objects.create(
                event=event,
                location=location,
                accuracy=accuracy,
                altitude=altitude,
                altitude_accuracy=altitude_accuracy,
                heading=heading,
                speed=speed,
            )

        return EventScalar(
            id=event.id,
            created=event.created,
            spotting_date=event.spotting_date,
            vehicle=event.vehicle,
            notes=event.notes,
            status=event.status,
            type=event.type,
            run_number=event.run_number,
            origin_station=event.origin_station,
            destination_station=event.destination_station,
        )

    @strawberry.mutation(
        permission_classes=[IsLoggedIn, IsRecaptchaChallengePassed, IsAdmin]
    )
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
