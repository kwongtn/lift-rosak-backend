import typing
from datetime import timedelta
from typing import Any, Optional

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from django.contrib.gis.geos import Point
from django.utils.timezone import now
from strawberry.types import Info

from common.schema.scalars import GenericMutationReturn
from operation.models import StationLine
from rosak.permissions import IsAdmin, IsLoggedIn, IsRecaptchaChallengePassed
from spotting import models
from spotting.enums import SpottingDataSource, SpottingEventType
from spotting.schema.filters import EventFilter
from spotting.schema.inputs import DeleteEventInput, EventInput, MarkEventAsReadInput
from spotting.schema.orderings import EventOrder
from spotting.schema.resolvers import get_events_count
from spotting.schema.scalars import EventScalar


def _maybe_value(maybe_field: Any, default: Optional[Any] = None) -> Any:
    """Unwrap a Strawberry Maybe field.

    Returns `default` when the field was omitted (UNSET) or is a plain
    None; otherwise returns the wrapped payload (`Some(value)` -> `value`,
    `Some(None)` -> `None`).
    """
    if maybe_field is None or maybe_field is strawberry.UNSET:
        return default
    return maybe_field.value


@strawberry.type
class SpottingScalars:
    events: typing.List[EventScalar] = strawberry_django.field(
        filters=EventFilter, pagination=True, order=EventOrder
    )
    events_count: int = strawberry_django.field(
        resolver=get_events_count,
        description="Number of events",
    )

    # import strawberry_django
    # from strawberry_django.relay import ListConnectionWithTotalCount
    # event_relay: typing.Optional[EventRelay] = relay.node()
    # event_relay_connection: ListConnectionWithTotalCount[
    #     EventRelay
    # ] = strawberry_django.connection()


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

        notes = _maybe_value(input.notes, "")
        is_anonymous = _maybe_value(input.is_anonymous, False)
        wheel_status = _maybe_value(input.wheel_status, None)
        run_number = _maybe_value(input.run_number, None)
        origin_station_input = _maybe_value(input.origin_station, None)
        destination_station_input = _maybe_value(input.destination_station, None)

        origin_station_id = None
        destination_station_id = None
        if input.type == SpottingEventType.BETWEEN_STATIONS:
            station_line_dict = {
                str(station_line.id): station_line.station_id
                for station_line in StationLine.objects.filter(
                    id__in=[
                        station_line_id
                        for station_line_id in (
                            origin_station_input,
                            destination_station_input,
                        )
                        if station_line_id is not None
                    ]
                )
            }

            if origin_station_input is not None:
                origin_station_id = station_line_dict[str(origin_station_input)]

            if destination_station_input is not None:
                destination_station_id = station_line_dict[
                    str(destination_station_input)
                ]

        if input.type == SpottingEventType.AT_STATION:
            if origin_station_input is not None:
                origin_station_id = StationLine.objects.get(
                    id=origin_station_input
                ).station_id

        event_source = models.EventSource.objects.filter(
            name=SpottingDataSource.SITE
        ).first()

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
            run_number=run_number,
            wheel_status=wheel_status,
            data_source_id=event_source.id,
        )

        location_input = _maybe_value(input.location, None)
        if location_input is not None:
            accuracy = _maybe_value(location_input.accuracy, None)
            altitude_accuracy = _maybe_value(location_input.altitude_accuracy, None)
            heading = _maybe_value(location_input.heading, None)
            speed = _maybe_value(location_input.speed, None)
            altitude = _maybe_value(location_input.altitude, None)

            location = Point(
                x=location_input.longitude.value,
                y=location_input.latitude.value,
            )

            models.LocationEvent.objects.create(
                event_id=event.id,
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
            wheel_status=event.wheel_status,
        )

    @strawberry.mutation(
        permission_classes=[IsLoggedIn, IsRecaptchaChallengePassed, IsAdmin]
    )
    async def mark_as_read(
        self, input: MarkEventAsReadInput, info: Info
    ) -> GenericMutationReturn:
        await models.EventRead.objects.abulk_create(
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
