import copy
import html
import json
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from dotmap import DotMap
from graphql import GraphQLError
from strawberry.types.maybe import Some

from common.models import Media, User
from incident.enums import (
    CalendarIncidentChronologyIndicator,
    CalendarIncidentSeverity,
    IncidentSeverity,
    IngestPlatform,
    PassengerStatus,
    SocialMediaLinkStatus,
)
from incident.models import (
    CalendarIncident,
    CalendarIncidentCategory,
    CalendarIncidentChronology,
    CalendarIncidentMedia,
    LineStatusReport,
    SocialMediaLink,
    StationIncident,
    VehicleIncident,
)
from incident.services import official_posts
from incident.services.line_status import load_line_status_history
from incident.services.official_posts import (
    RawPost,
    fetch_user_posts,
    get_system_author,
    ingest_posts,
    latest_post_id,
    load_fixture_posts,
)
from incident.services.urls import canonicalize_url
from incident.tasks import TELEGRAM_MAX_TEXT_LENGTH, ingest_official_posts
from operation.models import Line, Station, Vehicle, VehicleType
from rosak.context import ContextLoaders
from rosak.schema import schema
from telegram_provider.enums import MessageDirection
from telegram_provider.models import TelegramLogs, TelegramSocialMediaLinkLog

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_FIXTURE = FIXTURES_DIR / "x_user_tweets_sample.json"

#: Distinguishes "no scripted outcome left" from a scripted ``None`` (a
#: dead-lettered send) in :func:`fake_sender`.
_UNSCRIPTED = object()


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


def fake_sender(outcomes=None):
    """Build an async stand-in for the ``send_message`` the task imported.

    ``async_to_sync`` awaits the *result* of the callable, so the patch target
    must be a coroutine function — a ``MagicMock`` returning a tuple would
    raise ``TypeError: object tuple can't be used in 'await' expression``.
    Each entry of ``outcomes`` is consumed one call at a time: an exception
    instance is raised, ``None`` is a dead-lettered send. Unscripted calls
    succeed and return a real (unsent) ``TelegramLogs`` row alongside a
    message, so the join table can be asserted on for real.
    """
    calls: list[dict] = []
    pending = list(outcomes) if outcomes is not None else None
    ids = count(90000)

    async def sender(**kwargs):
        calls.append(kwargs)
        outcome = pending.pop(0) if pending else _UNSCRIPTED
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is _UNSCRIPTED:
            message = SimpleNamespace(
                message_id=next(ids), chat=SimpleNamespace(id=kwargs["chat_id"])
            )
            # acreate, not create: this body is a coroutine and a synchronous
            # ORM call inside one raises SynchronousOnlyOperation.
            return message, await TelegramLogs.objects.acreate(
                direction=MessageDirection.OUTBOUND,
                payload={"chat_id": kwargs["chat_id"], "text": kwargs["text"]},
            )
        return outcome

    sender.calls = calls
    return sender


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
            indicator=CalendarIncidentChronologyIndicator.GREEN,
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

    def test_station_incident_conditional_unique_constraint_blocks_second_last(self):
        # The constraint only enforces uniqueness for the current (is_last=True)
        # incident, so multiple historical incidents are allowed but a second
        # current one is blocked.
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
            date=date(2026, 1, 3),
            severity=IncidentSeverity.TRIVIA,
            title="Second historical incident",
            brief="Lighting issue",
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
                    date=date(2026, 1, 4),
                    severity=IncidentSeverity.CRITICAL,
                    title="Duplicate last incident",
                    brief="Lift issue",
                    is_last=True,
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

    def test_range_includes_incidents_overlapping_either_boundary(self) -> None:
        from incident.schema.filters import CalendarIncidentDateFilter, DateRangeInput

        # Given incidents ending in, starting in, and spanning the requested window.
        spans = [
            (datetime(2023, 12, 1), datetime(2024, 1, 1)),
            (datetime(2024, 1, 31), datetime(2024, 2, 20)),
            (datetime(2023, 12, 1), datetime(2024, 2, 20)),
            (datetime(2023, 12, 1), None),
        ]
        incidents = [
            CalendarIncident.objects.create(
                title="Overlapping incident",
                brief="Boundary coverage",
                severity=CalendarIncidentSeverity.MINOR,
                start_datetime=start,
                end_datetime=end,
            )
            for start, end in spans
        ]
        # When filtering January, both boundaries are inclusive.
        results = self._apply_date_filter(
            CalendarIncidentDateFilter(
                range=Some(
                    DateRangeInput(
                        start=Some(date(2024, 1, 1)), end=Some(date(2024, 1, 31))
                    )
                )
            )
        )
        # Then every overlapping incident survives, but unrelated history does not.
        for incident in incidents:
            self.assertIn(incident, results)
        self.assertNotIn(self.incident_jun, results)

    def test_graphql_range_with_ongoing_preserves_pinned_incidents(self) -> None:
        result = execute_graphql(
            """
            query CalendarIncidents($filters: CalendarIncidentFilter) {
                calendarIncidents(filters: $filters) { id }
            }
            """,
            variables={
                "filters": {
                    "date": {"range": {"start": "2023-12-18", "end": "2024-01-14"}},
                    "OR": {"ongoing": True},
                }
            },
        )
        self.assertIsNone(result.errors)
        self.assertCountEqual(
            [row["id"] for row in result.data["calendarIncidents"]],
            [str(self.incident_jan.id), str(self.incident_ongoing_jan.id)],
        )

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

    def _apply_ongoing_filter(self, value):
        from incident.schema.filters import CalendarIncidentFilter

        filter_method = vars(CalendarIncidentFilter)["ongoing"]
        q = filter_method(CalendarIncidentFilter(), value=value, prefix="")
        return CalendarIncident.objects.filter(q)

    def test_filter_ongoing_true_matches_only_incidents_without_end_date(self):
        results = self._apply_ongoing_filter(True)
        self.assertIn(self.incident_ongoing_jan, results)
        self.assertNotIn(self.incident_jan, results)
        self.assertNotIn(self.incident_jun, results)

    def test_filter_ongoing_false_matches_only_resolved_incidents(self):
        results = self._apply_ongoing_filter(False)
        self.assertIn(self.incident_jan, results)
        self.assertIn(self.incident_jun, results)
        self.assertNotIn(self.incident_ongoing_jan, results)


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


class SocialMediaLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-sml")
        self.admin_user = User.objects.create(firebase_id="test-admin-sml")

    def test_social_media_link_category_relationship(self):
        from django.contrib.contenttypes.models import ContentType

        from incident.models import SocialMediaLink

        category = CalendarIncidentCategory.objects.get_or_create(
            name="Just Reporting"
        )[0]
        line = Line.objects.create(
            code="TEST_LINE", display_name="Test Line", display_color="#123456"
        )
        station = Station.objects.create(display_name="Test Station")
        v_type = VehicleType.objects.create(
            internal_name="TEST_TYPE", display_name="Test Type"
        )
        vehicle = Vehicle.objects.create(
            identification_no="Set 99", vehicle_type=v_type
        )

        incident = CalendarIncident.objects.create(
            title="Tagged Incident",
            brief="Tagged incident brief",
            severity="MINOR",
            start_datetime=timezone.now(),
        )

        content_type = ContentType.objects.get_for_model(CalendarIncident)
        sml = SocialMediaLink.objects.create(
            url="https://twitter.com/user/status/1234567890",
            title="Twitter post about LRT delay",
            user=self.user,
            content_type=content_type,
            object_id=incident.id,
            completed=True,
            completed_at=timezone.now(),
            completed_by=self.admin_user,
        )

        sml.categories.add(category)
        sml.lines.add(line)
        sml.stations.add(station)
        sml.vehicles.add(vehicle)

        self.assertEqual(sml.content_object, incident)
        self.assertIn(category, sml.categories.all())
        self.assertIn(line, sml.lines.all())
        self.assertIn(station, sml.stations.all())
        self.assertIn(vehicle, sml.vehicles.all())
        self.assertTrue(sml.completed)
        self.assertEqual(sml.completed_by, self.admin_user)
        self.assertIn(sml, self.admin_user.completed_social_media_links.all())

    def test_just_reporting_category_exists(self):
        self.assertTrue(
            CalendarIncidentCategory.objects.filter(name="Just Reporting").exists()
        )

    def test_delete_social_media_link_admin_deletes_another_users_link(self):
        from unittest.mock import patch

        from incident.models import SocialMediaLink

        link = SocialMediaLink.objects.create(
            url="https://twitter.com/user/status/delete-me",
            title="Delete me",
            user=self.user,
        )
        query = """
            mutation DeleteSocialMediaLink($linkId: ID!) {
                deleteSocialMediaLink(socialMediaLinkId: $linkId) {
                    ok
                }
            }
        """
        with patch("rosak.permissions.has_admin_claim", return_value=True):
            result = execute_graphql(
                query,
                variables={"linkId": str(link.id)},
                user=self.admin_user,
            )
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["deleteSocialMediaLink"]["ok"])
        self.assertFalse(SocialMediaLink.objects.filter(pk=link.id).exists())

    def test_delete_social_media_link_requires_admin(self):
        from unittest.mock import patch

        from incident.models import SocialMediaLink

        link = SocialMediaLink.objects.create(
            url="https://twitter.com/user/status/keep-me",
            title="Keep me",
            user=self.user,
        )
        query = """
            mutation DeleteSocialMediaLink($linkId: ID!) {
                deleteSocialMediaLink(socialMediaLinkId: $linkId) {
                    ok
                }
            }
        """
        with patch("rosak.permissions.has_admin_claim", return_value=False):
            result = execute_graphql(
                query,
                variables={"linkId": str(link.id)},
                user=self.user,
            )
        self.assertIsNotNone(result.errors)
        self.assertTrue(SocialMediaLink.objects.filter(pk=link.id).exists())

    def test_submit_social_media_link_title_null_coerced_via_graphql(self):
        from unittest.mock import AsyncMock, patch

        query = """
            mutation SubmitSocialMediaLink($input: SocialMediaLinkInput!) {
                submitSocialMediaLink(input: $input) {
                    ok
                }
            }
        """
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = execute_graphql(
                query,
                variables={
                    "input": {
                        "url": "https://www.facebook.com/groups/developerkaki/permalink/2951657628513464",
                        "title": None,
                        "lineIds": [],
                        "vehicleIds": [],
                        "stationIds": [],
                        "categoryIds": [],
                    }
                },
                user=self.user,
            )
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["submitSocialMediaLink"]["ok"])
        from incident.models import SocialMediaLink

        link = SocialMediaLink.objects.filter(
            url="https://www.facebook.com/groups/developerkaki/permalink/2951657628513464"
        ).first()
        self.assertIsNotNone(link)
        self.assertEqual(link.title, "")

    def test_submit_social_media_link_title_omitted_coerced_via_graphql(self):
        from unittest.mock import AsyncMock, patch

        query = """
            mutation SubmitSocialMediaLink($input: SocialMediaLinkInput!) {
                submitSocialMediaLink(input: $input) {
                    ok
                }
            }
        """
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = execute_graphql(
                query,
                variables={
                    "input": {
                        "url": "https://www.facebook.com/groups/developerkaki/permalink/2951657628513465",
                        "lineIds": [],
                        "vehicleIds": [],
                        "stationIds": [],
                        "categoryIds": [],
                    }
                },
                user=self.user,
            )
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["submitSocialMediaLink"]["ok"])
        from incident.models import SocialMediaLink

        link = SocialMediaLink.objects.filter(
            url="https://www.facebook.com/groups/developerkaki/permalink/2951657628513465"
        ).first()
        self.assertIsNotNone(link)
        self.assertEqual(link.title, "")

    def test_create_calendar_incident_details_null_coerced_via_graphql(self):
        from unittest.mock import patch

        query = """
            mutation CreateCalendarIncident($input: CalendarIncidentInput!) {
                createCalendarIncident(input: $input) {
                    ok
                    id
                }
            }
        """
        with patch(
            "incident.schema.mutations.incidents.has_admin_claim",
            return_value=False,
        ):
            result = execute_graphql(
                query,
                variables={
                    "input": {
                        "title": "Test",
                        "brief": "Test",
                        "details": None,
                        "startDatetime": "2026-08-31T16:33:00.000Z",
                        "endDatetime": None,
                        "severity": "MAJOR",
                        "longTerm": False,
                        "inaccurate": False,
                        "lineIds": [],
                        "vehicleIds": [],
                        "stationIds": [],
                        "chronologies": [],
                    }
                },
                user=self.user,
            )
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["createCalendarIncident"]["ok"])
        incident_id = result.data["createCalendarIncident"]["id"]
        self.assertIsNotNone(incident_id)
        from incident.models import CalendarIncident

        incident = CalendarIncident.objects.get(pk=int(incident_id))
        self.assertEqual(incident.details, "")
        self.assertEqual(incident.title, "Test")
        self.assertEqual(incident.brief, "Test")

    def test_create_calendar_incident_details_omitted_coerced_via_graphql(self):
        from unittest.mock import patch

        query = """
            mutation CreateCalendarIncident($input: CalendarIncidentInput!) {
                createCalendarIncident(input: $input) {
                    ok
                    id
                }
            }
        """
        with patch(
            "incident.schema.mutations.incidents.has_admin_claim",
            return_value=False,
        ):
            result = execute_graphql(
                query,
                variables={
                    "input": {
                        "title": "Test2",
                        "brief": "Test2",
                        "startDatetime": "2026-08-31T16:33:00.000Z",
                        "severity": "MAJOR",
                        "lineIds": [],
                        "vehicleIds": [],
                        "stationIds": [],
                        "chronologies": [],
                    }
                },
                user=self.user,
            )
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["createCalendarIncident"]["ok"])
        incident_id = result.data["createCalendarIncident"]["id"]
        from incident.models import CalendarIncident

        incident = CalendarIncident.objects.get(pk=int(incident_id))
        self.assertEqual(incident.details, "")

    def test_create_calendar_incident_chronology_null_fields_coerced_via_graphql(self):
        from unittest.mock import patch

        query = """
            mutation CreateCalendarIncident($input: CalendarIncidentInput!) {
                createCalendarIncident(input: $input) {
                    ok
                    id
                }
            }
        """
        with patch(
            "incident.schema.mutations.incidents.has_admin_claim",
            return_value=False,
        ):
            result = execute_graphql(
                query,
                variables={
                    "input": {
                        "title": "Chrono Test",
                        "brief": "Chrono brief",
                        "details": "detail",
                        "startDatetime": "2026-08-31T16:33:00.000Z",
                        "severity": "MINOR",
                        "lineIds": [],
                        "vehicleIds": [],
                        "stationIds": [],
                        "chronologies": [
                            {
                                "indicator": "RED",
                                "datetime": None,
                                "sourceUrl": None,
                                "content": None,
                            }
                        ],
                    }
                },
                user=self.user,
            )
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["createCalendarIncident"]["ok"])
        from incident.models import CalendarIncidentChronology

        chrono = CalendarIncidentChronology.objects.filter(
            calendar_incident_id=int(result.data["createCalendarIncident"]["id"])
        ).first()
        self.assertIsNotNone(chrono)
        self.assertEqual(chrono.source_url, "")
        self.assertEqual(chrono.content, "")


