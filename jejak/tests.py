import inspect
from datetime import datetime, timezone

from django.contrib.gis.geos import Point
from django.contrib.postgres.indexes import GistIndex
from django.db import connection, models
from django.test import TestCase, override_settings
from psycopg2.extras import DateTimeTZRange
from strawberry import Some
from strawberry_django.ordering import Ordering
from strawberry_django.pagination import OffsetPaginationInput

from jejak.models import (
    Accessibility,
    AccessibilityBusRange,
    Bus,
    BusProviderRange,
    BusRouteRange,
    BusStopBusRange,
    BusType,
    CaptainBusRange,
    EngineStatusBusRange,
    Location,
    TripRevBusRange,
)
from jejak.schema.filters import LocationFilter
from jejak.schema.orderings import BusOrder
from jejak.schema.schema import JejakScalars
from rosak.tests import execute_graphql_async


@override_settings(DATABASE_ROUTERS=[])
class JejakIndexAndQueryPlanTests(TestCase):
    def test_model_meta_indexes_defined(self):
        range_models = [
            (AccessibilityBusRange, "idx_accessbusrange_bus_range"),
            (EngineStatusBusRange, "idx_engstatbusrange_bus_range"),
            (TripRevBusRange, "idx_triprevbusrange_bus_range"),
            (BusRouteRange, "idx_busrouterange_bus_range"),
            (BusStopBusRange, "idx_busstopbusrange_bus_range"),
            (CaptainBusRange, "idx_captainbusrange_bus_range"),
            (BusProviderRange, "idx_busproviderrange_bus_range"),
        ]

        for model_cls, index_name in range_models:
            with self.subTest(model=model_cls.__name__):
                index_names = [idx.name for idx in model_cls._meta.indexes]
                self.assertIn(index_name, index_names)
                target_idx = next(
                    idx for idx in model_cls._meta.indexes if idx.name == index_name
                )
                self.assertIsInstance(target_idx, GistIndex)
                self.assertEqual(target_idx.fields, ["bus", "dt_range"])

        location_index_names = [idx.name for idx in Location._meta.indexes]
        self.assertIn("idx_location_bus_dtgps", location_index_names)
        self.assertIn("idx_location_bus_dtreceived", location_index_names)

        dtgps_idx = next(
            idx
            for idx in Location._meta.indexes
            if idx.name == "idx_location_bus_dtgps"
        )
        self.assertIsInstance(dtgps_idx, models.Index)
        self.assertEqual(dtgps_idx.fields, ["bus", "-dt_gps"])

        dtreceived_idx = next(
            idx
            for idx in Location._meta.indexes
            if idx.name == "idx_location_bus_dtreceived"
        )
        self.assertIsInstance(dtreceived_idx, models.Index)
        self.assertEqual(dtreceived_idx.fields, ["bus", "-dt_received"])

    def test_explain_query_plan_range_models(self):
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

        with connection.schema_editor() as editor:
            editor.create_model(BusType)
            editor.create_model(Bus)
            editor.create_model(Accessibility)
            editor.create_model(AccessibilityBusRange)

        try:
            bus = Bus.objects.create(identifier="BUS-EXPLAIN-001")
            acc = Accessibility.objects.create(identifier="ACC-001")

            now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            for i in range(100):
                AccessibilityBusRange.objects.create(
                    bus=bus,
                    accessibility=acc,
                    dt_range=DateTimeTZRange(
                        datetime(2024, 1, 1, i % 24, i % 60, 0, tzinfo=timezone.utc),
                        datetime(2024, 1, 2, i % 24, i % 60, 0, tzinfo=timezone.utc),
                    ),
                )

            with connection.cursor() as cursor:
                cursor.execute("SET enable_seqscan = OFF;")
                qs = AccessibilityBusRange.objects.filter(
                    bus=bus,
                    dt_range__contains=now,
                )
                plan = qs.explain()
                self.assertIn("idx_accessbusrange_bus_range", plan)
                cursor.execute("SET enable_seqscan = ON;")
        finally:
            try:
                with connection.schema_editor() as editor:
                    editor.delete_model(AccessibilityBusRange)
                    editor.delete_model(Accessibility)
                    editor.delete_model(Bus)
                    editor.delete_model(BusType)
            except Exception:
                pass

    def test_explain_query_plan_location(self):
        with connection.schema_editor() as editor:
            editor.create_model(BusType)
            editor.create_model(Bus)
            editor.create_model(Location)

        try:
            bus = Bus.objects.create(identifier="BUS-EXPLAIN-LOC-001")

            for i in range(100):
                Location.objects.create(
                    bus=bus,
                    dt_received=datetime(
                        2024, 1, 1, (i // 60) % 24, i % 60, i % 60, tzinfo=timezone.utc
                    ),
                    dt_gps=datetime(
                        2024, 1, 1, (i // 60) % 24, i % 60, i % 60, tzinfo=timezone.utc
                    ),
                    location=Point(101.69, 3.14),
                    speed=30,
                )

            with connection.cursor() as cursor:
                cursor.execute("SET enable_seqscan = OFF;")

                qs_gps = Location.objects.filter(
                    bus=bus,
                    dt_gps__lte=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                ).order_by("-dt_gps")
                plan_gps = qs_gps.explain()
                self.assertIn("idx_location_bus_dtgps", plan_gps)

                qs_rec = Location.objects.filter(
                    bus=bus,
                    dt_received__lte=datetime(
                        2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc
                    ),
                ).order_by("-dt_received")
                plan_rec = qs_rec.explain()
                self.assertIn("idx_location_bus_dtreceived", plan_rec)

                cursor.execute("SET enable_seqscan = ON;")
        finally:
            try:
                with connection.schema_editor() as editor:
                    editor.delete_model(Location)
                    editor.delete_model(Bus)
                    editor.delete_model(BusType)
            except Exception:
                pass


@override_settings(DATABASE_ROUTERS=[])
class JejakLocationsCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with connection.schema_editor() as editor:
            editor.create_model(BusType)
            editor.create_model(Bus)
            editor.create_model(Location)

        cls.bus1 = Bus.objects.create(identifier="BUS-001")
        cls.bus2 = Bus.objects.create(identifier="BUS-002")

        cls.loc1 = Location.objects.create(
            bus=cls.bus1,
            dt_received=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            dt_gps=datetime(2024, 1, 1, 9, 59, 0, tzinfo=timezone.utc),
            location=Point(101.69, 3.14),
            speed=30,
        )
        cls.loc2 = Location.objects.create(
            bus=cls.bus1,
            dt_received=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            dt_gps=datetime(2024, 1, 1, 11, 59, 0, tzinfo=timezone.utc),
            location=Point(101.70, 3.15),
            speed=40,
        )
        cls.loc3 = Location.objects.create(
            bus=cls.bus2,
            dt_received=datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
            dt_gps=datetime(2024, 1, 1, 13, 59, 0, tzinfo=timezone.utc),
            location=Point(101.71, 3.16),
            speed=50,
        )

    @classmethod
    def tearDownClass(cls):
        try:
            with connection.schema_editor() as editor:
                editor.delete_model(Location)
                editor.delete_model(Bus)
        except Exception:
            pass
        super().tearDownClass()

    def setUp(self):
        self.scalar = JejakScalars()

    async def test_locations_count_filters_none_returns_zero(self):
        count = await self.scalar.locations_count(filters=None)
        self.assertEqual(count, 0)

    async def test_locations_count_empty_filter_returns_zero(self):
        count = await self.scalar.locations_count(filters=Some(LocationFilter()))
        self.assertEqual(count, 0)

    async def test_locations_count_with_bus_id_only(self):
        f = LocationFilter(bus_id=Some(str(self.bus1.id)))
        count = await self.scalar.locations_count(filters=Some(f))
        self.assertEqual(count, 2)

        f2 = LocationFilter(bus_id=Some(str(self.bus2.id)))
        count2 = await self.scalar.locations_count(filters=Some(f2))
        self.assertEqual(count2, 1)

    async def test_locations_count_with_bus_id_and_dt_gps_range(self):
        f = LocationFilter(
            bus_id=Some(str(self.bus1.id)),
            dt_gps_range=Some(
                [
                    datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
                ]
            ),
        )
        count = await self.scalar.locations_count(filters=Some(f))
        self.assertEqual(count, 1)

    async def test_locations_count_with_bus_id_and_dt_received_range(self):
        f = LocationFilter(
            bus_id=Some(str(self.bus1.id)),
            dt_received_range=Some(
                [
                    datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
                ]
            ),
        )
        count = await self.scalar.locations_count(filters=Some(f))
        self.assertEqual(count, 1)

    async def test_locations_count_with_all_fields(self):
        f = LocationFilter(
            bus_id=Some(str(self.bus1.id)),
            dt_received_range=Some(
                [
                    datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
                ]
            ),
            dt_gps_range=Some(
                [
                    datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
                ]
            ),
        )
        count = await self.scalar.locations_count(filters=Some(f))
        self.assertEqual(count, 1)

    async def test_locations_count_graphql_query_without_filters(self):
        query = """
            query {
                locationsCount
            }
        """
        result = await execute_graphql_async(query)
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["locationsCount"], 0)

    async def test_locations_count_graphql_query_with_filters(self):
        query = """
            query GetLocationsCount($filters: LocationFilter) {
                locationsCount(filters: $filters)
            }
        """
        variables = {
            "filters": {
                "id": "1",
                "busId": str(self.bus1.id),
                "dtReceivedRange": [
                    "2024-01-01T09:00:00Z",
                    "2024-01-01T13:00:00Z",
                ],
                "dtGpsRange": [
                    "2024-01-01T09:00:00Z",
                    "2024-01-01T13:00:00Z",
                ],
            }
        }
        result = await execute_graphql_async(query, variables=variables)
        self.assertIsNone(result.errors)
        self.assertEqual(result.data["locationsCount"], 2)


@override_settings(DATABASE_ROUTERS=[])
class TestLocationResolvers(TestCase):
    @classmethod
    def setUpTestData(cls):
        with connection.schema_editor() as editor:
            editor.create_model(BusType)
            editor.create_model(Bus)
            editor.create_model(Location)

        cls.bus1 = Bus.objects.create(identifier="BUS-101")
        cls.bus2 = Bus.objects.create(identifier="BUS-102")

        cls.loc1 = Location.objects.create(
            bus=cls.bus1,
            dt_received=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            dt_gps=datetime(2024, 1, 1, 9, 59, 0, tzinfo=timezone.utc),
            location=Point(101.69, 3.14),
            speed=30,
        )
        cls.loc2 = Location.objects.create(
            bus=cls.bus1,
            dt_received=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            dt_gps=datetime(2024, 1, 1, 11, 59, 0, tzinfo=timezone.utc),
            location=Point(101.70, 3.15),
            speed=40,
        )
        cls.loc3 = Location.objects.create(
            bus=cls.bus2,
            dt_received=datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
            dt_gps=datetime(2024, 1, 1, 13, 59, 0, tzinfo=timezone.utc),
            location=Point(101.71, 3.16),
            speed=50,
        )

    @classmethod
    def tearDownClass(cls):
        try:
            with connection.schema_editor() as editor:
                editor.delete_model(Location)
                editor.delete_model(Bus)
        except Exception:
            pass
        super().tearDownClass()

    def setUp(self):
        self.scalar = JejakScalars()

    async def test_locations_query_omitted_filters_returns_all(self):
        # Maybe semantics: omitted arguments must default to None, not UNSET
        sig = inspect.signature(self.scalar.locations)
        self.assertIsNone(sig.parameters["filters"].default)
        self.assertIsNone(sig.parameters["order"].default)
        self.assertIsNone(sig.parameters["pagination"].default)

        results = await self.scalar.locations(info=None)
        self.assertEqual(len(results), 3)

    async def test_locations_query_with_bus_id_filter(self):
        filters = LocationFilter(bus_id=Some(str(self.bus1.id)))
        results = await self.scalar.locations(info=None, filters=Some(filters))
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.bus_id == self.bus1.id for r in results))

    async def test_locations_count_with_date_range_filters(self):
        filters = LocationFilter(
            dt_received_range=Some(
                [
                    datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                ]
            ),
            dt_gps_range=Some(
                [
                    datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
                ]
            ),
        )
        count = await self.scalar.locations_count(filters=Some(filters))
        self.assertEqual(count, 1)

    async def test_buses_query_with_order_and_pagination(self):
        order = BusOrder(identifier=Ordering.DESC)
        pagination = OffsetPaginationInput(offset=0, limit=1)
        results = await self.scalar.buses(
            info=None,
            order=Some(order),
            pagination=Some(pagination),
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].identifier, "BUS-102")
