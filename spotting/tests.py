from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from common.models import User
from operation.models import Line, Station, Vehicle, VehicleType
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event, EventRead, LocationEvent


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
