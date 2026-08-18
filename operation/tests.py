import json
from datetime import date

from django.contrib.gis.geos import Point
from django.db import IntegrityError
from django.test import TestCase, modify_settings
from django.urls import reverse

from chartography.enums import DataSources
from chartography.models import LineVehicleStatusCountHistory, Snapshot, Source
from common.models import User
from operation.enums import AssetStatus, AssetType, VehicleStatus
from operation.models import Asset, Line, Station, StationLine, Vehicle, VehicleType
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event


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
