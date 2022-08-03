import typing

import requests
from asgiref.sync import sync_to_async
from django.conf import settings
from firebase_admin import auth
from strawberry.types import Info
from strawberry_django_plus import gql

from common.models import User
from common.schema.scalars import GenericMutationReturn
from operation.models import StationLine
from spotting import models
from spotting.enums import SpottingEventType
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
    @sync_to_async
    def add_event(self, input: EventInput, info: Info) -> GenericMutationReturn:
        # Check if captcha is valid
        response = requests.request(
            "POST",
            "https://www.google.com/recaptcha/api/siteverify",
            params={
                "secret": settings.RECAPTCHA_KEY,
                "response": input.captcha_key,
            },
        ).json()

        if not response["success"] or response["score"] < settings.RECAPTCHA_MIN_SCORE:
            raise ConnectionRefusedError("Recaptcha verification failed.")

        key_contents = auth.verify_id_token(input.auth_key)
        reporter_id = User.objects.get_or_create(
            firebase_id=key_contents["uid"],
            defaults={"firebase_id": key_contents["uid"]},
        )[0].id

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
            reporter_id=reporter_id,
            vehicle_id=input.vehicle,
            notes=notes,
            status=input.status,
            type=input.type,
            origin_station_id=origin_station_id,
            destination_station_id=destination_station_id,
            is_anonymous=is_anonymous,
        )

        return GenericMutationReturn(ok=True)
