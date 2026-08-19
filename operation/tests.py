import copy
import json
from datetime import date

from asgiref.sync import async_to_sync
from django.contrib.gis.geos import Point
from django.db import IntegrityError
from django.test import TestCase, modify_settings
from django.urls import reverse
from dotmap import DotMap

from chartography.enums import DataSources
from chartography.models import LineVehicleStatusCountHistory, Snapshot, Source
from common.models import User
from operation.enums import AssetStatus, AssetType, VehicleStatus, WheelStatus
from operation.models import (
    Asset,
    Line,
    Station,
    StationLine,
    Vehicle,
    VehicleLine,
    VehicleType,
)
from rosak.context import ContextLoaders
from rosak.schema import schema
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event


def execute_graphql(query: str, variables: dict | None = None, user=None):
    context = DotMap(
        {
            "loaders": copy.deepcopy(ContextLoaders),
            "request": None,
            "response": None,
            "user": user,
        }
    )
    return async_to_sync(schema.execute)(
        query,
        variable_values=variables,
        context_value=context,
    )


class OperationModelTests(TestCase):
    def setUp(self):
        self.line = Line.objects.create(
            display_name="Kelana Jaya Line",
            code="KJL",
            display_color="#ff0000",
        )
        self.station = Station.objects.create(
            display_name="KL Sentral",
            location=Point(101.6869, 3.1341),
        )
        self.station_line = StationLine.objects.create(
            station=self.station,
            line=self.line,
            display_name="KL Sentral",
            internal_representation="KJ15",
        )
        self.vehicle_type = VehicleType.objects.create(
            display_name="Innovia Metro 300",
            internal_name="INNOVIA_300",
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 40",
            vehicle_type=self.vehicle_type,
            status=VehicleStatus.IN_SERVICE,
        )

    def test_line_and_station_creation(self):
        self.assertEqual(self.line.code, "KJL")
        self.assertEqual(self.station.display_name, "KL Sentral")
        self.assertEqual(self.station_line.internal_representation, "KJ15")

    def test_station_line_relationship(self):
        self.assertIn(self.station, self.line.stations.all())
        self.assertIn(self.line, self.station.lines.all())

    def test_vehicle_and_line_association(self):
        self.vehicle.lines.add(self.line)
        self.assertIn(self.line, self.vehicle.lines.all())
        self.assertEqual(self.vehicle.status, VehicleStatus.IN_SERVICE)

    def test_asset_creation(self):
        asset = Asset.objects.create(
            station=self.station,
            officialid="ESC-01",
            short_description="Escalator 1",
            asset_type=AssetType.ESCALATOR,
            status=AssetStatus.IN_OPERATION,
        )
        self.assertEqual(asset.station, self.station)
        self.assertEqual(asset.officialid, "ESC-01")

    def test_unique_constraint_on_line_code(self):
        with self.assertRaises(IntegrityError):
            Line.objects.create(
                display_name="Duplicate Line",
                code="KJL",  # duplicate code
                display_color="#00ff00",
            )