class LineStatusHistoryTests(TestCase):
    """Runnable coverage for the service-day history contract."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="history-test-user")
        self.line = Line.objects.create(
            code="HST", display_name="History Test Line", display_color="#008800"
        )

    def test_history_returns_all_24_hours_when_the_line_has_reports(self):
        report = LineStatusReport.objects.create(
            line=self.line, status=PassengerStatus.CROWDED, user=self.user
        )

        buckets = async_to_sync(load_line_status_history)(self.line.id)

        self.assertEqual(len(buckets), 24)
        hour_starts = [bucket.hour_start for bucket in buckets]
        self.assertEqual(hour_starts, sorted(hour_starts))
        # Service day starts at 03:00 and closes at 02:00 next morning.
        self.assertEqual(buckets[0].hour_start.hour, 3)
        self.assertEqual(buckets[-1].hour_start.hour, 2)
        self.assertEqual(
            buckets[-1].hour_end, buckets[-1].hour_start + timedelta(hours=1)
        )
        # Every other hour is zero-filled; the report lands in its own hour.
        report_hour = report.created.replace(minute=0, second=0, microsecond=0)
        self.assertEqual(
            [bucket.count for bucket in buckets if bucket.hour_start == report_hour],
            [1],
        )
        self.assertEqual(
            [
                bucket.dominant_status
                for bucket in buckets
                if bucket.hour_start == report_hour
            ],
            [PassengerStatus.CROWDED],
        )
        self.assertEqual(
            [
                bucket.status_counts
                for bucket in buckets
                if bucket.hour_start == report_hour
            ],
            [{PassengerStatus.CROWDED: 1}],
        )
        self.assertEqual(sum(bucket.count for bucket in buckets), 1)
        self.assertTrue(
            all(
                bucket.status_counts == {}
                for bucket in buckets
                if bucket.hour_start != report_hour
            )
        )

    def test_history_status_counts_break_down_mixed_statuses_in_one_hour(self):
        hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        reports = [
            LineStatusReport.objects.create(
                line=self.line, status=status, user=self.user
            )
            for status in [
                PassengerStatus.DELAYED,
                PassengerStatus.CROWDED,
                PassengerStatus.CROWDED,
            ]
        ]
        for report in reports:
            LineStatusReport.objects.filter(pk=report.pk).update(created=hour)

        buckets = async_to_sync(load_line_status_history)(
            self.line.id, day_start_hour=hour.hour
        )

        self.assertEqual(len(buckets), 24)
        hour_bucket = next(bucket for bucket in buckets if bucket.hour_start == hour)
        # Enum declaration order, not insertion order.
        self.assertEqual(
            hour_bucket.status_counts,
            {PassengerStatus.CROWDED: 2, PassengerStatus.DELAYED: 1},
        )
        self.assertEqual(hour_bucket.count, 3)
        self.assertEqual(sum(hour_bucket.status_counts.values()), hour_bucket.count)
        self.assertEqual(hour_bucket.dominant_status, PassengerStatus.CROWDED)

    def test_graphql_history_exposes_status_counts_in_enum_order(self):
        hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        reports = [
            LineStatusReport.objects.create(
                line=self.line, status=status, user=self.user
            )
            for status in [
                PassengerStatus.DELAYED,
                PassengerStatus.CROWDED,
                PassengerStatus.CROWDED,
            ]
        ]
        for report in reports:
            LineStatusReport.objects.filter(pk=report.pk).update(created=hour)

        result = execute_graphql(
            """
            query($id: ID!, $hour: Int!) {
              lineStatusHistory(lineId: $id, dayStartHour: $hour) {
                count
                statusCounts { status count }
              }
            }
            """,
            variables={"id": str(self.line.id), "hour": hour.hour},
        )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        buckets = result.data["lineStatusHistory"]
        self.assertEqual(len(buckets), 24)
        self.assertEqual(
            buckets[0]["statusCounts"],
            [
                {"status": "CROWDED", "count": 2},
                {"status": "DELAYED", "count": 1},
            ],
        )
        self.assertEqual(buckets[0]["count"], 3)
        self.assertEqual(
            sum(entry["count"] for entry in buckets[0]["statusCounts"]),
            buckets[0]["count"],
        )
        # No-report hours carry count=0 and an empty breakdown.
        self.assertEqual(buckets[1]["count"], 0)
        self.assertEqual(buckets[1]["statusCounts"], [])

    def test_history_is_empty_when_the_line_has_no_reports(self):
        buckets = async_to_sync(load_line_status_history)(self.line.id)

        self.assertEqual(buckets, [])


class PublicFeedContractTests(TestCase):
    """GraphQL contract for the public feed: ``totalCount`` is the whole
    filtered set (cursor-independent) and ``currentServiceDayOnly`` keeps only
    links inside the current service day (03:00 rollover)."""

    query = """
        query Feed($first: Int, $after: String, $currentServiceDayOnly: Boolean) {
            publicSocialMediaLinks(
                first: $first
                after: $after
                currentServiceDayOnly: $currentServiceDayOnly
            ) {
                totalCount
                edges { node { id } cursor }
                pageInfo { hasNextPage endCursor }
            }
        }
    """

    def setUp(self):
        self.user = User.objects.create(firebase_id="feed-contract-user")

    def _link(self, slug, *, created=None):
        from incident.models import SocialMediaLink

        link = SocialMediaLink.objects.create(
            url=f"https://example.com/{slug}", title=slug, user=self.user
        )
        if created is not None:
            SocialMediaLink.objects.filter(id=link.id).update(created=created)
            link.refresh_from_db()
        return link

    def _feed(self, **variables):
        result = execute_graphql(self.query, variables=variables)
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return result.data["publicSocialMediaLinks"]

    def test_total_count_is_the_full_filtered_set_not_the_page(self):
        for index in range(3):
            self._link(f"total-count-{index}")

        page_one = self._feed(first=1)

        self.assertEqual(page_one["totalCount"], 3)
        self.assertEqual(len(page_one["edges"]), 1)
        self.assertTrue(page_one["pageInfo"]["hasNextPage"])

        page_two = self._feed(first=2, after=page_one["pageInfo"]["endCursor"])

        self.assertEqual(page_two["totalCount"], 3)
        self.assertEqual(len(page_two["edges"]), 2)
        self.assertFalse(page_two["pageInfo"]["hasNextPage"])
        first_id = page_one["edges"][0]["node"]["id"]
        second_ids = [edge["node"]["id"] for edge in page_two["edges"]]
        self.assertNotIn(first_id, second_ids)

    def test_current_service_day_only_excludes_previous_day_and_counts_filtered_set(
        self,
    ):
        from incident.services.line_status import service_day_start

        now = timezone.now()
        back_dated = self._link(
            "previous-service-day",
            created=service_day_start(now) - timedelta(minutes=1),
        )
        current = self._link("current-service-day", created=now)

        filtered = self._feed(currentServiceDayOnly=True)

        ids = [edge["node"]["id"] for edge in filtered["edges"]]
        self.assertEqual(ids, [str(current.id)])
        self.assertNotIn(str(back_dated.id), ids)
        self.assertEqual(filtered["totalCount"], 1)

        unfiltered = self._feed(currentServiceDayOnly=False)

        all_ids = [edge["node"]["id"] for edge in unfiltered["edges"]]
        self.assertIn(str(current.id), all_ids)
        self.assertIn(str(back_dated.id), all_ids)
        self.assertEqual(unfiltered["totalCount"], 2)


class LineStatusReportStationsTests(TestCase):
    """``LineStatusReportScalar.stations`` reads the report's station M2M."""

    def setUp(self):
        self.user = User.objects.create(firebase_id="report-stations-user")
        self.line = Line.objects.create(
            code="RST", display_name="Report Stations Line", display_color="#990000"
        )
        self.station = Station.objects.create(display_name="KLCC")

    def test_stations_lists_attached_station_and_empty_list_when_none(self):
        tagged = LineStatusReport.objects.create(
            line=self.line, status=PassengerStatus.CROWDED, user=self.user
        )
        tagged.stations.add(self.station)
        untagged = LineStatusReport.objects.create(
            line=self.line, status=PassengerStatus.NORMAL, user=self.user
        )

        result = execute_graphql(
            """
            query Reports($lineId: ID!) {
                lineStatusReports(lineId: $lineId) {
                    edges { node { id stations { id displayName } } }
                }
            }
            """,
            variables={"lineId": str(self.line.id)},
        )
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")

        stations_by_report = {
            edge["node"]["id"]: edge["node"]["stations"]
            for edge in result.data["lineStatusReports"]["edges"]
        }
        self.assertEqual(
            stations_by_report[str(tagged.id)],
            [{"id": str(self.station.id), "displayName": "KLCC"}],
        )
        self.assertEqual(stations_by_report[str(untagged.id)], [])


