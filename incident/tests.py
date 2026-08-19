import copy
from datetime import date, datetime, timedelta

from asgiref.sync import async_to_sync
from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from dotmap import DotMap
from graphql import GraphQLError
from strawberry.types.maybe import Some

from common.models import Media, User
from incident.enums import (
    CalendarIncidentChronologyIndicator,
    CalendarIncidentSeverity,
    IncidentSeverity,
)
from incident.models import (
    CalendarIncident,
    CalendarIncidentCategory,
    CalendarIncidentChronology,
    CalendarIncidentMedia,
    StationIncident,
    VehicleIncident,
)
from operation.models import Line, Station, Vehicle, VehicleType
from rosak.context import ContextLoaders
from rosak.schema import schema


def execute_graphql(query: str, variables=None, user=None):
    context = DotMap(
        {
            "loaders": copy.deepcopy(ContextLoaders),
            "request": None,
            "response": None,
            "user": user,
        }
    )
    return async_to_sync(schema.execute)(
        query, variable_values=variables, context_value=context
    )


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


class IncidentSchemaExecutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(firebase_id="incident-test-user-1")
        cls.line = Line.objects.create(
            code="KJL", display_name="Kelana Jaya Line", display_color="#e0115f"
        )
        cls.station = Station.objects.create(
            display_name="KLCC", location=Point(101.71, 3.15)
        )
        cls.v_type = VehicleType.objects.create(
            internal_name="KJL_INNOVIA", display_name="Innovia"
        )
        cls.vehicle = Vehicle.objects.create(
            identification_no="Set 20", vehicle_type=cls.v_type
        )
        cls.category = CalendarIncidentCategory.objects.create(name="Signalling")
        cls.media = Media.objects.create(
            uploader=cls.user,
            file_id="12345",
            file_name="incident.jpg",
        )

    def test_calendar_incidents_full_graph_query(self):
        incident = CalendarIncident.objects.create(
            title="Complete Signal Failure",
            brief="Full line stoppage",
            details="Technicians troubleshooting trackside ATP unit.",
            severity=CalendarIncidentSeverity.MAJOR,
            start_datetime=timezone.now() - timedelta(hours=2),
            end_datetime=timezone.now(),
            impact_factor=15.5,
        )
        incident.lines.add(self.line)
        incident.vehicles.add(self.vehicle)
        incident.stations.add(self.station)
        incident.categories.add(self.category)

        CalendarIncidentMedia.objects.create(
            calendar_incident=incident,
            media=self.media,
        )

        CalendarIncidentChronology.objects.create(
            calendar_incident=incident,
            indicator=CalendarIncidentChronologyIndicator.RED,
            datetime=timezone.now() - timedelta(hours=1),
            content="Power reset attempt initiated",
        )

        query = """
            query {
                calendarIncidents {
                    id
                    title
                    brief
                    details
                    severity
                    impactFactor
                    lines {
                        id
                    }
                    vehicles {
                        id
                    }
                    stations {
                        id
                    }
                    chronologies {
                        datetime
                        content
                    }
                    medias {
                        id
                    }
                    hasDetails
                    lastUpdated
                }
            }
        """
        result = execute_graphql(query)
        self.assertIsNone(result.errors)
        self.assertEqual(len(result.data["calendarIncidents"]), 1)
        inc_data = result.data["calendarIncidents"][0]
        self.assertEqual(inc_data["id"], str(incident.id))
        self.assertEqual(inc_data["title"], "Complete Signal Failure")
        self.assertEqual(inc_data["brief"], "Full line stoppage")
        self.assertEqual(
            inc_data["details"], "Technicians troubleshooting trackside ATP unit."
        )
        self.assertEqual(inc_data["severity"], CalendarIncidentSeverity.MAJOR)
        self.assertEqual(inc_data["impactFactor"], 15.5)

        self.assertEqual(len(inc_data["lines"]), 1)
        self.assertEqual(inc_data["lines"][0]["id"], str(self.line.id))

        self.assertEqual(len(inc_data["vehicles"]), 1)
        self.assertEqual(inc_data["vehicles"][0]["id"], str(self.vehicle.id))

        self.assertEqual(len(inc_data["stations"]), 1)
        self.assertEqual(inc_data["stations"][0]["id"], str(self.station.id))

        self.assertEqual(len(inc_data["chronologies"]), 1)
        self.assertEqual(
            inc_data["chronologies"][0]["content"], "Power reset attempt initiated"
        )
        self.assertIsNotNone(inc_data["chronologies"][0]["datetime"])

        self.assertEqual(len(inc_data["medias"]), 1)
        self.assertEqual(inc_data["medias"][0]["id"], str(self.media.id))

        self.assertTrue(inc_data["hasDetails"])
        self.assertIsNotNone(inc_data["lastUpdated"])

    def test_calendar_incident_filter_date_range(self):
        incident_in_range = CalendarIncident.objects.create(
            title="Within January 2024",
            brief="Inside range",
            severity=CalendarIncidentSeverity.MINOR,
            start_datetime=datetime(2024, 1, 5, 10, 0),
            end_datetime=datetime(2024, 1, 7, 12, 0),
        )

        incident_ongoing = CalendarIncident.objects.create(
            title="Ongoing January 2024",
            brief="Started Jan 10, no end date",
            severity=CalendarIncidentSeverity.MAJOR,
            start_datetime=datetime(2024, 1, 10, 8, 0),
            end_datetime=None,
        )

        incident_outside_range = CalendarIncident.objects.create(
            title="Outside February 2024",
            brief="Starts Feb 15",
            severity=CalendarIncidentSeverity.MINOR,
            start_datetime=datetime(2024, 2, 15, 10, 0),
            end_datetime=datetime(2024, 2, 16, 10, 0),
        )

        query = """
            query {
                calendarIncidents(filters: { date: { range: { start: "2024-01-01", end: "2024-01-31" } } }) {
                    id
                    title
                    startDatetime
                    endDatetime
                }
            }
        """
        result = execute_graphql(query)
        self.assertIsNone(result.errors)
        returned_ids = [inc["id"] for inc in result.data["calendarIncidents"]]
        self.assertIn(str(incident_in_range.id), returned_ids)
        self.assertIn(str(incident_ongoing.id), returned_ids)
        self.assertNotIn(str(incident_outside_range.id), returned_ids)

    def test_vehicle_incidents_query_filter_by_vehicle(self):
        v_type2 = VehicleType.objects.create(
            internal_name="KJL_INNOVIA_2", display_name="Innovia 2"
        )
        vehicle2 = Vehicle.objects.create(
            identification_no="Set 21", vehicle_type=v_type2
        )

        VehicleIncident.objects.create(
            vehicle=self.vehicle,
            date=date(2024, 1, 1),
            severity=IncidentSeverity.CRITICAL,
            title="Brake System Failure",
            brief="Emergency brakes deployed",
            is_last=False,
        )
        VehicleIncident.objects.create(
            vehicle=self.vehicle,
            date=date(2024, 1, 2),
            severity=IncidentSeverity.STATUS,
            title="Brake Sensor Calibration",
            brief="Sensors recalibrated",
            is_last=True,
        )
        VehicleIncident.objects.create(
            vehicle=vehicle2,
            date=date(2024, 1, 3),
            severity=IncidentSeverity.TRIVIA,
            title="Door Squeak",
            brief="Lubricated door track",
            is_last=True,
        )

        query = """
            query GetVehicleIncidents($vehicleId: ID) {
                vehicleIncidents(filters: { vehicle: { id: $vehicleId } }) {
                    date
                    severity
                    title
                    isLast
                }
            }
        """
        result = execute_graphql(query, variables={"vehicleId": str(self.vehicle.id)})
        self.assertIsNone(result.errors)
        self.assertEqual(len(result.data["vehicleIncidents"]), 2)

        titles = [inc["title"] for inc in result.data["vehicleIncidents"]]
        self.assertIn("Brake System Failure", titles)
        self.assertIn("Brake Sensor Calibration", titles)
        self.assertNotIn("Door Squeak", titles)

        item = next(
            inc
            for inc in result.data["vehicleIncidents"]
            if inc["title"] == "Brake Sensor Calibration"
        )
        self.assertEqual(item["date"], "2024-01-02")
        self.assertEqual(item["severity"], IncidentSeverity.STATUS)
        self.assertTrue(item["isLast"])

    def test_calendar_incident_has_details_computed_field(self):
        inc_with_details = CalendarIncident.objects.create(
            title="Incident with Details",
            brief="Brief description",
            details="Here are the in-depth incident details.",
            severity=CalendarIncidentSeverity.MAJOR,
            start_datetime=datetime(2024, 3, 1, 12, 0),
        )
        inc_without_details_empty = CalendarIncident.objects.create(
            title="Incident without Details Empty",
            brief="Brief description",
            details="",
            severity=CalendarIncidentSeverity.MINOR,
            start_datetime=datetime(2024, 3, 2, 12, 0),
        )

        query = """
            query {
                calendarIncidents {
                    id
                    hasDetails
                }
            }
        """
        result = execute_graphql(query)
        self.assertIsNone(result.errors)

        details_map = {
            inc["id"]: inc["hasDetails"] for inc in result.data["calendarIncidents"]
        }
        self.assertTrue(details_map[str(inc_with_details.id)])
        self.assertFalse(details_map[str(inc_without_details_empty.id)])

    def test_calendar_incident_last_updated_chronology_fallback(self):
        incident = CalendarIncident.objects.create(
            title="Incident with Chronologies",
            brief="Brief description",
            severity=CalendarIncidentSeverity.MAJOR,
            start_datetime=timezone.now() - timedelta(days=2),
        )
        inc_modified = incident.modified

        query = f"""
            query {{
                calendarIncidents(filters: {{ id: "{incident.id}" }}) {{
                    id
                    lastUpdated
                }}
            }}
        """
        result = execute_graphql(query)
        self.assertIsNone(result.errors)
        self.assertEqual(len(result.data["calendarIncidents"]), 1)
        self.assertEqual(
            datetime.fromisoformat(result.data["calendarIncidents"][0]["lastUpdated"]),
            inc_modified,
        )

        chronology = CalendarIncidentChronology.objects.create(
            calendar_incident=incident,
            indicator=CalendarIncidentChronologyIndicator.BLUE,
            datetime=timezone.now(),
            content="Update regarding train recovery",
        )
        CalendarIncidentChronology.objects.filter(id=chronology.id).update(
            modified=inc_modified + timedelta(hours=3)
        )
        chronology.refresh_from_db()

        result = execute_graphql(query)
        self.assertIsNone(result.errors)
        self.assertEqual(
            datetime.fromisoformat(result.data["calendarIncidents"][0]["lastUpdated"]),
            chronology.modified,
        )


