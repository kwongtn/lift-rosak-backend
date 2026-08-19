from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from strawberry import UNSET
from strawberry.types.maybe import Some

from common.models import User
from generic.schema.inputs import WebLocationInput
from operation.enums import VehicleStatus
from operation.models import (
    Line,
    Station,
    StationLine,
    Vehicle,
    VehicleLine,
    VehicleType,
)
from rosak.tests import execute_graphql_async
from rosak.tests.test_schema import assert_maybe_field_behavior
from spotting.enums import (
    SpottingEventType,
    SpottingVehicleStatus,
    SpottingWheelStatus,
)
from spotting.models import Event, EventRead, EventSource, LocationEvent
from spotting.schema.inputs import EventInput


class SpottingModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="spotter-user-1")
        self.line = Line.objects.create(
            code="AGL", display_name="Ampang Line", display_color="#ff7700"
        )
        self.station1 = Station.objects.create(
            display_name="Plaza Rakyat", location=Point(101.69, 3.14)
        )
        self.station2 = Station.objects.create(
            display_name="Hang Tuah", location=Point(101.70, 3.14)
        )
        self.v_type = VehicleType.objects.create(
            internal_name="AMY_LIGHT_RAIL", display_name="AMY"
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 10", vehicle_type=self.v_type
        )

    def test_create_event_between_stations(self):
        event = Event.objects.create(
            reporter=self.user,
            vehicle=self.vehicle,
            type=SpottingEventType.BETWEEN_STATIONS,
            status=SpottingVehicleStatus.IN_SERVICE,
            origin_station=self.station1,
            destination_station=self.station2,
            spotting_date=timezone.now().date(),
        )
        self.assertEqual(event.origin_station, self.station1)
        self.assertEqual(event.destination_station, self.station2)

    def test_event_read_tracking(self):
        event = Event.objects.create(
            reporter=self.user,
            vehicle=self.vehicle,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=timezone.now().date(),
        )
        event_read = EventRead.objects.create(reader=self.user, event=event)
        self.assertEqual(event_read.reader, self.user)

        with self.assertRaises(IntegrityError):
            EventRead.objects.create(reader=self.user, event=event)  # duplicate read