class OfficialPostFixtureParsingTests(TestCase):
    """Spec 4.8.1 — a saved API payload maps to RawPost without a token."""

    def test_saved_payload_yields_verbatim_text_posted_at_and_permalink(self):
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))

        self.assertEqual(len(posts), 2)
        first = posts[0]
        self.assertEqual(first.platform, IngestPlatform.X)
        self.assertEqual(first.handle, "askrapidkl")
        self.assertEqual(first.post_id, "1791552310047416320")
        self.assertEqual(
            first.url,
            "https://x.com/askrapidkl/status/1791552310047416320",
        )
        # Verbatim means byte-for-byte: compare against the file's own bytes, not
        # a hand-copied literal that could drift from the fixture.
        saved = json.loads(SAMPLE_FIXTURE.read_text(encoding="utf-8"))["data"]
        self.assertEqual(first.text, saved[0]["text"])
        self.assertIn("Gangguan di LRT Aliran Utama", first.text)
        self.assertEqual(
            first.posted_at,
            datetime(2026, 9, 26, 3, 15, tzinfo=UTC),
        )
        self.assertEqual(
            posts[1].url,
            "https://x.com/askrapidkl/status/1791552408821972992",
        )
        self.assertEqual(
            posts[1].posted_at, datetime(2026, 9, 26, 5, 42, 31, tzinfo=UTC)
        )

    def test_has_media_reflects_the_payload_and_raw_is_kept_untouched(self):
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))

        self.assertTrue(posts[0].has_media)
        self.assertFalse(posts[1].has_media)
        self.assertEqual(posts[0].raw["public_metrics"]["like_count"], 226)

    def test_unknown_fixture_path_raises_a_sanitized_fetch_error(self):
        with self.assertRaises(official_posts.OfficialPostFetchError) as caught:
            load_fixture_posts("/nonexistent-official-posts.json")

        self.assertIn("could not be read", str(caught.exception))