class TestCalendarIncidentResolvers(TestCase):
    def test_severity_count_requires_both_dates(self):
        query = """
            query {
                calendarIncidentsBySeverityCount(groupBy: DAY) {
                    date
                    severity
                    count
                }
            }
        """
        result = execute_graphql(query)
        self.assertIsNotNone(result.errors)
        self.assertTrue(
            any(
                "start_date and end_date required" in (error.message or "")
                for error in result.errors
            )
        )

    def test_severity_count_with_valid_date_range(self):
        CalendarIncident.objects.create(
            title="Test Incident",
            brief="Brief",
            severity=CalendarIncidentSeverity.MAJOR,
            start_datetime=datetime(2024, 1, 5, 10, 0),
            end_datetime=datetime(2024, 1, 6, 10, 0),
        )
        query = """
            query {
                calendarIncidentsBySeverityCount(
                    startDate: "2024-01-01"
                    endDate: "2024-01-31"
                    groupBy: DAY
                ) {
                    date
                    severity
                    count
                }
            }
        """
        result = execute_graphql(query)
        self.assertIsNone(result.errors)
        self.assertIsNotNone(result.data["calendarIncidentsBySeverityCount"])
        self.assertGreater(len(result.data["calendarIncidentsBySeverityCount"]), 0)


