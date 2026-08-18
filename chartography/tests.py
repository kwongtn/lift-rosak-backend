from datetime import date, timedelta
from unittest.mock import Mock, patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from django.utils.timezone import now

from chartography.enums import DataSources
from chartography.models import (
    LineVehicleStatusCountHistory,
    Snapshot,
    Source,
    SourceCustomLine,
)
from chartography.tasks import (
    aggregate_line_vehicle_status_mlptf_task,
    aggregate_line_vehicle_status_mtrec_task,
)
from common.models import User
from operation.enums import VehicleStatus
from operation.models import Line, Vehicle, VehicleLine, VehicleType


class ChartographyModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="chart-user-1")
        self.source, _ = Source.objects.get_or_create(name=DataSources.MLPTF)
        self.line = Line.objects.create(
            code="BRT", display_name="Sunway Line", display_color="#00aa00"
        )

    def test_snapshot_and_history(self):
        snapshot = Snapshot.objects.create(
            source=self.source,
            date=timezone.now().date(),
            triggered_by=self.user,
        )
        history = LineVehicleStatusCountHistory.objects.create(
            snapshot=snapshot,
            line=self.line,
            status=VehicleStatus.IN_SERVICE,
            count=5,
        )
        self.assertEqual(history.count, 5)
        self.assertEqual(history.line, self.line)
        self.assertEqual(
            LineVehicleStatusCountHistory.objects.filter(snapshot=snapshot).count(), 1
        )


class AggregateLineVehicleStatusMlptfTaskTests(TestCase):
    def setUp(self):
        self.source = Source.objects.get(name=DataSources.MLPTF)
        self.line = Line.objects.create(
            code="TST",
            display_name="Task Test Line",
            display_color="#123456",
        )
        self.vehicle_type = VehicleType.objects.create(
            internal_name="TSTVT",
            display_name="Task Test Vehicle Type",
        )
        for i in range(3):
            vehicle = Vehicle.objects.create(
                identification_no=f"IS{i:04d}",
                vehicle_type=self.vehicle_type,
                status=VehicleStatus.IN_SERVICE,
            )
            VehicleLine.objects.create(vehicle=vehicle, line=self.line)
        decommissioned = Vehicle.objects.create(
            identification_no="DC0001",
            vehicle_type=self.vehicle_type,
            status=VehicleStatus.DECOMMISSIONED,
        )
        VehicleLine.objects.create(vehicle=decommissioned, line=self.line)

    def test_task_creates_snapshot_and_history(self):
        snapshot_count_before = Snapshot.objects.filter(source=self.source).count()

        aggregate_line_vehicle_status_mlptf_task.apply()

        self.assertEqual(
            Snapshot.objects.filter(source=self.source).count(),
            snapshot_count_before + 1,
        )
        snapshot = Snapshot.objects.filter(source=self.source).latest("id")
        self.assertEqual(snapshot.date, (now() - timedelta(days=1)).date())
        self.assertIsNone(snapshot.triggered_by)

        history_qs = LineVehicleStatusCountHistory.objects.filter(
            snapshot=snapshot,
            line=self.line,
        )
        # The task bulk_creates one row per line x status, including
        # count=0 rows for statuses with no matching vehicles.
        self.assertEqual(history_qs.count(), len(VehicleStatus.choices))
        counts = {row.status: row.count for row in history_qs}
        self.assertEqual(counts[VehicleStatus.IN_SERVICE], 3)
        self.assertEqual(counts[VehicleStatus.DECOMMISSIONED], 1)
        for status, _label in VehicleStatus.choices:
            if status not in (VehicleStatus.IN_SERVICE, VehicleStatus.DECOMMISSIONED):
                self.assertEqual(counts[status], 0)

    def test_second_run_same_date_raises_integrity_error(self):
        aggregate_line_vehicle_status_mlptf_task.apply()

        # Snapshot has a partial UniqueConstraint on (date, source) where
        # triggered_by IS NULL, so an identical second run on the same date
        # violates it and the task propagates IntegrityError.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                aggregate_line_vehicle_status_mlptf_task.apply(throw=True)