class OfficialPostIngestTests(TestCase):
    """Idempotency, cross-account dedup and the field mapping (4.8.2 – 4.8.4)."""

    def setUp(self):
        # The system author is seeded by migration 0027's data migration; a
        # missing seed must fail loudly, so this is not mocked.
        self.author = get_system_author()
        self.posts = load_fixture_posts(str(SAMPLE_FIXTURE))

    def test_same_posts_twice_yield_one_row_each_and_no_second_creation(self):
        first = ingest_posts(self.posts, handle="askrapidkl", author=self.author)

        self.assertEqual(first.fetched, 2)
        self.assertEqual(first.created, 2)
        self.assertEqual(first.skipped, 0)
        self.assertEqual(first.duplicate_urls, 0)
        self.assertEqual(len(first.created_ids), 2)

        second = ingest_posts(self.posts, handle="askrapidkl", author=self.author)

        self.assertEqual(second.created, 0)
        self.assertEqual(second.skipped, 2)
        self.assertEqual(second.created_ids, ())
        self.assertEqual(
            SocialMediaLink.objects.filter(platform=IngestPlatform.X).count(), 2
        )

    def test_same_url_under_a_second_handle_is_a_duplicate_url_not_a_twin(self):
        ingest_posts(self.posts, handle="askrapidkl", author=self.author)
        existing = SocialMediaLink.objects.get(post_id=self.posts[0].post_id)

        # Same permalink, arriving attributed to the other tracked account with a
        # different post_id: post-id dedup alone would let it through, so the
        # normalized_url check is what stops the twin.
        # A post_id the store has never seen, so the (platform, post_id) check
        # passes and the normalized_url check is what has to catch it.
        cross_account = RawPost(
            platform=IngestPlatform.X,
            post_id="1791552500000000001",
            handle="myrapidkl",
            text=self.posts[0].text,
            posted_at=self.posts[0].posted_at,
            url=self.posts[0].url,
            has_media=False,
            raw={"id": "1791552500000000001"},
        )

        summary = ingest_posts([cross_account], handle="myrapidkl", author=self.author)

        self.assertEqual(summary.duplicate_urls, 1)
        self.assertEqual(summary.created, 0)
        self.assertEqual(SocialMediaLink.objects.count(), 2)
        # The existing row is left alone: not rewritten, not re-attributed.
        existing.refresh_from_db()
        self.assertEqual(existing.source_handle, "askrapidkl")
        self.assertEqual(existing.post_id, self.posts[0].post_id)

    def test_row_is_verbatim_mapped_and_pending_approval(self):
        # Long text so the CharField(256) title truncation is observable while
        # description keeps every character.
        bm_text = "⚠️ Gangguan di LRT Aliran Utama.\n\n" + "per MSI " * 80
        posted_at = datetime(2024, 5, 1, 8, 30, tzinfo=UTC)
        post = RawPost(
            platform=IngestPlatform.X,
            post_id="1791552310047416320",
            handle="askrapidkl",
            text=bm_text,
            posted_at=posted_at,
            url="https://x.com/askrapidkl/status/1791552310047416320",
            has_media=True,
            raw={"id": "1791552310047416320", "text": bm_text},
        )

        ingest_posts([post], handle="askrapidkl", author=self.author)

        link = SocialMediaLink.objects.get(platform=IngestPlatform.X)
        self.assertEqual(link.description, bm_text)
        self.assertEqual(link.title, bm_text[:256])
        self.assertEqual(len(link.title), 256)
        self.assertIs(link.is_automated, True)
        self.assertEqual(link.status, SocialMediaLinkStatus.PENDING_APPROVAL)
        self.assertEqual(link.user, self.author)
        # USE_TZ=False, so the aware input is stored as naive local time.
        self.assertEqual(link.posted_at, timezone.make_naive(posted_at))
        # posted_at is post time; created is ingest time.
        self.assertNotEqual(link.posted_at, link.created)
        self.assertEqual(link.source_handle, "askrapidkl")
        self.assertEqual(link.post_id, "1791552310047416320")
        self.assertEqual(link.raw_payload, post.raw)
        self.assertEqual(
            link.normalized_url,
            canonicalize_url("https://x.com/askrapidkl/status/1791552310047416320"),
        )

    def test_latest_post_id_returns_the_highest_numeric_snowflake(self):
        self.assertIsNone(latest_post_id("askrapidkl"))
        ingest_posts(self.posts, handle="askrapidkl", author=self.author)

        # The fixture's newest id is numerically the larger one, and a plain
        # lexicographic Max() would pick the smaller.
        self.assertEqual(latest_post_id("askrapidkl"), "1791552408821972992")
        self.assertIsNone(latest_post_id("myrapidkl"))

    def test_dry_run_counts_creations_but_writes_nothing(self):
        summary = ingest_posts(
            self.posts, handle="askrapidkl", author=self.author, dry_run=True
        )

        self.assertEqual(summary.fetched, 2)
        self.assertEqual(summary.created, 2)
        self.assertEqual(summary.created_ids, ())
        self.assertEqual(SocialMediaLink.objects.count(), 0)


class OfficialPostTaskGuardTests(TestCase):
    """The two env guards (4.8.5) — no request, no row, no crash."""

    @override_settings(OFFICIAL_POST_INGESTION_ENABLED=False, X_API_BEARER_TOKEN="t")
    def test_disabled_flag_makes_no_request_and_writes_nothing(self):
        with (
            # _get_json is the service module's only HTTP seam and
            # fetch_user_posts is what the task resolves it through; both are
            # asserted untouched.
            mock.patch.object(
                official_posts, "_get_json", side_effect=AssertionError("HTTP called")
            ) as get_json,
            mock.patch(
                "incident.tasks.fetch_user_posts",
                side_effect=AssertionError("fetch called"),
            ) as fetch,
            self.assertLogs("incident.tasks", level="INFO") as logs,
        ):
            result = ingest_official_posts()

        self.assertEqual(result, {"skipped": "disabled"})
        fetch.assert_not_called()
        get_json.assert_not_called()
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.assertTrue(any("disabled" in line for line in logs.output))

    @override_settings(OFFICIAL_POST_INGESTION_ENABLED=True, X_API_BEARER_TOKEN="")
    def test_enabled_without_a_token_is_a_clean_no_op(self):
        with (
            mock.patch.object(
                official_posts, "_get_json", side_effect=AssertionError("HTTP called")
            ) as get_json,
            mock.patch(
                "incident.tasks.fetch_user_posts",
                side_effect=AssertionError("fetch called"),
            ) as fetch,
            self.assertLogs("incident.tasks", level="WARNING") as logs,
        ):
            result = ingest_official_posts()

        self.assertEqual(result, {"skipped": "no_token"})
        get_json.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.assertTrue(any("X_API_BEARER_TOKEN" in line for line in logs.output))

    @override_settings(
        OFFICIAL_POST_INGESTION_ENABLED=True,
        X_API_BEARER_TOKEN="t",
        OFFICIAL_POST_HANDLES=["askrapidkl", "myrapidkl"],
    )
    def test_one_handle_failing_does_not_stop_the_others(self):
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))

        with mock.patch(
            "incident.tasks.fetch_user_posts",
            side_effect=[
                official_posts.OfficialPostFetchError("X API error: HTTP 429"),
                posts,
            ],
        ) as fetch:
            result = ingest_official_posts()

        # The error reason is sanitized upstream, so it is safe to log and return.
        failed = result["handles"]["askrapidkl"]
        self.assertEqual(failed["error"], "X API error: HTTP 429")
        self.assertEqual(failed["created"], 0)
        self.assertIn("duration_ms", failed)
        # The other handle still ran and still wrote its rows.
        self.assertNotIn("error", result["handles"]["myrapidkl"])
        self.assertEqual(result["handles"]["myrapidkl"]["created"], 2)
        self.assertEqual(result["created"], 2)
        self.assertEqual(fetch.call_count, 2)
        # since_id is the incremental filter, read from that handle's own rows.
        self.assertIsNone(fetch.call_args_list[0].kwargs["since_id"])
        self.assertEqual(SocialMediaLink.objects.count(), 2)