class TestCalendarIncidentFilter(TestCase):
    def setUp(self):
        self.incident_jan = CalendarIncident.objects.create(
            title="January overlap",
            brief="Runs Jan 10-12",
            severity=CalendarIncidentSeverity.MINOR,
            start_datetime=datetime(2024, 1, 10, 8, 0),
            end_datetime=datetime(2024, 1, 12, 8, 0),
        )
        self.incident_ongoing_jan = CalendarIncident.objects.create(
            title="Ongoing from January",
            brief="Started Jan 20, no end date",
            severity=CalendarIncidentSeverity.MAJOR,
            start_datetime=datetime(2024, 1, 20, 8, 0),
            end_datetime=None,
        )
        self.incident_jun = CalendarIncident.objects.create(
            title="June incident",
            brief="Runs Jun 1-2",
            severity=CalendarIncidentSeverity.MINOR,
            start_datetime=datetime(2024, 6, 1, 8, 0),
            end_datetime=datetime(2024, 6, 2, 8, 0),
        )

    def _apply_date_filter(self, date_input):
        from incident.schema.filters import CalendarIncidentFilter

        filter_method = vars(CalendarIncidentFilter)["date"]
        q = filter_method(CalendarIncidentFilter(), value=date_input, prefix="")
        return CalendarIncident.objects.filter(q)

    def test_filter_date_range_both_start_end(self):
        from incident.schema.filters import CalendarIncidentDateFilter, DateRangeInput

        date_input = CalendarIncidentDateFilter(
            range=Some(
                DateRangeInput(
                    start=Some(date(2024, 1, 1)),
                    end=Some(date(2024, 1, 31)),
                )
            )
        )
        results = self._apply_date_filter(date_input)
        self.assertIn(self.incident_jan, results)
        self.assertIn(self.incident_ongoing_jan, results)
        self.assertNotIn(self.incident_jun, results)

    def test_filter_date_exact(self):
        from incident.schema.filters import CalendarIncidentDateFilter

        date_input = CalendarIncidentDateFilter(exact=Some(date(2024, 1, 25)))
        results = self._apply_date_filter(date_input)
        self.assertNotIn(self.incident_jan, results)
        self.assertIn(self.incident_ongoing_jan, results)
        self.assertNotIn(self.incident_jun, results)

    def test_filter_month_exact(self):
        from incident.schema.filters import CalendarIncidentDateFilter, IntExactInput

        date_input = CalendarIncidentDateFilter(
            month=Some(IntExactInput(exact=Some(6)))
        )
        results = self._apply_date_filter(date_input)
        self.assertNotIn(self.incident_jan, results)
        self.assertIn(self.incident_ongoing_jan, results)
        self.assertNotIn(self.incident_jun, results)

    def test_filter_year_exact(self):
        from incident.schema.filters import CalendarIncidentDateFilter, IntExactInput

        incident_2025 = CalendarIncident.objects.create(
            title="Future 2025 incident",
            brief="Runs in 2025",
            severity=CalendarIncidentSeverity.MINOR,
            start_datetime=datetime(2025, 1, 1, 8, 0),
            end_datetime=datetime(2025, 1, 2, 8, 0),
        )
        date_input = CalendarIncidentDateFilter(
            year=Some(IntExactInput(exact=Some(2024)))
        )
        results = self._apply_date_filter(date_input)
        self.assertIn(self.incident_jan, results)
        self.assertIn(self.incident_ongoing_jan, results)
        self.assertIn(self.incident_jun, results)
        self.assertNotIn(incident_2025, results)

    def test_filter_invalid_range_missing_start_raises_error(self):
        from incident.schema.filters import CalendarIncidentDateFilter, DateRangeInput

        date_input = CalendarIncidentDateFilter(
            range=Some(
                DateRangeInput(
                    start=None,
                    end=Some(date(2024, 1, 31)),
                )
            )
        )
        with self.assertRaises(GraphQLError) as ctx:
            self._apply_date_filter(date_input)
        self.assertIn("date range requires both start and end", str(ctx.exception))


class TestFilterDecorators(TestCase):
    """Test that filter decorators are correctly applied."""

    def test_calendar_filter(self):
        """Verify CalendarIncidentFilter has correct strawberry_django decorator."""
        from incident.schema.filters import CalendarIncidentFilter

        self.assertTrue(
            hasattr(CalendarIncidentFilter, "__strawberry_django_definition__"),
            "CalendarIncidentFilter missing strawberry_django decorator",
        )

    def test_vehicle_filter(self):
        """Verify VehicleIncidentFilter has correct strawberry_django decorator."""
        from incident.schema.filters import VehicleIncidentFilter

        self.assertTrue(
            hasattr(VehicleIncidentFilter, "__strawberry_django_definition__"),
            "VehicleIncidentFilter missing strawberry_django decorator",
        )