class EventCheckConstraintTests(TestCase):
    """Exhaustive tests for the `spotting_event_value_relevant` CheckConstraint."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="constraint-user-1")
        self.line = Line.objects.create(
            code="KJL", display_name="Kelana Jaya Line", display_color="#e0115f"
        )
        self.station1 = Station.objects.create(
            display_name="KLCC", location=Point(101.71, 3.15)
        )
        self.station2 = Station.objects.create(
            display_name="Masjid Jamek", location=Point(101.69, 3.15)
        )
        self.v_type = VehicleType.objects.create(
            internal_name="KJL_INNOVIA", display_name="Innovia"
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 20", vehicle_type=self.v_type
        )

    def _kwargs(self, **overrides):
        kwargs = {
            "reporter": self.user,
            "vehicle": self.vehicle,
            "status": SpottingVehicleStatus.IN_SERVICE,
            "spotting_date": timezone.now().date(),
        }
        kwargs.update(overrides)
        return kwargs

    def _assert_invalid(self, **overrides):
        # IntegrityError breaks the surrounding transaction, so wrap each
        # invalid save in its own atomic block.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Event.objects.create(**self._kwargs(**overrides))

    def test_between_stations_with_distinct_stations_ok(self):
        event = Event.objects.create(
            **self._kwargs(
                type=SpottingEventType.BETWEEN_STATIONS,
                origin_station=self.station1,
                destination_station=self.station2,
            )
        )
        self.assertIsNotNone(event.id)

    def test_between_stations_missing_destination_raises(self):
        self._assert_invalid(
            type=SpottingEventType.BETWEEN_STATIONS,
            origin_station=self.station1,
            destination_station=None,
        )

    def test_between_stations_missing_origin_raises(self):
        self._assert_invalid(
            type=SpottingEventType.BETWEEN_STATIONS,
            origin_station=None,
            destination_station=self.station2,
        )

    def test_between_stations_same_origin_and_destination_raises(self):
        self._assert_invalid(
            type=SpottingEventType.BETWEEN_STATIONS,
            origin_station=self.station1,
            destination_station=self.station1,
        )

    def test_at_station_with_origin_only_ok(self):
        event = Event.objects.create(
            **self._kwargs(
                type=SpottingEventType.AT_STATION,
                origin_station=self.station1,
                destination_station=None,
            )
        )
        self.assertIsNotNone(event.id)

    def test_at_station_with_destination_set_raises(self):
        self._assert_invalid(
            type=SpottingEventType.AT_STATION,
            origin_station=self.station1,
            destination_station=self.station2,
        )

    def test_at_station_without_origin_raises(self):
        self._assert_invalid(
            type=SpottingEventType.AT_STATION,
            origin_station=None,
            destination_station=None,
        )

    def test_stationless_types_with_any_station_set_raise(self):
        stationless_types = [
            SpottingEventType.DEPOT,
            SpottingEventType.JUST_SPOTTING,
            SpottingEventType.LOCATION,
        ]
        for event_type in stationless_types:
            with self.subTest(event_type=event_type, station="origin"):
                self._assert_invalid(
                    type=event_type,
                    origin_station=self.station1,
                    destination_station=None,
                )
            with self.subTest(event_type=event_type, station="destination"):
                self._assert_invalid(
                    type=event_type,
                    origin_station=None,
                    destination_station=self.station2,
                )
            with self.subTest(event_type=event_type, station="both"):
                self._assert_invalid(
                    type=event_type,
                    origin_station=self.station1,
                    destination_station=self.station2,
                )

    def test_stationless_types_without_stations_ok(self):
        for event_type in [
            SpottingEventType.DEPOT,
            SpottingEventType.JUST_SPOTTING,
            SpottingEventType.LOCATION,
        ]:
            with self.subTest(event_type=event_type):
                event = Event.objects.create(
                    **self._kwargs(
                        type=event_type,
                        origin_station=None,
                        destination_station=None,
                    )
                )
                self.assertIsNotNone(event.id)

    def test_location_type_without_location_event_row_ok(self):
        # Pin the catalogued gap: the CheckConstraint never requires a
        # LocationEvent row (i.e. coordinates) for LOCATION-type events.
        # This pins current behavior — do NOT "fix" the model.
        event = Event.objects.create(**self._kwargs(type=SpottingEventType.LOCATION))
        self.assertIsNotNone(event.id)
        self.assertFalse(LocationEvent.objects.filter(event=event).exists())


class LocationEventTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="location-event-user-1")
        self.line = Line.objects.create(
            code="MRL", display_name="Monorail Line", display_color="#7dba00"
        )
        self.v_type = VehicleType.objects.create(
            internal_name="MRL_SCOMI", display_name="Scomi"
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 30", vehicle_type=self.v_type
        )
        self.event = Event.objects.create(
            reporter=self.user,
            vehicle=self.vehicle,
            type=SpottingEventType.LOCATION,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=timezone.now().date(),
        )

    def test_location_event_persists_with_fields(self):
        location_event = LocationEvent.objects.create(
            event=self.event,
            location=Point(101.6, 3.1),
            accuracy="5.500000",
            altitude="10.250000",
            altitude_accuracy="2.500000",
            heading="180.50000",
            speed="12.345",
        )
        self.assertIsNotNone(location_event.id)

        fetched = LocationEvent.objects.get(id=location_event.id)
        self.assertEqual(fetched.event_id, self.event.id)
        self.assertEqual(fetched.event, self.event)
        self.assertEqual(fetched.location.coords, (101.6, 3.1))
        self.assertEqual(str(fetched.accuracy), "5.500000")
        self.assertEqual(str(fetched.altitude), "10.250000")

    def test_location_event_event_fk_resolves(self):
        location_event = LocationEvent.objects.create(
            event=self.event,
            location=Point(101.6, 3.1),
        )
        self.assertEqual(Event.objects.get(locationevent=location_event), self.event)

    def test_location_event_location_not_nullable(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            LocationEvent.objects.create(event=self.event, location=None)


class AsyncOrmRegressionTests(TestCase):
    """Regression tests for the Django async ORM API surface (4.2 -> 5.x)."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="async-user-1")
        self.other_user = User.objects.create(firebase_id="async-user-2")
        self.line = Line.objects.create(
            code="SPL", display_name="Sri Petaling Line", display_color="#8c2e08"
        )
        self.v_type = VehicleType.objects.create(
            internal_name="SPL_CSR", display_name="CSR"
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 40", vehicle_type=self.v_type
        )

    def _kwargs(self, **overrides):
        kwargs = {
            "reporter": self.user,
            "vehicle": self.vehicle,
            "type": SpottingEventType.JUST_SPOTTING,
            "status": SpottingVehicleStatus.IN_SERVICE,
            "spotting_date": timezone.now().date(),
        }
        kwargs.update(overrides)
        return kwargs

    async def test_acreate_and_aget_round_trip(self):
        event = await Event.objects.acreate(**self._kwargs())
        fetched = await Event.objects.aget(id=event.id)
        self.assertEqual(fetched.id, event.id)
        self.assertEqual(fetched.reporter_id, self.user.id)
        self.assertEqual(fetched.vehicle_id, self.vehicle.id)

    async def test_async_iteration_over_filter_yields_created_rows(self):
        event1 = await Event.objects.acreate(**self._kwargs())
        event2 = await Event.objects.acreate(**self._kwargs())

        seen_ids = []
        async for event in Event.objects.filter(vehicle=self.vehicle).order_by("id"):
            seen_ids.append(event.id)

        self.assertEqual(seen_ids, sorted([event1.id, event2.id]))

    async def test_auser_deletion_by_reporter_within_3_days_deletes(self):
        event = await Event.objects.acreate(**self._kwargs())
        await event.auser_deletion(self.user.id)
        self.assertFalse(await Event.objects.filter(id=event.id).aexists())

    async def test_auser_deletion_by_wrong_user_raises(self):
        event = await Event.objects.acreate(**self._kwargs())
        with self.assertRaises(Exception):
            await event.auser_deletion(self.other_user.id)
        self.assertTrue(await Event.objects.filter(id=event.id).aexists())


class SpottingGraphQLTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            firebase_id="spotting-gql-user-1",
            nickname="SpotterOne",
        )
        self.other_user = User.objects.create(
            firebase_id="spotting-gql-user-2",
            nickname="SpotterTwo",
        )
        self.admin_user = User.objects.create(
            firebase_id="spotting-gql-admin-user",
            nickname="SpotterAdmin",
        )

        self.line = Line.objects.create(
            code="KJL",
            display_name="Kelana Jaya Line",
            display_color="#d32f2f",
        )
        self.station1 = Station.objects.create(
            display_name="KLCC",
            location=Point(101.7118, 3.1592),
        )
        self.station2 = Station.objects.create(
            display_name="Pasar Seni",
            location=Point(101.6958, 3.1425),
        )
        self.station3 = Station.objects.create(
            display_name="Subang Jaya",
            location=Point(101.5878, 3.0801),
        )

        self.station_line1 = StationLine.objects.create(
            station=self.station1,
            line=self.line,
            display_name="KLCC KJ",
            internal_representation="KJ10",
        )
        self.station_line2 = StationLine.objects.create(
            station=self.station2,
            line=self.line,
            display_name="Pasar Seni KJ",
            internal_representation="KJ14",
        )
        self.station_line3 = StationLine.objects.create(
            station=self.station3,
            line=self.line,
            display_name="Subang Jaya KJ",
            internal_representation="KJ28",
        )

        self.v_type = VehicleType.objects.create(
            internal_name="KJL_INNOVIA_300",
            display_name="Innovia Metro 300",
        )
        self.vehicle1 = Vehicle.objects.create(
            identification_no="Set 50",
            nickname="The Falcon",
            vehicle_type=self.v_type,
            status=VehicleStatus.IN_SERVICE,
        )
        self.vehicle2 = Vehicle.objects.create(
            identification_no="Set 51",
            nickname="The Eagle",
            vehicle_type=self.v_type,
            status=VehicleStatus.OUT_OF_SERVICE,
        )
        VehicleLine.objects.create(vehicle=self.vehicle1, line=self.line)
        VehicleLine.objects.create(vehicle=self.vehicle2, line=self.line)

        EventSource.objects.get_or_create(
            name="SITE",
            defaults={"description": "Web app"},
        )

    async def test_add_spotting_event_mutation_between_stations_with_location(self):
        mutation = """
            mutation AddEventBetweenStations($input: EventInput!) {
                addEvent(input: $input) {
                    id
                    spottingDate
                    type
                    status
                    wheelStatus
                    notes
                    runNumber
                    originStation {
                        id
                        displayName
                    }
                    destinationStation {
                        id
                        displayName
                    }
                    location {
                        id
                        altitude
                        accuracy
                        speed
                        heading
                    }
                }
            }
        """
        variables = {
            "input": {
                "spottingDate": "2024-05-10",
                "vehicle": str(self.vehicle1.id),
                "type": SpottingEventType.BETWEEN_STATIONS,
                "status": SpottingVehicleStatus.IN_SERVICE,
                "wheelStatus": SpottingWheelStatus.FRESH,
                "notes": "Smooth ride between stations",
                "runNumber": "RN-42",
                "originStation": str(self.station_line1.id),
                "destinationStation": str(self.station_line2.id),
                "location": {
                    "latitude": 3.1592,
                    "longitude": 101.7118,
                    "altitude": 45.5,
                    "accuracy": 3.2,
                    "speed": 15.0,
                    "heading": 90.0,
                },
            }
        }

        unauth_result = await execute_graphql_async(
            mutation, variables=variables, user=None
        )
        self.assertIsNotNone(unauth_result.errors)
        self.assertIsNone(unauth_result.data)

        result = await execute_graphql_async(
            mutation, variables=variables, user=self.user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)

        event_data = result.data["addEvent"]
        self.assertEqual(event_data["spottingDate"], "2024-05-10")
        self.assertEqual(event_data["type"], SpottingEventType.BETWEEN_STATIONS)
        self.assertEqual(event_data["status"], SpottingVehicleStatus.IN_SERVICE)
        self.assertEqual(event_data["wheelStatus"], SpottingWheelStatus.FRESH)
        self.assertEqual(event_data["notes"], "Smooth ride between stations")
        self.assertEqual(event_data["runNumber"], "RN-42")
        self.assertEqual(
            event_data["originStation"]["displayName"], self.station1.display_name
        )
        self.assertEqual(
            event_data["destinationStation"]["displayName"], self.station2.display_name
        )
        self.assertEqual(event_data["location"]["altitude"], 45.5)
        self.assertEqual(event_data["location"]["accuracy"], 3.2)

        event_id = int(event_data["id"])
        self.assertTrue(await Event.objects.filter(id=event_id).aexists())
        created_event = await Event.objects.aget(id=event_id)
        self.assertEqual(created_event.reporter_id, self.user.id)
        self.assertEqual(created_event.origin_station_id, self.station1.id)
        self.assertEqual(created_event.destination_station_id, self.station2.id)

        self.assertTrue(await LocationEvent.objects.filter(event_id=event_id).aexists())
        created_location = await LocationEvent.objects.aget(event_id=event_id)
        self.assertEqual(created_location.location.coords, (101.7118, 3.1592))
        self.assertEqual(float(created_location.altitude), 45.5)

    async def test_add_spotting_event_mutation_at_station(self):
        mutation = """
            mutation AddEventAtStation($input: EventInput!) {
                addEvent(input: $input) {
                    id
                    type
                    originStation {
                        id
                        displayName
                    }
                    destinationStation {
                        id
                    }
                }
            }
        """
        variables = {
            "input": {
                "spottingDate": "2024-05-11",
                "vehicle": str(self.vehicle1.id),
                "type": SpottingEventType.AT_STATION,
                "status": SpottingVehicleStatus.IN_SERVICE,
                "originStation": str(self.station_line1.id),
            }
        }

        result = await execute_graphql_async(
            mutation, variables=variables, user=self.user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)

        event_data = result.data["addEvent"]
        self.assertEqual(event_data["type"], SpottingEventType.AT_STATION)
        self.assertEqual(
            event_data["originStation"]["displayName"], self.station1.display_name
        )
        self.assertIsNone(event_data["destinationStation"])

        event_id = int(event_data["id"])
        created_event = await Event.objects.aget(id=event_id)
        self.assertEqual(created_event.origin_station_id, self.station1.id)
        self.assertIsNone(created_event.destination_station_id)

    async def test_vehicle_events_query_pagination_and_is_mine(self):
        e1 = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date(2024, 5, 1),
            notes="User 1 Event 1",
        )
        e2 = await Event.objects.acreate(
            reporter=self.other_user,
            vehicle=self.vehicle1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date(2024, 5, 2),
            notes="User 2 Event 1",
        )
        e3 = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date(2024, 5, 3),
            notes="User 1 Event 2",
        )
        await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle2,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.NOT_IN_SERVICE,
            spotting_date=date(2024, 5, 4),
            notes="Vehicle 2 Event",
        )

        query = """
            query GetVehicleEvents($vehicleId: ID!, $limit: Int, $offset: Int) {
                events(
                    filters: { vehicle: { id: $vehicleId } }
                    pagination: { limit: $limit, offset: $offset }
                    order: { id: ASC }
                ) {
                    id
                    notes
                    isMine
                    reporter {
                        nickname
                    }
                }
                eventsCount
            }
        """

        variables_p1 = {
            "vehicleId": str(self.vehicle1.id),
            "limit": 2,
            "offset": 0,
        }
        res_p1 = await execute_graphql_async(
            query, variables=variables_p1, user=self.user
        )
        self.assertIsNone(res_p1.errors)
        self.assertIsNotNone(res_p1.data)
        self.assertEqual(res_p1.data["eventsCount"], 4)

        events_p1 = res_p1.data["events"]
        self.assertEqual(len(events_p1), 2)
        self.assertEqual(events_p1[0]["id"], str(e1.id))
        self.assertTrue(events_p1[0]["isMine"])
        self.assertEqual(events_p1[0]["reporter"]["nickname"], "SpotterOne")

        self.assertEqual(events_p1[1]["id"], str(e2.id))
        self.assertFalse(events_p1[1]["isMine"])
        self.assertEqual(events_p1[1]["reporter"]["nickname"], "SpotterTwo")

        variables_p2 = {
            "vehicleId": str(self.vehicle1.id),
            "limit": 2,
            "offset": 2,
        }
        res_p2 = await execute_graphql_async(
            query, variables=variables_p2, user=self.user
        )
        self.assertIsNone(res_p2.errors)
        events_p2 = res_p2.data["events"]
        self.assertEqual(len(events_p2), 1)
        self.assertEqual(events_p2[0]["id"], str(e3.id))
        self.assertTrue(events_p2[0]["isMine"])

        res_unauth = await execute_graphql_async(
            query, variables=variables_p1, user=None
        )
        self.assertIsNone(res_unauth.errors)
        for ev in res_unauth.data["events"]:
            self.assertFalse(ev["isMine"])

    async def test_event_filter_different_status_than_vehicle(self):
        e_same = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date(2024, 5, 1),
            notes="Same status event",
        )
        e_diff = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.TESTING,
            spotting_date=date(2024, 5, 2),
            notes="Different status event",
        )

        query = """
            query GetEventsWithDifferentStatus($diffStatus: Boolean) {
                events(filters: { differentStatusThanVehicle: $diffStatus }) {
                    id
                    status
                    vehicle {
                        id
                        status
                    }
                }
            }
        """
        result_true = await execute_graphql_async(
            query, variables={"diffStatus": True}, user=self.user
        )
        self.assertIsNone(result_true.errors)
        ids_true = [ev["id"] for ev in result_true.data["events"]]
        self.assertIn(str(e_diff.id), ids_true)
        self.assertNotIn(str(e_same.id), ids_true)

        result_false = await execute_graphql_async(
            query, variables={"diffStatus": False}, user=self.user
        )
        self.assertIsNone(result_false.errors)
        ids_false = [ev["id"] for ev in result_false.data["events"]]
        self.assertIn(str(e_same.id), ids_false)
        self.assertNotIn(str(e_diff.id), ids_false)

    async def test_event_filter_free_search(self):
        e_notes = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date(2024, 5, 1),
            notes="Spotted unique_zebra near track",
        )
        e_station = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle1,
            type=SpottingEventType.AT_STATION,
            status=SpottingVehicleStatus.IN_SERVICE,
            origin_station=self.station3,
            spotting_date=date(2024, 5, 2),
            notes="Standard stop",
        )
        e_vehicle_nick = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle2,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.NOT_IN_SERVICE,
            spotting_date=date(2024, 5, 3),
            notes="Maintenance yard",
        )

        query = """
            query FreeSearchEvents($keyword: String!) {
                events(filters: { freeSearch: $keyword }) {
                    id
                    notes
                }
            }
        """

        res1 = await execute_graphql_async(
            query, variables={"keyword": "unique_zebra"}, user=self.user
        )
        self.assertIsNone(res1.errors)
        ids1 = [ev["id"] for ev in res1.data["events"]]
        self.assertEqual(ids1, [str(e_notes.id)])

        res2 = await execute_graphql_async(
            query, variables={"keyword": "Subang Jaya"}, user=self.user
        )
        self.assertIsNone(res2.errors)
        ids2 = [ev["id"] for ev in res2.data["events"]]
        self.assertIn(str(e_station.id), ids2)
        self.assertNotIn(str(e_notes.id), ids2)

        res3 = await execute_graphql_async(
            query, variables={"keyword": "Set 51"}, user=self.user
        )
        self.assertIsNone(res3.errors)
        ids3 = [ev["id"] for ev in res3.data["events"]]
        self.assertIn(str(e_vehicle_nick.id), ids3)
        self.assertNotIn(str(e_notes.id), ids3)

        res4 = await execute_graphql_async(
            query, variables={"keyword": "The Eagle"}, user=self.user
        )
        self.assertIsNone(res4.errors)
        ids4 = [ev["id"] for ev in res4.data["events"]]
        self.assertIn(str(e_vehicle_nick.id), ids4)

    async def test_mark_as_read_mutation_admin_bulk_create(self):
        e1 = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date(2024, 5, 1),
        )
        e2 = await Event.objects.acreate(
            reporter=self.user,
            vehicle=self.vehicle1,
            type=SpottingEventType.JUST_SPOTTING,
            status=SpottingVehicleStatus.IN_SERVICE,
            spotting_date=date(2024, 5, 2),
        )
        await EventRead.objects.acreate(reader=self.admin_user, event=e1)

        mutation = """
            mutation MarkEventsRead($input: MarkEventAsReadInput!) {
                markAsRead(input: $input) {
                    ok
                }
            }
        """
        variables = {
            "input": {
                "eventIds": [str(e1.id), str(e2.id)],
            }
        }

        mock_firebase_admin_user = MagicMock()
        mock_firebase_admin_user.custom_claims = {"admin": True}

        mock_firebase_non_admin_user = MagicMock()
        mock_firebase_non_admin_user.custom_claims = {"admin": False}

        with (
            patch(
                "rosak.permissions.IsRecaptchaChallengePassed.has_permission",
                return_value=True,
            ),
            patch(
                "firebase_admin.auth.get_user",
                return_value=mock_firebase_non_admin_user,
            ),
        ):
            res_forbidden = await execute_graphql_async(
                mutation, variables=variables, user=self.user
            )
            self.assertIsNotNone(res_forbidden.errors)

        with (
            patch(
                "rosak.permissions.IsRecaptchaChallengePassed.has_permission",
                return_value=True,
            ),
            patch(
                "firebase_admin.auth.get_user", return_value=mock_firebase_admin_user
            ),
        ):
            res = await execute_graphql_async(
                mutation, variables=variables, user=self.admin_user
            )
            self.assertIsNone(res.errors)
            self.assertTrue(res.data["markAsRead"]["ok"])

        self.assertTrue(
            await EventRead.objects.filter(reader=self.admin_user).acount(), 2
        )