class OfficialPostBoundedFetchTests(TestCase):
    """The pagination walk is bounded by ``limit`` *and* by a page cap (4.8.6)."""

    def setUp(self):
        # The user-id lookup is cached under a namespaced key; a cache hit would
        # skip the first call and change what the side_effect chain means.
        cache.clear()
        self.addCleanup(cache.clear)

    def _paged_api(self, posts_per_page, pages):
        """A _get_json stand-in: one user lookup, then ``pages`` tweet pages."""

        def fake_get_json(url, *, params, headers, context):
            if "by/username" in url:
                return {"data": {"id": "424242"}}
            index = fake_get_json.calls
            fake_get_json.calls += 1
            if index >= pages:
                return {"data": []}
            start = index * posts_per_page
            data = [
                {
                    "id": str(1791552310047416320 + start + offset),
                    "text": f"post {start + offset}",
                    "created_at": "2026-09-26T03:15:00.000Z",
                }
                for offset in range(posts_per_page)
            ]
            # Every page but the last carries a token, so only the caps stop the
            # walk — that is what the assertions below prove.
            payload = {"data": data, "meta": {"result_count": len(data)}}
            if index < pages - 1:
                payload["meta"]["next_token"] = f"token-{index}"
            return payload

        fake_get_json.calls = 0
        return fake_get_json

    def _tweet_pages(self, http):
        """The tweets-endpoint calls among a patched ``_get_json``'s calls."""
        return [call for call in http.call_args_list if "tweets" in call.args[0]]

    def test_walk_stops_at_limit_across_pages(self):
        with mock.patch.object(
            official_posts, "_get_json", side_effect=self._paged_api(2, pages=10)
        ) as http:
            posts = fetch_user_posts("askrapidkl", limit=3)
            pages = self._tweet_pages(http)

        # limit=3 over 2-post pages: the second page is truncated, not a third
        # request.
        self.assertEqual(len(posts), 3)
        self.assertEqual(len(pages), 2)
        # max_results never exceeds what is still outstanding.
        self.assertEqual(pages[0].kwargs["params"]["max_results"], 3)
        self.assertEqual(pages[1].kwargs["params"]["max_results"], 1)
        self.assertEqual(pages[1].kwargs["params"]["pagination_token"], "token-0")

    def test_walk_stops_at_the_hard_page_cap_not_at_exhaustion(self):
        with mock.patch.object(
            official_posts, "_get_json", side_effect=self._paged_api(1, pages=10_000)
        ) as http:
            posts = fetch_user_posts("askrapidkl", limit=10_000)
            pages = self._tweet_pages(http)

        # Every page carries a next_token, so only the cap stops the walk.
        self.assertEqual(len(pages), official_posts._MAX_PAGES)
        self.assertEqual(len(posts), official_posts._MAX_PAGES)

    def test_since_id_start_time_and_end_time_reach_the_request(self):
        captured = []

        def fake_get_json(url, *, params, headers, context):
            captured.append((url, dict(params), dict(headers)))
            if "by/username" in url:
                return {"data": {"id": "424242"}}
            return {"data": []}

        with mock.patch.object(official_posts, "_get_json", side_effect=fake_get_json):
            fetch_user_posts(
                "askrapidkl",
                since_id="1791552310047416320",
                start_time=datetime(2026, 9, 1, tzinfo=UTC),
                end_time=datetime(2026, 9, 2, 23, 59, 59, tzinfo=UTC),
                limit=5,
                exclude_retweets=True,
            )

        tweets_url, params, headers = captured[-1]
        self.assertIn("/2/users/424242/tweets", tweets_url)
        self.assertEqual(params["since_id"], "1791552310047416320")
        self.assertEqual(params["start_time"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(params["end_time"], "2026-09-02T23:59:59+00:00")
        self.assertEqual(params["exclude"], "retweets")
        self.assertEqual(params["max_results"], 5)
        self.assertEqual(headers["Authorization"], "Bearer ")

    # DEBUG=True swaps the default cache for DummyCache (AGENTS.md "local-vs-prod
    # gotcha"), which discards every write — so the cache assertion below needs a
    # real backend to mean anything.
    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "official-post-tests",
            }
        }
    )
    def test_user_id_is_resolved_once_per_handle(self):
        # The second call is served entirely from the cache, so the lookup does
        # not happen again — one extra HTTP request per account, not per tick.
        api = self._paged_api(1, pages=1)
        with mock.patch.object(official_posts, "_get_json", side_effect=api) as http:
            fetch_user_posts("askrapidkl", limit=1)
            fetch_user_posts("askrapidkl", limit=1)
            looked_up = [
                call for call in http.call_args_list if "by/username" in call.args[0]
            ]
            pages = self._tweet_pages(http)

        self.assertEqual(len(looked_up), 1)
        # One tweets page per call, so the cached id was reused instead of a
        # second username lookup — but the page fetch itself still happens.
        self.assertEqual(len(pages), 2)


