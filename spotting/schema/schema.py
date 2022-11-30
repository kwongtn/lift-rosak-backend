import typing

from asgiref.sync import sync_to_async
from django.contrib.gis.geos import Point
from strawberry.types import Info
from strawberry_django_plus import gql

from common.schema.scalars import GenericMutationReturn
from operation.models import StationLine
from rosak.permissions import IsAdmin, IsLoggedIn, IsRecaptchaChallengePassed
from spotting import models
from spotting.enums import SpottingEventType
from spotting.schema.filters import EventFilter
from spotting.schema.inputs import EventInput, MarkEventAsReadInput
from spotting.schema.scalars import EventScalar


@gql.type
class SpottingScalars:
    events: typing.List[EventScalar] = gql.django.field(
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

        if input.type == SpottingEventType.AT_STATION:
            origin_station_id = (
                StationLine.objects.get(id=input.origin_station).station_id
                if input.origin_station != gql.UNSET
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
        )

        if input.location != gql.UNSET:
            location_input = input.location
            accuracy = (
                location_input.accuracy
                if location_input.accuracy != gql.UNSET
                else None
            )
            altitude_accuracy = (
                location_input.altitude_accuracy
                if location_input.altitude_accuracy != gql.UNSET
                else None
            )
            heading = (
                location_input.heading if location_input.heading != gql.UNSET else None
            )
            speed = location_input.speed if location_input.speed != gql.UNSET else None

            location = Point(x=location_input.longitude, y=location_input.latitude)
            altitude = (
                location_input.altitude
                if location_input.altitude != gql.UNSET
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