class TestEventInput(TestCase):
    def test_event_input_partial_update_omits_optional_fields(self):
        base_variables = {
            "spottingDate": "2024-05-10",
            "vehicle": "1",
        }
        for field in [
            "notes",
            "run_number",
            "wheel_status",
            "origin_station",
            "destination_station",
            "location",
            "is_anonymous",
        ]:
            assert_maybe_field_behavior(
                input_class=EventInput,
                field_name=field,
                test_cases=[
                    (base_variables, UNSET),
                ],
            )

    def test_event_input_explicit_null_clears_notes(self):
        variables = {
            "spottingDate": "2024-05-10",
            "vehicle": "1",
            "notes": None,
        }
        assert_maybe_field_behavior(
            input_class=EventInput,
            field_name="notes",
            test_cases=[
                (variables, Some(None)),
            ],
        )

    def test_event_input_nested_location_with_partial_coords(self):
        variables = {
            "spottingDate": "2024-05-10",
            "vehicle": "1",
            "location": {
                "latitude": 3.14,
                "longitude": 101.69,
            },
        }
        assert_maybe_field_behavior(
            input_class=EventInput,
            field_name="location",
            test_cases=[
                (
                    variables,
                    Some(
                        WebLocationInput(
                            latitude=Some(3.14),
                            longitude=Some(101.69),
                            accuracy=UNSET,
                            altitude_accuracy=UNSET,
                            heading=UNSET,
                            speed=UNSET,
                            altitude=UNSET,
                        )
                    ),
                ),
            ],
        )