class OfficialPostNotificationTests(TestCase):
    """Phase 2 egress: one admin notification per newly ingested row (5.5).

    The seam patched is ``incident.tasks.send_message`` — the symbol the task
    imported — so no Telegram call is ever attempted. ``TELEGRAM_ADMIN_CHAT_ID``
    defaults to a real-looking id here; the one test that must not notify
    blanks it.
    """

    def setUp(self):
        self.author = get_system_author()
        self.posts = load_fixture_posts(str(SAMPLE_FIXTURE))
        self.addCleanup(cache.clear)

    def _ingest(self, sender=None, *, posts=None, **extra_settings):
        """Run the beat task with HTTP stubbed; ``sender=None`` uses the real
        ``send_message`` (only the PTB application is then faked)."""
        task_settings = {
            "OFFICIAL_POST_INGESTION_ENABLED": True,
            "X_API_BEARER_TOKEN": "t",
            "OFFICIAL_POST_HANDLES": ["askrapidkl"],
            "TELEGRAM_ADMIN_CHAT_ID": "-1001234",
            **extra_settings,
        }
        with ExitStack() as stack:
            stack.enter_context(override_settings(**task_settings))
            stack.enter_context(
                mock.patch(
                    "incident.tasks.fetch_user_posts",
                    return_value=self.posts if posts is None else posts,
                )
            )
            if sender is not None:
                stack.enter_context(mock.patch("incident.tasks.send_message", sender))
            return ingest_official_posts()

    @staticmethod
    def _notified(result):
        """How many notifications went out for the single tracked handle.

        ``notified`` is a per-handle stat; the task's top-level totals only sum
        ``INGEST_COUNTERS``, so it is read from the handle's own entry.
        """
        return result["handles"]["askrapidkl"]["notified"]

    def test_fires_once_per_new_link_and_never_for_a_re_scrape(self):
        sender = fake_sender()

        first = self._ingest(sender)

        self.assertEqual(first["created"], 2)
        self.assertEqual(self._notified(first), 2)
        self.assertEqual(len(sender.calls), 2)
        for call in sender.calls:
            self.assertEqual(call["chat_id"], "-1001234")
            self.assertEqual(call["parse_mode"], "HTML")
            self.assertIs(call["return_log"], True)

        second = self._ingest(sender)

        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 2)
        self.assertEqual(self._notified(second), 0)
        # Unchanged: a re-scrape is silent, it never re-notifies.
        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(TelegramSocialMediaLinkLog.objects.count(), 2)

    def test_message_carries_handle_time_verbatim_text_permalink_and_console_url(self):
        sender = fake_sender()
        self._ingest(sender)

        link = SocialMediaLink.objects.get(post_id=self.posts[0].post_id)
        text = sender.calls[0]["text"]

        self.assertIn("@askrapidkl", text)
        # The post's own time, rendered from posted_at — not the ingest time.
        self.assertIn(f"{link.posted_at:%Y-%m-%d %H:%M}", text)
        self.assertIn(link.url, text)
        self.assertIn(f"{settings.FRONTEND_BASE_URL}/console/insiden/links", text)
        # Verbatim text, HTML-escaped (the fixture contains a bare `&`).
        self.assertIn(html.escape(link.description, quote=False), text)
        # Never the provider blob.
        self.assertNotIn("public_metrics", text)

    def test_dynamic_values_are_html_escaped_for_telegram(self):
        # Telegram's HTML parser rejects &quot; / &#x27; outright, so quote
        # escaping must stay off while the markup characters are escaped.
        nasty = '<b>bold</b> & "quoted" <script>alert(1)</script>'
        post = RawPost(
            platform=IngestPlatform.X,
            post_id="1791552500000000002",
            handle="askrapidkl",
            text=nasty,
            posted_at=datetime(2026, 9, 26, 5, 0, tzinfo=UTC),
            url="https://x.com/askrapidkl/status/1791552500000000002",
            has_media=False,
            raw={"id": "1791552500000000002", "text": nasty},
        )
        sender = fake_sender()

        self._ingest(sender, posts=[post])

        text = sender.calls[0]["text"]
        self.assertNotIn("<script>", text)
        self.assertNotIn("<b>bold</b>", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertIn("&amp; ", text)
        self.assertIn('"quoted"', text)
        self.assertNotIn("&quot;", text)

    def test_a_long_post_is_truncated_to_fit_telegrams_limit(self):
        long_text = "Gangguan laluan utama. " * 400
        post = RawPost(
            platform=IngestPlatform.X,
            post_id="1791552500000000003",
            handle="askrapidkl",
            text=long_text,
            posted_at=datetime(2026, 9, 26, 5, 0, tzinfo=UTC),
            url="https://x.com/askrapidkl/status/1791552500000000003",
            has_media=False,
            raw={"id": "1791552500000000003"},
        )
        sender = fake_sender()

        self._ingest(sender, posts=[post])

        text = sender.calls[0]["text"]
        self.assertLessEqual(len(text), TELEGRAM_MAX_TEXT_LENGTH)
        # Truncated, and honest about being truncated; the actionable tail
        # (permalink + console link) survives.
        self.assertIn("…[truncated]", text)
        self.assertTrue(text.endswith("to publish it."))
        self.assertIn(post.url, text)

    def test_no_notification_and_no_join_row_when_admin_chat_id_is_empty(self):
        sender = fake_sender()

        result = self._ingest(sender, TELEGRAM_ADMIN_CHAT_ID="")

        self.assertEqual(result["created"], 2)
        self.assertEqual(self._notified(result), 0)
        self.assertEqual(sender.calls, [])
        self.assertEqual(TelegramSocialMediaLinkLog.objects.count(), 0)

    def test_a_dead_lettered_send_does_not_abort_the_remaining_notifications(self):
        sender = fake_sender(outcomes=[None])

        result = self._ingest(sender)

        self.assertEqual(result["created"], 2)
        self.assertEqual(self._notified(result), 1)
        self.assertEqual(len(sender.calls), 2)
        # Only the delivered one is joinable, so /approve can only find that one.
        self.assertEqual(TelegramSocialMediaLinkLog.objects.count(), 1)

    def test_a_raising_send_is_contained_and_logged_sanitized(self):
        sender = fake_sender(
            outcomes=[RuntimeError("bot down"), RuntimeError("bot down")]
        )

        with self.assertLogs("incident.tasks", level="WARNING") as logs:
            result = self._ingest(sender)

        self.assertEqual(result["created"], 2)
        self.assertEqual(self._notified(result), 0)
        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(TelegramSocialMediaLinkLog.objects.count(), 0)
        self.assertTrue(any("bot down" in line for line in logs.output))
        # The failure is per link, not per handle: the rows still exist.
        self.assertEqual(SocialMediaLink.objects.count(), 2)

    def test_the_join_row_is_found_by_the_lookup_approve_performs(self):
        """End to end over the real seam: the stamp ``send_message`` writes is
        exactly what ``handlers.approve`` filters on, so replying ``/approve``
        to the notification resolves the link."""
        message_id = 90210
        bot = AsyncMock()
        bot.bot.send_message = AsyncMock(
            return_value=SimpleNamespace(
                message_id=message_id, chat=SimpleNamespace(id=-1001234)
            )
        )

        # No sender patched: the real send_message runs, and only the PTB
        # application is faked. async_to_sync from sync code keeps the async ORM
        # writes on this thread's connection, inside the TestCase transaction.
        with patch(
            "telegram_provider.utils.get_ptb_application",
            new_callable=AsyncMock,
            return_value=bot,
        ):
            result = self._ingest()

        self.assertEqual(self._notified(result), 2)
        logs = TelegramLogs.objects.filter(direction=MessageDirection.OUTBOUND)
        self.assertEqual(logs.count(), 2)
        first_log = logs.order_by("id").first()
        self.assertEqual(
            first_log.payload["message"],
            {"message_id": message_id, "chat": {"id": -1001234}},
        )

        link = SocialMediaLink.objects.get(post_id=self.posts[0].post_id)
        join = TelegramSocialMediaLinkLog.objects.get(social_media_link=link)
        self.assertEqual(join.telegram_log_id, first_log.id)

        # Byte-for-byte the filter telegram_provider.handlers.approve applies.
        resolved = TelegramSocialMediaLinkLog.objects.filter(
            telegram_log__payload__message__message_id=message_id,
            telegram_log__payload__message__chat__id=-1001234,
        ).first()
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.social_media_link_id, link.id)
        # message_id alone is not enough — the handler is chat-scoped.
        self.assertFalse(
            TelegramSocialMediaLinkLog.objects.filter(
                telegram_log__payload__message__message_id=message_id,
                telegram_log__payload__message__chat__id=1,
            ).exists()
        )


class PublicFeedApprovalGateTests(TestCase):
    """Auto-ingested posts are gated on approval; community links are not (5.4)."""

    query = """
        query Feed($first: Int) {
            publicSocialMediaLinks(first: $first) {
                totalCount
                edges { node { id } }
            }
        }
    """

    def setUp(self):
        self.community_author = User.objects.create(firebase_id="feed-gate-community")
        self.system_author = get_system_author()

    def _link(self, slug, *, user=None, **kwargs):
        return SocialMediaLink.objects.create(
            url=f"https://example.com/{slug}",
            title=slug,
            user=user or self.community_author,
            **kwargs,
        )

    def _feed(self, **variables):
        result = execute_graphql(self.query, variables=variables)
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return result.data["publicSocialMediaLinks"]

    def test_pending_auto_posts_are_hidden_and_everything_else_still_surfaces(self):
        hidden = self._link(
            "auto-pending",
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
            is_automated=True,
            user=self.system_author,
        )
        live_auto = self._link(
            "auto-live",
            status=SocialMediaLinkStatus.LIVE,
            is_automated=True,
            user=self.system_author,
        )
        community_pending = self._link(
            "community-pending", status=SocialMediaLinkStatus.PENDING_APPROVAL
        )
        community_live = self._link("community-live", status=SocialMediaLinkStatus.LIVE)

        feed = self._feed()

        ids = [edge["node"]["id"] for edge in feed["edges"]]
        self.assertNotIn(str(hidden.id), ids)
        self.assertIn(str(live_auto.id), ids)
        # Community links keep today's behaviour: pending is still public.
        self.assertIn(str(community_pending.id), ids)
        self.assertIn(str(community_live.id), ids)
        # totalCount counts the filtered set, not the unfiltered table.
        self.assertEqual(feed["totalCount"], 3)
        self.assertEqual(SocialMediaLink.objects.count(), 4)

    def test_an_explicit_status_filter_cannot_resurrect_a_pending_auto_post(self):
        self._link(
            "auto-pending",
            status=SocialMediaLinkStatus.PENDING_APPROVAL,
            is_automated=True,
            user=self.system_author,
        )

        query = """
            query Feed($status: SocialMediaLinkStatus) {
                publicSocialMediaLinks(first: 10, status: $status) {
                    totalCount
                    edges { node { id } }
                }
            }
        """
        result = execute_graphql(
            query, variables={"status": "PENDING_APPROVAL"}, user=None
        )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        feed = result.data["publicSocialMediaLinks"]
        self.assertEqual(feed["edges"], [])
        self.assertEqual(feed["totalCount"], 0)