class AggregateLineVehicleStatusMtrecTaskTests(TestCase):
    def setUp(self):
        self.source = Source.objects.get(name=DataSources.MTREC)
        # The task maps short codes to hardcoded numeric Line PKs (KJL -> [4]).
        self.line = Line.objects.create(
            id=4,
            code="KJL",
            display_name="Kelana Jaya Line",
            display_color="#ff0000",
        )

    @staticmethod
    def _mock_get_return(payload):
        mock_response = Mock()
        mock_response.json.return_value = payload
        return mock_response

    @patch("chartography.tasks.requests.get")
    def test_task_creates_snapshot_history_and_custom_line(self, mock_get):
        mock_get.return_value = self._mock_get_return(
            {
                "Last_Updated": "01 January 2025, 05:00:00 AM",
                "Data": [
                    {
                        "Line_Short_Code": "KJL",
                        "Decommissioned": 2,
                        "In_Service": 30,
                        "Not_Spotted": 3,
                    },
                    {
                        "Line_Short_Code": "DMU",
                        "Decommissioned": 1,
                        "In_Service": 4,
                        "Not_Spotted": 2,
                    },
                ],
            }
        )

        aggregate_line_vehicle_status_mtrec_task.apply()

        snapshot = Snapshot.objects.get(source=self.source)
        # Snapshot date is the parsed Last_Updated timestamp minus one day.
        self.assertEqual(snapshot.date, date(2024, 12, 31))

        line_history = LineVehicleStatusCountHistory.objects.filter(
            snapshot=snapshot,
            line_id=4,
        )
        self.assertEqual(line_history.count(), 3)
        counts = {row.status: row.count for row in line_history}
        self.assertEqual(counts[VehicleStatus.IN_SERVICE], 30)
        self.assertEqual(counts[VehicleStatus.DECOMMISSIONED], 2)
        self.assertEqual(counts[VehicleStatus.NOT_SPOTTED], 3)

        # Short codes mapped to an empty PK list (e.g. DMU) go through the
        # SourceCustomLine path and history rows reference custom_line.
        custom_line = SourceCustomLine.objects.get(source=self.source, name="DMU")
        custom_history = LineVehicleStatusCountHistory.objects.filter(
            snapshot=snapshot,
            custom_line=custom_line,
        )
        self.assertEqual(custom_history.count(), 3)
        custom_counts = {row.status: row.count for row in custom_history}
        self.assertEqual(custom_counts[VehicleStatus.IN_SERVICE], 4)
        self.assertEqual(custom_counts[VehicleStatus.DECOMMISSIONED], 1)
        self.assertEqual(custom_counts[VehicleStatus.NOT_SPOTTED], 2)
        for row in custom_history:
            self.assertIsNone(row.line_id)

    @patch("chartography.tasks.requests.get")
    def test_unknown_short_code_raises_assertion_error(self, mock_get):
        mock_get.return_value = self._mock_get_return(
            {
                "Last_Updated": "01 January 2025, 05:00:00 AM",
                "Data": [
                    {
                        "Line_Short_Code": "KJL",
                        "Decommissioned": 2,
                        "In_Service": 30,
                        "Not_Spotted": 3,
                    },
                    {
                        "Line_Short_Code": "UNKNOWNXYZ",
                        "Decommissioned": 0,
                        "In_Service": 1,
                        "Not_Spotted": 0,
                    },
                ],
            }
        )

        # Known catalogued defect: the task's bare `assert isinstance(...)`
        # fires for short codes missing from the hardcoded PK map.
        with self.assertRaises(AssertionError):
            aggregate_line_vehicle_status_mtrec_task.apply(throw=True)

        # The Snapshot is created before the loop and is not rolled back,
        # but bulk_create is never reached so no history rows persist.
        snapshot = Snapshot.objects.get(source=self.source)
        self.assertEqual(snapshot.date, date(2024, 12, 31))
        self.assertEqual(
            LineVehicleStatusCountHistory.objects.filter(snapshot=snapshot).count(),
            0,
        )
