from datetime import date, datetime

from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from incident.enums import CalendarIncidentSeverity, IncidentSeverity
from incident.models import (
    CalendarIncident,
    CalendarIncidentCategory,
    CalendarIncidentChronology,
    StationIncident,
    VehicleIncident,
)
from operation.models import Line, Station, Vehicle, VehicleType


class IncidentModelTests(TestCase):
    def setUp(self):
        self.line = Line.objects.create(
            code="MRT1", display_name="Kajang Line", display_color="#008800"
        )
        self.station = Station.objects.create(
            display_name="Muzium Negara", location=Point(101.68, 3.13)
        )
        self.v_type = VehicleType.objects.create(
            internal_name="INSPIRA", display_name="Inspira"
        )
        self.vehicle = Vehicle.objects.create(
            identification_no="Set 25", vehicle_type=self.v_type
        )

    def test_calendar_incident_creation(self):
        category = CalendarIncidentCategory.objects.create(name="Track Fault")
        incident = CalendarIncident.objects.create(
            title="Track circuit failure",
            brief="Delay expected",
            severity=CalendarIncidentSeverity.MAJOR,
            start_datetime=timezone.now(),
            end_datetime=timezone.now() + timezone.timedelta(hours=2),
            impact_factor=10,
        )
        incident.categories.add(category)
        incident.lines.add(self.line)

        self.assertEqual(incident.severity, CalendarIncidentSeverity.MAJOR)
        self.assertIn(self.line, incident.lines.all())
        self.assertIn(category, incident.categories.all())

    def test_incident_chronology(self):
        incident = CalendarIncident.objects.create(
            title="Switch failure",
            brief="Minor delays",
            severity=CalendarIncidentSeverity.MINOR,
            start_datetime=timezone.now(),
        )
        chronology = CalendarIncidentChronology.objects.create(
            calendar_incident=incident,
            content="Repair team dispatched",
            datetime=timezone.now(),
        )
        self.assertEqual(chronology.calendar_incident, incident)
        self.assertEqual(incident.chronologies.count(), 1)

    def test_vehicle_incident_partial_unique_constraint(self):
        VehicleIncident.objects.create(
            vehicle=self.vehicle,
            date=date(2026, 1, 1),
            severity=IncidentSeverity.CRITICAL,
            title="First historical incident",
            brief="Brake fault",
            is_last=False,
        )
        VehicleIncident.objects.create(
            vehicle=self.vehicle,
            date=date(2026, 1, 2),
            severity=IncidentSeverity.TRIVIA,
            title="Second historical incident",
            brief="Door sensor fault",
            is_last=False,
        )
        VehicleIncident.objects.create(
            vehicle=self.vehicle,
            date=date(2026, 1, 3),
            severity=IncidentSeverity.STATUS,
            title="Current last incident",
            brief="Aircon fault",
            is_last=True,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VehicleIncident.objects.create(
                    vehicle=self.vehicle,
                    date=date(2026, 1, 4),
                    severity=IncidentSeverity.CRITICAL,
                    title="Duplicate last incident",
                    brief="Traction fault",
                    is_last=True,
                )

    def test_station_incident_unconditional_unique_constraint_blocks_second_historical(
        self,
    ):
        StationIncident.objects.create(
            station=self.station,
            date=date(2026, 1, 1),
            severity=IncidentSeverity.CRITICAL,
            title="First historical incident",
            brief="Escalator issue",
            is_last=False,
        )
        StationIncident.objects.create(
            station=self.station,
            date=date(2026, 1, 2),
            severity=IncidentSeverity.STATUS,
            title="Current last incident",
            brief="Gate issue",
            is_last=True,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StationIncident.objects.create(
                    station=self.station,
                    date=date(2026, 1, 3),
                    severity=IncidentSeverity.TRIVIA,
                    title="Second historical incident",
                    brief="Lighting issue",
                    is_last=False,
                )

    def test_calendar_incident_naive_datetime_storage_pin(self):
        now = datetime.now()
        self.assertIsNone(now.tzinfo)
        incident = CalendarIncident.objects.create(
            title="Signalling failure",
            brief="Delays expected across line",
            severity=CalendarIncidentSeverity.MAJOR,
            start_datetime=now,
        )
        incident.refresh_from_db()
        self.assertIsNone(incident.start_datetime.tzinfo)