@modify_settings(
    MIDDLEWARE={
        "remove": ["strawberry_django.middlewares.debug_toolbar.DebugToolbarMiddleware"]
    }
)
class TrendFeedViewTests(TestCase):
    def setUp(self):
        self.line = Line.objects.create(
            display_name="Kelana Jaya Line",
            code="KJL",
            display_color="#ff0000",
        )
        self.vehicle_type = VehicleType.objects.create(
            display_name="Innovia Metro 300",
            internal_name="INNOVIA_300",
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 40",
            vehicle_type=self.vehicle_type,
            status=VehicleStatus.IN_SERVICE,
        )
        self.vehicle.lines.add(self.line)
        self.user = User.objects.create(firebase_id="firebase-uid-trend-tests")
        self.event_1 = Event.objects.create(
            spotting_date=date(2024, 1, 15),
            reporter=self.user,
            vehicle=self.vehicle,
            status=SpottingVehicleStatus.IN_SERVICE,
            type=SpottingEventType.JUST_SPOTTING,
        )
        self.event_2 = Event.objects.create(
            spotting_date=date(2024, 1, 22),
            reporter=self.user,
            vehicle=self.vehicle,
            status=SpottingVehicleStatus.IN_SERVICE,
            type=SpottingEventType.JUST_SPOTTING,
        )

    def test_line_vehicles_spotting_trend_csv(self):
        response = self.client.get(
            reverse(
                "operation:line_vehicles_spotting_trend",
                kwargs={
                    "line_id": self.line.id,
                    "start_date": "2024-01-01",
                    "end_date": "2024-02-29",
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        body = response.content.decode()
        self.assertIn(self.vehicle.identification_no, body)
        self.assertIn(f"{self.vehicle.identification_no},1,2024-W03", body)

    def test_line_vehicles_status_trend_count(self):
        source = Source.objects.get(name=DataSources.MLPTF)
        snapshot = Snapshot.objects.create(source=source, date=date(2024, 1, 15))
        LineVehicleStatusCountHistory.objects.create(
            snapshot=snapshot,
            line=self.line,
            status=VehicleStatus.IN_SERVICE,
            count=7,
        )
        LineVehicleStatusCountHistory.objects.create(
            snapshot=snapshot,
            line=self.line,
            status=VehicleStatus.OUT_OF_SERVICE,
            count=2,
        )
        response = self.client.get(
            reverse(
                "operation:line_vehicles_status_trend_count",
                kwargs={
                    "line_id": self.line.id,
                    "source_str": "MLPTF",
                    "start_date": "2024-01-01",
                    "end_date": "2024-02-29",
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(len(payload), 2)
        for entry in payload:
            self.assertIn("status", entry)
            self.assertIn("count", entry)
            self.assertIn("date", entry)
            self.assertEqual(entry["date"], "2024-01-15")
        counts = {entry["status"]: entry["count"] for entry in payload}
        self.assertEqual(counts[VehicleStatus.IN_SERVICE], 7)
        self.assertEqual(counts[VehicleStatus.OUT_OF_SERVICE], 2)

    def test_vehicle_spotting_trend(self):
        response = self.client.get(
            reverse(
                "operation:vehicle_spotting_trend",
                kwargs={
                    "vehicle_id": self.vehicle.id,
                    "start_date": "2024-01-01",
                    "end_date": "2024-02-29",
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertIn("data", payload)
        self.assertIn("yearWeek", payload["mappings"])
        total = sum(entry["count"] for entry in payload["data"])
        self.assertEqual(total, 2)


class SimpleHistoryTests(TestCase):
    def setUp(self):
        self.station = Station.objects.create(
            display_name="KL Sentral",
            location=Point(101.6869, 3.1341),
        )
        self.vehicle_type = VehicleType.objects.create(
            display_name="Innovia Metro 300",
            internal_name="INNOVIA_300",
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 40",
            vehicle_type=self.vehicle_type,
            status=VehicleStatus.IN_SERVICE,
        )

    def test_vehicle_history_records_changes(self):
        self.vehicle.status = VehicleStatus.OUT_OF_SERVICE
        self.vehicle.save()
        self.assertEqual(self.vehicle.history.count(), 2)
        latest = self.vehicle.history.order_by("-history_date", "-history_id").first()
        self.assertEqual(latest.status, VehicleStatus.OUT_OF_SERVICE)

    def test_asset_history_records_changes(self):
        asset = Asset.objects.create(
            station=self.station,
            officialid="ESC-01",
            short_description="Escalator 1",
            asset_type=AssetType.ESCALATOR,
            status=AssetStatus.IN_OPERATION,
        )
        asset.status = AssetStatus.UNDER_MAINTENANCE
        asset.save()
        self.assertEqual(asset.history.count(), 2)
        latest = asset.history.order_by("-history_date", "-history_id").first()
        self.assertEqual(latest.status, AssetStatus.UNDER_MAINTENANCE)


class OperationGraphQLTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.line_kjl = Line.objects.create(
            display_name="Kelana Jaya Line",
            code="KJL",
            display_color="#e0115f",
        )
        cls.line_agl = Line.objects.create(
            display_name="Ampang Line",
            code="AGL",
            display_color="#ff7700",
        )

        cls.station_kj15 = Station.objects.create(
            display_name="KL Sentral",
            location=Point(101.6869, 3.1341),
        )
        cls.station_kj10 = Station.objects.create(
            display_name="KLCC",
            location=Point(101.7118, 3.1592),
        )
        cls.station_ag01 = Station.objects.create(
            display_name="Sentul Timur",
            location=Point(101.6953, 3.1861),
        )

        cls.sl_kj15 = StationLine.objects.create(
            station=cls.station_kj15,
            line=cls.line_kjl,
            display_name="KL Sentral KJ",
            internal_representation="KJ15",
        )
        cls.sl_kj10 = StationLine.objects.create(
            station=cls.station_kj10,
            line=cls.line_kjl,
            display_name="KLCC KJ",
            internal_representation="KJ10",
        )
        cls.sl_ag01 = StationLine.objects.create(
            station=cls.station_ag01,
            line=cls.line_agl,
            display_name="Sentul Timur AG",
            internal_representation="AG01",
        )

        cls.vt_innovia = VehicleType.objects.create(
            display_name="Innovia Metro 300",
            internal_name="INNOVIA_300",
            description="Four-car Innovia Metro 300 trainsets",
        )
        cls.vt_amy = VehicleType.objects.create(
            display_name="AMY Light Rail Vehicle",
            internal_name="AMY_LRV",
            description="Six-car CSR Zhuzhou LRV trainsets",
        )

        cls.veh_kjl_1 = Vehicle.objects.create(
            identification_no="Set 40",
            vehicle_type=cls.vt_innovia,
            status=VehicleStatus.IN_SERVICE,
            wheel_status=WheelStatus.FRESH,
        )
        cls.veh_kjl_2 = Vehicle.objects.create(
            identification_no="Set 41",
            vehicle_type=cls.vt_innovia,
            status=VehicleStatus.OUT_OF_SERVICE,
            wheel_status=WheelStatus.WORN_OUT,
        )
        cls.veh_kjl_3 = Vehicle.objects.create(
            identification_no="Set 42",
            vehicle_type=cls.vt_innovia,
            status=VehicleStatus.IN_SERVICE,
            wheel_status=WheelStatus.FRESH,
        )

        cls.veh_agl_1 = Vehicle.objects.create(
            identification_no="Set 10",
            vehicle_type=cls.vt_amy,
            status=VehicleStatus.IN_SERVICE,
            wheel_status=WheelStatus.FRESH,
        )
        cls.veh_agl_2 = Vehicle.objects.create(
            identification_no="Set 11",
            vehicle_type=cls.vt_amy,
            status=VehicleStatus.TESTING,
            wheel_status=WheelStatus.FRESH,
        )

        VehicleLine.objects.create(vehicle=cls.veh_kjl_1, line=cls.line_kjl)
        VehicleLine.objects.create(vehicle=cls.veh_kjl_2, line=cls.line_kjl)
        VehicleLine.objects.create(vehicle=cls.veh_kjl_3, line=cls.line_kjl)

        VehicleLine.objects.create(vehicle=cls.veh_agl_1, line=cls.line_agl)
        VehicleLine.objects.create(vehicle=cls.veh_agl_2, line=cls.line_agl)

        cls.user = User.objects.create(firebase_id="firebase-uid-gql-tests")

        cls.evt_kjl_1 = Event.objects.create(
            spotting_date=date(2024, 1, 15),
            reporter=cls.user,
            vehicle=cls.veh_kjl_1,
            status=SpottingVehicleStatus.IN_SERVICE,
            type=SpottingEventType.JUST_SPOTTING,
        )
        cls.evt_kjl_2 = Event.objects.create(
            spotting_date=date(2024, 3, 20),
            reporter=cls.user,
            vehicle=cls.veh_kjl_1,
            status=SpottingVehicleStatus.IN_SERVICE,
            type=SpottingEventType.JUST_SPOTTING,
        )

        cls.evt_kjl_3 = Event.objects.create(
            spotting_date=date(2024, 3, 25),
            reporter=cls.user,
            vehicle=cls.veh_kjl_3,
            status=SpottingVehicleStatus.IN_SERVICE,
            type=SpottingEventType.JUST_SPOTTING,
        )

    def test_lines_and_vehicles_nested_hierarchy(self):
        query = """
            query {
                lines {
                    id
                    code
                    vehicleTypes {
                        id
                        internalName
                        vehicles {
                            id
                            identificationNo
                            status
                        }
                    }
                }
            }
        """
        result = execute_graphql(query)

        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)
        lines_data = {line["code"]: line for line in result.data["lines"]}

        self.assertIn("KJL", lines_data)
        self.assertIn("AGL", lines_data)

        kjl_types = lines_data["KJL"]["vehicleTypes"]
        self.assertEqual(len(kjl_types), 1)
        self.assertEqual(kjl_types[0]["internalName"], "INNOVIA_300")
        kjl_vehicles = {v["identificationNo"] for v in kjl_types[0]["vehicles"]}
        self.assertEqual(kjl_vehicles, {"Set 40", "Set 41", "Set 42"})

        agl_types = lines_data["AGL"]["vehicleTypes"]
        self.assertEqual(len(agl_types), 1)
        self.assertEqual(agl_types[0]["internalName"], "AMY_LRV")
        agl_vehicles = {v["identificationNo"] for v in agl_types[0]["vehicles"]}
        self.assertEqual(agl_vehicles, {"Set 10", "Set 11"})

    def test_vehicle_types_by_line_filter(self):
        query = """
            query GetVehicleTypesByLine($lineId: ID!) {
                vehicleTypes(filters: { lineId: $lineId }) {
                    id
                    internalName
                    displayName
                    vehicles {
                        wheelStatus
                        status
                    }
                    vehicleStatusInServiceCount
                    vehicleStatusOutOfServiceCount
                    vehicleStatusTestingCount
                    vehicleTotalCount
                }
            }
        """
        result_kjl = execute_graphql(query, variables={"lineId": str(self.line_kjl.id)})
        self.assertIsNone(result_kjl.errors)
        self.assertIsNotNone(result_kjl.data)
        vtypes_kjl = result_kjl.data["vehicleTypes"]
        vt_kjl_dict = {vt["internalName"]: vt for vt in vtypes_kjl}
        self.assertIn("INNOVIA_300", vt_kjl_dict)
        vt_kjl_data = vt_kjl_dict["INNOVIA_300"]
        self.assertEqual(vt_kjl_data["vehicleStatusInServiceCount"], 2)
        self.assertEqual(vt_kjl_data["vehicleStatusOutOfServiceCount"], 1)
        self.assertEqual(vt_kjl_data["vehicleStatusTestingCount"], 0)
        self.assertEqual(vt_kjl_data["vehicleTotalCount"], 3)

        wheel_statuses = [v["wheelStatus"] for v in vt_kjl_data["vehicles"]]
        self.assertIn(WheelStatus.FRESH.name, wheel_statuses)
        self.assertIn(WheelStatus.WORN_OUT.name, wheel_statuses)

        result_agl = execute_graphql(query, variables={"lineId": str(self.line_agl.id)})
        self.assertIsNone(result_agl.errors)
        self.assertIsNotNone(result_agl.data)
        vtypes_agl = result_agl.data["vehicleTypes"]
        vt_agl_dict = {vt["internalName"]: vt for vt in vtypes_agl}
        self.assertIn("AMY_LRV", vt_agl_dict)
        vt_agl_data = vt_agl_dict["AMY_LRV"]
        self.assertEqual(vt_agl_data["vehicleStatusInServiceCount"], 1)
        self.assertEqual(vt_agl_data["vehicleStatusOutOfServiceCount"], 0)
        self.assertEqual(vt_agl_data["vehicleStatusTestingCount"], 1)
        self.assertEqual(vt_agl_data["vehicleTotalCount"], 2)

    def test_station_lines_by_line_filter(self):
        query = """
            query GetStationLinesByLine($lineId: ID!) {
                stationLines(filters: { line: { id: $lineId } }) {
                    id
                    displayName
                    internalRepresentation
                }
            }
        """
        result = execute_graphql(query, variables={"lineId": str(self.line_kjl.id)})
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)
        station_lines = result.data["stationLines"]
        self.assertEqual(len(station_lines), 2)
        reps = {sl["internalRepresentation"] for sl in station_lines}
        self.assertEqual(reps, {"KJ15", "KJ10"})

        names = {sl["displayName"] for sl in station_lines}
        self.assertEqual(names, {"KL Sentral KJ", "KLCC KJ"})

    def test_line_vehicle_spotting_trends_with_zero_filling(self):
        query = """
            query GetLineTrends($lineId: ID!, $start: Date!, $end: Date!) {
                lines(filters: { id: $lineId }) {
                    id
                    code
                    vehicleSpottingTrends(
                        start: $start
                        end: $end
                        dateGroup: MONTH
                        addZero: true
                    ) {
                        dateKey
                        year
                        month
                        count
                        vehicle {
                            identificationNo
                        }
                    }
                }
            }
        """
        result = execute_graphql(
            query,
            variables={
                "lineId": str(self.line_kjl.id),
                "start": "2024-01-01",
                "end": "2024-04-30",
            },
        )
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data)
        lines = result.data["lines"]
        self.assertEqual(len(lines), 1)
        trends = lines[0]["vehicleSpottingTrends"]

        self.assertEqual(len(trends), 12)

        set40_trends = {
            t["dateKey"]: t["count"]
            for t in trends
            if t["vehicle"]["identificationNo"] == "Set 40"
        }
        self.assertEqual(set40_trends.get("2024-01"), 1)
        self.assertEqual(set40_trends.get("2024-02"), 0)
        self.assertEqual(set40_trends.get("2024-03"), 1)
        self.assertEqual(set40_trends.get("2024-04"), 0)

        set41_trends = {
            t["dateKey"]: t["count"]
            for t in trends
            if t["vehicle"]["identificationNo"] == "Set 41"
        }
        self.assertEqual(
            set41_trends, {"2024-01": 0, "2024-02": 0, "2024-03": 0, "2024-04": 0}
        )

        set42_trends = {
            t["dateKey"]: t["count"]
            for t in trends
            if t["vehicle"]["identificationNo"] == "Set 42"
        }
        self.assertEqual(set42_trends.get("2024-01"), 0)
        self.assertEqual(set42_trends.get("2024-02"), 0)
        self.assertEqual(set42_trends.get("2024-03"), 1)
        self.assertEqual(set42_trends.get("2024-04"), 0)

        query_day = """
            query GetLineTrendsDay($lineId: ID!, $start: Date!, $end: Date!) {
                lines(filters: { id: $lineId }) {
                    vehicleSpottingTrends(
                        start: $start
                        end: $end
                        dateGroup: DAY
                        addZero: true
                    ) {
                        dateKey
                        day
                        count
                    }
                }
            }
        """
        result_day = execute_graphql(
            query_day,
            variables={
                "lineId": str(self.line_kjl.id),
                "start": "2024-01-14",
                "end": "2024-01-16",
            },
        )
        self.assertIsNone(result_day.errors)
        day_trends = result_day.data["lines"][0]["vehicleSpottingTrends"]
        self.assertEqual(len(day_trends), 9)

        query_week = """
            query GetLineTrendsWeek($lineId: ID!, $start: Date!, $end: Date!) {
                lines(filters: { id: $lineId }) {
                    vehicleSpottingTrends(
                        start: $start
                        end: $end
                        dateGroup: WEEK
                        addZero: false
                    ) {
                        dateKey
                        count
                    }
                }
            }
        """
        result_week = execute_graphql(
            query_week,
            variables={
                "lineId": str(self.line_kjl.id),
                "start": "2024-01-01",
                "end": "2024-03-31",
            },
        )
        self.assertIsNone(result_week.errors)
        week_trends = result_week.data["lines"][0]["vehicleSpottingTrends"]
        self.assertTrue(len(week_trends) >= 2)

    def test_vehicle_spotting_count_dataloader_cache_key(self):
        query_all = """
            query GetVehicleSpottingCountsAll($vehId: ID!) {
                vehicles(filters: { id: $vehId }) {
                    id
                    countAll: spottingCount
                }
            }
        """
        query_filtered = """
            query GetVehicleSpottingCountsFiltered($vehId: ID!) {
                vehicles(filters: { id: $vehId }) {
                    id
                    countAfterFeb: spottingCount(after: "2024-02-01")
                }
            }
        """
        result_all = execute_graphql(
            query_all, variables={"vehId": str(self.veh_kjl_1.id)}
        )
        self.assertIsNone(result_all.errors)
        self.assertEqual(result_all.data["vehicles"][0]["countAll"], 2)

        result_filtered = execute_graphql(
            query_filtered, variables={"vehId": str(self.veh_kjl_1.id)}
        )
        self.assertIsNone(result_filtered.errors)
        self.assertEqual(result_filtered.data["vehicles"][0]["countAfterFeb"], 1)

        result_v3 = execute_graphql(
            query_all, variables={"vehId": str(self.veh_kjl_3.id)}
        )
        self.assertIsNone(result_v3.errors)
        self.assertEqual(result_v3.data["vehicles"][0]["countAll"], 1)

        result_query_multiple_vehicles = execute_graphql(
            """
            query GetMultipleVehicleCounts {
                vehicles {
                    id
                    identificationNo
                    spottingCount
                }
            }
            """
        )
        self.assertIsNone(result_query_multiple_vehicles.errors)
        counts_by_ident = {
            v["identificationNo"]: v["spottingCount"]
            for v in result_query_multiple_vehicles.data["vehicles"]
        }
        self.assertEqual(counts_by_ident.get("Set 40"), 2)
        self.assertEqual(counts_by_ident.get("Set 41"), 0)
        self.assertEqual(counts_by_ident.get("Set 42"), 1)
        self.assertEqual(counts_by_ident.get("Set 10"), 0)
        self.assertEqual(counts_by_ident.get("Set 11"), 0)


class TestFilterDecorators(TestCase):
    """Test that filter decorators are correctly applied."""

    def test_line_filter(self):
        """Verify LineFilter has correct strawberry_django decorator."""
        from operation.schema.filters import LineFilter

        self.assertTrue(
            hasattr(LineFilter, "__strawberry_django_definition__"),
            "LineFilter missing strawberry_django decorator",
        )

    def test_station_filter(self):
        """Verify StationFilter has correct strawberry_django decorator."""
        from operation.schema.filters import StationFilter

        self.assertTrue(
            hasattr(StationFilter, "__strawberry_django_definition__"),
            "StationFilter missing strawberry_django decorator",
        )


class TestTrendsResolvers(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.line_kjl = Line.objects.create(
            display_name="Kelana Jaya Line",
            code="KJL",
            display_color="#e0115f",
        )
        cls.vt_innovia = VehicleType.objects.create(
            display_name="Innovia Metro 300",
            internal_name="INNOVIA_300",
            description="Four-car Innovia Metro 300 trainsets",
        )
        cls.veh_kjl_1 = Vehicle.objects.create(
            identification_no="Set 40",
            vehicle_type=cls.vt_innovia,
            status=VehicleStatus.IN_SERVICE,
            wheel_status=WheelStatus.FRESH,
        )
        VehicleLine.objects.create(vehicle=cls.veh_kjl_1, line=cls.line_kjl)

        cls.user = User.objects.create(firebase_id="firebase-uid-trends-tests")

        cls.evt_kjl_1 = Event.objects.create(
            spotting_date=date(2024, 1, 15),
            reporter=cls.user,
            vehicle=cls.veh_kjl_1,
            status=SpottingVehicleStatus.IN_SERVICE,
            type=SpottingEventType.JUST_SPOTTING,
        )

    def test_line_spotting_trends_defaults(self):
        from operation.schema.scalars import Line as LineScalar

        trends = LineScalar.vehicle_spotting_trends.base_resolver(
            self.line_kjl, start=None, end=None
        )
        self.assertIsInstance(trends, list)

    def test_vehicle_spotting_trends_custom_range(self):
        from strawberry.types.maybe import Some

        from generic.schema.enums import DateGroupings
        from operation.schema.scalars import Vehicle as VehicleScalar

        trends = VehicleScalar.spotting_trends.base_resolver(
            self.veh_kjl_1,
            start=Some(date(2024, 1, 14)),
            end=Some(date(2024, 1, 16)),
            date_group=DateGroupings.DAY,
            add_zero=True,
        )
        self.assertEqual(len(trends), 3)
