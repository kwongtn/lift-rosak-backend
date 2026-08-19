from django.contrib.gis.geos import Point
from django.test import TestCase

from common.models import User
from operation.models import Line, Station, StationLine, Vehicle, VehicleType
from rosak.tests import execute_graphql_async
from spotting.enums import (
    SpottingEventType,
    SpottingVehicleStatus,
)
from spotting.models import Event, EventSource, LocationEvent


class AddEventMutationLocationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="spotter-user-mutation-test")
        self.line = Line.objects.create(
            code="KJL", display_name="Kelana Jaya Line", display_color="#e0115f"
        )
        self.station1 = Station.objects.create(
            display_name="KLCC", location=Point(101.71, 3.15)
        )
        self.station_line1 = StationLine.objects.create(
            station=self.station1,
            line=self.line,
            display_name="KLCC KJ",
            internal_representation="KJ10",
        )
        self.v_type = VehicleType.objects.create(
            internal_name="KJL_INNOVIA", display_name="Innovia"
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 99", vehicle_type=self.v_type
        )
        EventSource.objects.get_or_create(
            name="SITE",
            defaults={"description": "Web app"},
        )

        self.mutation = """
            mutation AddEvent($input: EventInput!) {
                addEvent(input: $input) {
                    id
                    type
                    status
                    location {
                        accuracy
                        altitude
                        altitudeAccuracy
                        heading
                        speed
                    }
                }
            }
        """

    async def test_add_event_with_location_none(self):
        variables = {
            "input": {
                "spottingDate": "2024-05-10",
                "vehicle": str(self.vehicle.id),
                "type": SpottingEventType.JUST_SPOTTING,
                "status": SpottingVehicleStatus.IN_SERVICE,
                "location": None,
            }
        }

        result = await execute_graphql_async(
            self.mutation, variables=variables, user=self.user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)

        event_data = result.data["addEvent"]
        event_id = int(event_data["id"])
        self.assertIsNone(event_data["location"])

        self.assertTrue(await Event.objects.filter(id=event_id).aexists())
        self.assertFalse(
            await LocationEvent.objects.filter(event_id=event_id).aexists()
        )

    async def test_add_event_with_location_unset(self):
        variables = {
            "input": {
                "spottingDate": "2024-05-10",
                "vehicle": str(self.vehicle.id),
                "type": SpottingEventType.JUST_SPOTTING,
                "status": SpottingVehicleStatus.IN_SERVICE,
            }
        }

        result = await execute_graphql_async(
            self.mutation, variables=variables, user=self.user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)

        event_data = result.data["addEvent"]
        event_id = int(event_data["id"])
        self.assertIsNone(event_data["location"])

        self.assertTrue(await Event.objects.filter(id=event_id).aexists())
        self.assertFalse(
            await LocationEvent.objects.filter(event_id=event_id).aexists()
        )

    async def test_add_event_with_location_all_fields(self):
        variables = {
            "input": {
                "spottingDate": "2024-05-10",
                "vehicle": str(self.vehicle.id),
                "type": SpottingEventType.JUST_SPOTTING,
                "status": SpottingVehicleStatus.IN_SERVICE,
                "location": {
                    "latitude": 3.1592,
                    "longitude": 101.7118,
                    "altitude": 45.5,
                    "accuracy": 3.2,
                    "altitudeAccuracy": 1.5,
                    "speed": 15.0,
                    "heading": 90.0,
                },
            }
        }

        result = await execute_graphql_async(
            self.mutation, variables=variables, user=self.user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)

        event_data = result.data["addEvent"]
        event_id = int(event_data["id"])
        self.assertIsNotNone(event_data["location"])
        self.assertEqual(event_data["location"]["altitude"], 45.5)
        self.assertEqual(event_data["location"]["accuracy"], 3.2)
        self.assertEqual(event_data["location"]["altitudeAccuracy"], 1.5)
        self.assertEqual(event_data["location"]["speed"], 15.0)
        self.assertEqual(event_data["location"]["heading"], 90.0)

        self.assertTrue(await Event.objects.filter(id=event_id).aexists())
        self.assertTrue(await LocationEvent.objects.filter(event_id=event_id).aexists())
        created_location = await LocationEvent.objects.aget(event_id=event_id)
        self.assertEqual(created_location.location.coords, (101.7118, 3.1592))
        self.assertEqual(float(created_location.altitude), 45.5)
        self.assertEqual(float(created_location.accuracy), 3.2)
        self.assertEqual(float(created_location.altitude_accuracy), 1.5)
        self.assertEqual(float(created_location.speed), 15.0)
        self.assertEqual(float(created_location.heading), 90.0)

    async def test_add_event_with_location_partial_fields(self):
        variables = {
            "input": {
                "spottingDate": "2024-05-10",
                "vehicle": str(self.vehicle.id),
                "type": SpottingEventType.JUST_SPOTTING,
                "status": SpottingVehicleStatus.IN_SERVICE,
                "location": {
                    "latitude": 3.1592,
                    "longitude": 101.7118,
                },
            }
        }

        result = await execute_graphql_async(
            self.mutation, variables=variables, user=self.user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)

        event_data = result.data["addEvent"]
        event_id = int(event_data["id"])
        self.assertIsNotNone(event_data["location"])
        self.assertIsNone(event_data["location"]["altitude"])
        self.assertIsNone(event_data["location"]["accuracy"])
        self.assertIsNone(event_data["location"]["altitudeAccuracy"])
        self.assertIsNone(event_data["location"]["speed"])
        self.assertIsNone(event_data["location"]["heading"])

        self.assertTrue(await Event.objects.filter(id=event_id).aexists())
        self.assertTrue(await LocationEvent.objects.filter(event_id=event_id).aexists())
        created_location = await LocationEvent.objects.aget(event_id=event_id)
        self.assertEqual(created_location.location.coords, (101.7118, 3.1592))
        self.assertIsNone(created_location.altitude)
        self.assertIsNone(created_location.accuracy)
        self.assertIsNone(created_location.altitude_accuracy)
        self.assertIsNone(created_location.speed)
        self.assertIsNone(created_location.heading)