class IngestOfficialPostsCommandTests(TestCase):
    """The manual backfill command (4.8.7)."""

    def setUp(self):
        self.author = get_system_author()

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command("ingest_official_posts", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_fixture_imports_posts_and_reports_the_summary(self):
        out, _ = self._run("--fixture", str(SAMPLE_FIXTURE))

        self.assertIn("handle=askrapidkl", out)
        self.assertIn("fetched=2", out)
        self.assertIn("created=2", out)
        self.assertIn("skipped=0", out)
        self.assertIn("duplicate_urls=0", out)
        self.assertIn("dry_run=False", out)
        self.assertEqual(
            SocialMediaLink.objects.filter(
                platform=IngestPlatform.X, status=SocialMediaLinkStatus.PENDING_APPROVAL
            ).count(),
            2,
        )

    def test_rerunning_the_same_fixture_is_idempotent(self):
        self._run("--fixture", str(SAMPLE_FIXTURE))
        out, _ = self._run("--fixture", str(SAMPLE_FIXTURE))

        self.assertIn("created=0", out)
        self.assertIn("skipped=2", out)
        self.assertEqual(SocialMediaLink.objects.count(), 2)

    def test_dry_run_writes_nothing(self):
        out, _ = self._run("--fixture", str(SAMPLE_FIXTURE), "--dry-run")

        self.assertIn("dry_run=True", out)
        self.assertIn("created=2", out)
        self.assertEqual(SocialMediaLink.objects.count(), 0)

    def test_unknown_fixture_path_raises_command_error(self):
        with self.assertRaises(CommandError) as caught:
            self._run("--fixture", "/nonexistent-official-posts.json")

        self.assertIn("could not be read", str(caught.exception))

    def test_several_handles_with_one_fixture_is_refused(self):
        with self.assertRaises(CommandError) as caught:
            self._run(
                "--handle",
                "askrapidkl",
                "--handle",
                "myrapidkl",
                "--fixture",
                str(SAMPLE_FIXTURE),
            )

        self.assertIn("cannot be attributed to", str(caught.exception))

    def test_explicit_handle_overrides_the_fixture_sidecar(self):
        out, _ = self._run("--handle", "myrapidkl", "--fixture", str(SAMPLE_FIXTURE))

        self.assertIn("handle=myrapidkl", out)
        links = SocialMediaLink.objects.order_by("post_id")
        self.assertEqual(links.count(), 2)
        for link in links:
            self.assertEqual(link.source_handle, "myrapidkl")
            # The permalink follows the handle it was attributed to, even though
            # the payload's sidecar key said otherwise.
            self.assertIn("/myrapidkl/status/", link.url)

    def test_limit_caps_a_fixture(self):
        out, _ = self._run("--fixture", str(SAMPLE_FIXTURE), "--limit", "1")

        self.assertIn("fetched=1", out)
        self.assertEqual(SocialMediaLink.objects.count(), 1)

    def test_fixture_rejects_a_window(self):
        with self.assertRaises(CommandError) as caught:
            self._run("--fixture", str(SAMPLE_FIXTURE), "--since", "2026-09-01")

        self.assertIn("cannot be combined with --fixture", str(caught.exception))

    def test_malformed_date_raises_command_error(self):
        with self.assertRaises(CommandError) as caught:
            self._run("--since", "01-09-2026")

        self.assertIn("YYYY-MM-DD", str(caught.exception))

    def test_window_bounds_are_whole_utc_days(self):
        command = self._call_command_class()

        self.assertEqual(
            command._parse_date("2026-09-01", "--since"),
            datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            command._parse_date("2026-09-02", "--until", end_of_day=True),
            datetime(2026, 9, 2, 23, 59, 59, 999999, tzinfo=UTC),
        )

    def test_until_before_since_is_refused(self):
        with self.assertRaises(CommandError) as caught:
            self._run("--since", "2026-09-05", "--until", "2026-09-01")

        self.assertIn("is before", str(caught.exception))

    @override_settings(X_API_BEARER_TOKEN="t")
    def test_live_fetch_failure_raises_command_error_and_sanitizes(self):
        with (
            mock.patch.object(
                official_posts,
                "_get_json",
                side_effect=official_posts.OfficialPostFetchError(
                    "X API error: HTTP 401"
                ),
            ),
            self.assertRaises(CommandError) as caught,
        ):
            self._run("--handle", "askrapidkl", "--since", "2026-09-01")

        self.assertIn("HTTP 401", str(caught.exception))
        self.assertEqual(SocialMediaLink.objects.count(), 0)

    @override_settings(X_API_BEARER_TOKEN="t")
    def test_windowed_live_run_uses_start_end_time_and_warns_on_the_api_window(self):
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))
        with mock.patch.object(
            official_posts, "fetch_user_posts", return_value=posts
        ) as fetch:
            out, err = self._run(
                "--handle",
                "askrapidkl",
                "--since",
                "2020-01-01",
                "--until",
                "2020-01-31",
            )

        # A windowed run must not also pass since_id: the API window is the
        # limit, and asking for both is how a backfill silently under-fetches.
        self.assertEqual(
            fetch.call_args.kwargs["start_time"], datetime(2020, 1, 1, tzinfo=UTC)
        )
        self.assertEqual(
            fetch.call_args.kwargs["end_time"],
            datetime(2020, 1, 31, 23, 59, 59, 999999, tzinfo=UTC),
        )
        self.assertNotIn("since_id", fetch.call_args.kwargs)
        self.assertIn("created=2", out)
        # The oldest post the endpoint returned is still newer than --since.
        self.assertIn("3,200 posts", err)

    def test_reachable_window_prints_no_limit_warning(self):
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))
        with mock.patch.object(official_posts, "fetch_user_posts", return_value=posts):
            # The window starts after every post the endpoint served, so nothing
            # older than --since exists and there is nothing to warn about.
            _, err = self._run(
                "--handle",
                "askrapidkl",
                "--since",
                "2026-09-27",
                "--until",
                "2026-09-28",
            )

        self.assertEqual(err, "")

    def test_empty_window_warns_that_the_api_window_is_the_limit(self):
        with mock.patch.object(official_posts, "fetch_user_posts", return_value=[]):
            out, err = self._run(
                "--handle",
                "askrapidkl",
                "--since",
                "2019-01-01",
                "--until",
                "2019-12-31",
            )

        self.assertIn("created=0", out)
        self.assertIn("served no post for this window", err)
        self.assertIn("3,200 posts", err)

    def _call_command_class(self):
        from incident.management.commands.ingest_official_posts import Command

        return Command()