class TestAddEventMutation(TestCase):
    """Maybe[T] migration tests for the add_event mutation.

    Maybe semantics: omitted -> UNSET, explicit null -> Some(None),
    provided value -> Some(value). The mutation must unwrap Some via
    `.value` and must not pass Some/UNSET objects to the ORM.
    """

    def setUp(self):
        self.user = User.objects.create(
            firebase_id="add-event-user-1",
            nickname="AddEventSpotter",
        )
        self.line = Line.objects.create(
            code="PJL",
            display_name="Putrajaya Line",
            display_color="#f0ad4e",
        )
        self.station1 = Station.objects.create(
            display_name="Tun Razak Exchange",
            location=Point(101.7100, 3.1420),
        )
        self.station2 = Station.objects.create(
            display_name="Chan Sow Lin",
            location=Point(101.7166, 3.1276),
        )
        self.station_line1 = StationLine.objects.create(
            station=self.station1,
            line=self.line,
            display_name="TRX PY",
            internal_representation="PY20",
        )
        self.station_line2 = StationLine.objects.create(
            station=self.station2,
            line=self.line,
            display_name="Chan Sow Lin PY",
            internal_representation="PY24",
        )
        self.v_type = VehicleType.objects.create(
            internal_name="PYL_HYUNDAI",
            display_name="Hyundai Rotem",
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 60",
            vehicle_type=self.v_type,
            status=VehicleStatus.IN_SERVICE,
        )
        EventSource.objects.get_or_create(
            name="SITE",
            defaults={"description": "Web app"},
        )

        self.mutation = """
            mutation AddEvent($input: EventInput!) {
                addEvent(input: $input) {
                    id
                    spottingDate
                    type
                    status
                    notes
                    runNumber
                    wheelStatus
                    originStation {
                        id
                        displayName
                    }
                    destinationStation {
                        id
                        displayName
                    }
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

    async def test_add_event_minimal_required_fields_only(self):
        variables = {
            "input": {
                "spottingDate": "2024-06-01",
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
        self.assertEqual(event_data["notes"], "")
        self.assertIsNone(event_data["runNumber"])
        self.assertIsNone(event_data["wheelStatus"])
        self.assertIsNone(event_data["originStation"])
        self.assertIsNone(event_data["destinationStation"])
        self.assertIsNone(event_data["location"])

        event = await Event.objects.aget(id=int(event_data["id"]))
        self.assertEqual(event.notes, "")
        self.assertFalse(event.is_anonymous)
        self.assertIsNone(event.wheel_status)
        self.assertIsNone(event.run_number)
        self.assertIsNone(event.origin_station_id)
        self.assertIsNone(event.destination_station_id)
        self.assertFalse(await LocationEvent.objects.filter(event=event).aexists())

    async def test_add_event_with_partial_location_coordinates(self):
        variables = {
            "input": {
                "spottingDate": "2024-06-02",
                "vehicle": str(self.vehicle.id),
                "type": SpottingEventType.LOCATION,
                "status": SpottingVehicleStatus.IN_SERVICE,
                "location": {
                    "latitude": 3.1420,
                    "longitude": 101.7100,
                },
            }
        }

        result = await execute_graphql_async(
            self.mutation, variables=variables, user=self.user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)

        event_data = result.data["addEvent"]
        self.assertIsNotNone(event_data["location"])
        self.assertIsNone(event_data["location"]["accuracy"])
        self.assertIsNone(event_data["location"]["altitude"])
        self.assertIsNone(event_data["location"]["altitudeAccuracy"])
        self.assertIsNone(event_data["location"]["heading"])
        self.assertIsNone(event_data["location"]["speed"])

        location_event = await LocationEvent.objects.aget(
            event_id=int(event_data["id"])
        )
        self.assertEqual(location_event.location.coords, (101.7100, 3.1420))
        self.assertIsNone(location_event.accuracy)
        self.assertIsNone(location_event.altitude)
        self.assertIsNone(location_event.altitude_accuracy)
        self.assertIsNone(location_event.heading)
        self.assertIsNone(location_event.speed)

    async def test_add_event_omitted_notes_defaults_to_empty(self):
        variables = {
            "input": {
                "spottingDate": "2024-06-03",
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
        self.assertEqual(event_data["notes"], "")

        event = await Event.objects.aget(id=int(event_data["id"]))
        self.assertEqual(event.notes, "")

    async def test_add_event_explicit_null_location_skips_gps(self):
        variables = {
            "input": {
                "spottingDate": "2024-06-04",
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
        self.assertIsNone(event_data["location"])
        self.assertFalse(
            await LocationEvent.objects.filter(event_id=int(event_data["id"])).aexists()
        )

    async def test_add_event_with_all_optional_fields(self):
        variables = {
            "input": {
                "spottingDate": "2024-06-05",
                "vehicle": str(self.vehicle.id),
                "type": SpottingEventType.BETWEEN_STATIONS,
                "status": SpottingVehicleStatus.IN_SERVICE,
                "notes": "Full optional coverage",
                "runNumber": "RN-99",
                "wheelStatus": SpottingWheelStatus.WORN_OUT,
                "isAnonymous": True,
                "originStation": str(self.station_line1.id),
                "destinationStation": str(self.station_line2.id),
                "location": {
                    "latitude": 3.1420,
                    "longitude": 101.7100,
                    "accuracy": 4.5,
                    "altitude": 33.2,
                    "altitudeAccuracy": 1.5,
                    "heading": 270.0,
                    "speed": 22.5,
                },
            }
        }

        result = await execute_graphql_async(
            self.mutation, variables=variables, user=self.user
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)

        event_data = result.data["addEvent"]
        self.assertEqual(event_data["notes"], "Full optional coverage")
        self.assertEqual(event_data["runNumber"], "RN-99")
        self.assertEqual(event_data["wheelStatus"], SpottingWheelStatus.WORN_OUT)
        self.assertEqual(event_data["originStation"]["id"], str(self.station1.id))
        self.assertEqual(event_data["destinationStation"]["id"], str(self.station2.id))
        self.assertEqual(event_data["location"]["accuracy"], 4.5)
        self.assertEqual(event_data["location"]["altitude"], 33.2)
        self.assertEqual(event_data["location"]["altitudeAccuracy"], 1.5)
        self.assertEqual(event_data["location"]["heading"], 270.0)
        self.assertEqual(event_data["location"]["speed"], 22.5)

        event = await Event.objects.aget(id=int(event_data["id"]))
        self.assertTrue(event.is_anonymous)
        self.assertEqual(event.origin_station_id, self.station1.id)
        self.assertEqual(event.destination_station_id, self.station2.id)

        location_event = await LocationEvent.objects.aget(event_id=event.id)
        self.assertEqual(location_event.location.coords, (101.7100, 3.1420))
        self.assertEqual(float(location_event.accuracy), 4.5)
        self.assertEqual(float(location_event.altitude), 33.2)
        self.assertEqual(float(location_event.altitude_accuracy), 1.5)
        self.assertEqual(float(location_event.heading), 270.0)
        self.assertEqual(float(location_event.speed), 22.5)


class TestFilterDecorators(TestCase):
    """Test that filter decorators are correctly applied."""

    def test_event_filter(self):
        """Verify EventFilter has correct strawberry_django decorator."""
        from spotting.schema.filters import EventFilter

        self.assertTrue(
            hasattr(EventFilter, "__strawberry_django_definition__"),
            "EventFilter missing strawberry_django decorator",
        )

    def test_event_type_filter(self):
        """Verify EventFilter type field exists (smoke test)."""
        from spotting.schema.filters import EventFilter

        filter_instance = EventFilter()
        self.assertTrue(
            hasattr(filter_instance, "type"),
            "EventFilter missing type field",
        )
