import base64
import copy
import csv
import html
import json
import os
import sys
import tempfile
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from itertools import count
from pathlib import Path
from types import GeneratorType, SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from celery.schedules import crontab
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, modify_settings, override_settings
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
from incident.services.errors import OfficialPostFetchError
from incident.services.line_status import load_line_status_history
from incident.services.official_posts import (
    RawPost,
    fetch_user_posts,
    get_system_author,
    ingest_posts,
    latest_post_id,
    load_fixture_posts,
    resolve_handle_for_user_id,
)
from incident.services.urls import canonicalize_url
from incident.services.x_webhooks import (
    crc_response_token,
    has_signing_secret,
    ingest_webhook_payload,
    sign_body,
    verify_webhook_signature,
)
from incident.tasks import (
    TELEGRAM_MAX_TEXT_LENGTH,
    ingest_official_posts,
    notify_official_post_links,
)
from operation.models import Line, Station, Vehicle, VehicleType
from rosak.celery import official_post_polling_entry
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
    """The env guards (master flag, opt-in polling, token) — no request, no
    row, no crash."""

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

    @override_settings(
        OFFICIAL_POST_INGESTION_ENABLED=True,
        OFFICIAL_POST_POLLING_ENABLED=True,
        X_API_BEARER_TOKEN="",
    )
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
        OFFICIAL_POST_POLLING_ENABLED=True,
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


class OfficialPostPollingDisabledTests(TestCase):
    """Polling is opt-in (4.6) — OFFICIAL_POST_POLLING_ENABLED already ships
    false, so the beat task must refuse to run even with the master flag on and
    a token set. No request, no row, no crash."""

    @override_settings(
        OFFICIAL_POST_INGESTION_ENABLED=True,
        OFFICIAL_POST_POLLING_ENABLED=False,
        X_API_BEARER_TOKEN="t",
    )
    def test_polling_disabled_no_ops_even_with_a_token_and_the_master_on(self):
        with (
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

        self.assertEqual(result, {"skipped": "polling_disabled"})
        fetch.assert_not_called()
        get_json.assert_not_called()
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.assertTrue(any("polling" in line for line in logs.output))


class OfficialPostPollingEntryTests(TestCase):
    """The opt-in beat entry builder in rosak/celery.py. Reads the live setting
    at call time, so override_settings covers both branches without reloading
    the module."""

    @override_settings(OFFICIAL_POST_POLLING_ENABLED=False)
    def test_off_means_no_beat_entry(self):
        # False is the shipping default; the beat schedule must not carry the
        # polling tick until somebody opts in.
        self.assertIsNone(official_post_polling_entry())

    @override_settings(
        OFFICIAL_POST_POLLING_ENABLED=True,
        OFFICIAL_POST_INGESTION_ENABLED=True,
        X_API_BEARER_TOKEN="t",
    )
    def test_on_returns_the_exact_beat_entry(self):
        entry = official_post_polling_entry()

        self.assertIsNotNone(entry)
        self.assertEqual(entry["task"], "incident.tasks.ingest_official_posts")
        self.assertIsInstance(entry["schedule"], crontab)
        self.assertEqual(entry["schedule"], crontab(minute="*/5"))
        self.assertEqual(entry["options"], {"expires": 240, "time_limit": 180})


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

    @override_settings(X_API_BEARER_TOKEN="test-bearer-token")
    def test_since_id_start_time_and_end_time_reach_the_request(self):
        # The bearer token is pinned above rather than read from the
        # environment: secrets.dev.env sets a real one, so asserting against
        # whatever the operator happened to configure would make this test
        # env-dependent (and would put that token in a failure message).
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
        self.assertEqual(headers["Authorization"], "Bearer test-bearer-token")

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
            "OFFICIAL_POST_POLLING_ENABLED": True,
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


class ExportOfficialPostsFixture:
    """Shared rows for the export tests: two accounts, plus a community link.

    Kept out of the TestCase itself so both export test classes build the exact
    same archive — the fixture posts carry the shipped BM text, which is what
    the verbatim-text assertions read.
    """

    OTHER_HANDLE = "myrapidkl"

    @classmethod
    def build(cls, author):
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))
        ingest_posts(posts, handle="askrapidkl", author=author)
        # A second tracked account, dated a day earlier: --handle and the date
        # window each have something to narrow.
        ingest_posts(
            [
                RawPost(
                    platform=IngestPlatform.X,
                    post_id="1791552500000000001",
                    handle=cls.OTHER_HANDLE,
                    text="Gangguan pada laluan utama",
                    posted_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
                    url=f"https://x.com/{cls.OTHER_HANDLE}/status/1791552500000000001",
                    has_media=False,
                    raw={"id": "1791552500000000001"},
                )
            ],
            handle=cls.OTHER_HANDLE,
            author=author,
        )
        # A hand-submitted link: same table, never part of the operator's
        # archive, so every export must leave it out.
        community = SocialMediaLink.objects.create(
            url="https://twitter.com/kwong/status/1234567890",
            title="community submission",
            description="submitted by a commuter, not ingested",
            user=author,
        )
        return posts, community


class ExportOfficialPostsCommandTests(TestCase):
    """The export command (6.2): mapping, filtering, CSV/JSONL, dry run."""

    def setUp(self):
        self.author = get_system_author()
        self.fixture_posts, self.community = ExportOfficialPostsFixture.build(
            self.author
        )
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmppath = Path(self.tmpdir.name)

    # --- helpers -------------------------------------------------------

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command("export_official_posts", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def _records(self, *args):
        """Run the command to stdout and parse the JSONL back into records."""
        out, _ = self._run(*args)
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def _read(self, path: Path) -> str:
        # newline="" is what the csv docs require for reading a written file.
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()

    def _store(self, **fields) -> SocialMediaLink:
        """Create one automated row directly (for cases ingestion can't make)."""
        defaults = {
            "user": self.author,
            "is_automated": True,
            "platform": IngestPlatform.X,
        }
        return SocialMediaLink.objects.create(**{**defaults, **fields})

    def _command(self):
        from incident.management.commands.export_official_posts import Command

        return Command()

    # --- row mapping ---------------------------------------------------

    def test_one_post_maps_to_the_exact_expected_columns(self):
        records = self._records("--handle", "askrapidkl")
        self.assertEqual(len(records), 2)

        first = records[0]
        stored = SocialMediaLink.objects.get(post_id="1791552310047416320")
        # Column order is part of the dataset contract, so it is asserted, not
        # just the key set.
        self.assertEqual(
            list(first),
            ["post_id", "posted_at", "handle", "text", "permalink"],
        )
        self.assertEqual(first["post_id"], "1791552310047416320")
        self.assertEqual(first["handle"], "askrapidkl")
        self.assertEqual(first["permalink"], stored.url)
        self.assertEqual(
            first["permalink"],
            "https://x.com/askrapidkl/status/1791552310047416320",
        )
        # Verbatim, byte for byte: against the stored column and against the
        # fixture payload ingestion read, not a re-typed literal that could
        # drift from either.
        self.assertEqual(first["text"], stored.description)
        self.assertEqual(first["text"], self.fixture_posts[0].text)
        self.assertIn("Gangguan di LRT Aliran Utama", first["text"])
        # ISO-8601 of the stored post time.
        self.assertEqual(first["posted_at"], stored.posted_at.isoformat())
        self.assertEqual(first["posted_at"], "2026-09-26T11:15:00")

    def test_a_row_without_a_post_time_keeps_a_null_posted_at(self):
        self._store(
            url="https://x.com/askrapidkl/status/1791552900000000001",
            title="no post time",
            description="posted_at could not be parsed",
            post_id="1791552900000000001",
            posted_at=None,
            source_handle="askrapidkl",
        )

        records = self._records("--handle", "askrapidkl")
        undated = next(r for r in records if r["post_id"] == "1791552900000000001")
        self.assertIsNone(undated["posted_at"])
        self.assertIn('"posted_at": null', json.dumps(undated))

    def test_posted_at_order_wins_over_post_id(self):
        # Ids and post times deliberately disagree: the newer post has the
        # smaller id, so ordering by id alone would reverse the archive.
        self._store(
            url="https://x.com/askrapidkl/status/1791552600000000001",
            title="newer",
            description="posted 27 Sep",
            post_id="1791552600000000001",
            posted_at=datetime(2026, 9, 27, 10, 0, tzinfo=UTC),
            source_handle="askrapidkl",
        )
        self._store(
            url="https://x.com/askrapidkl/status/1791552700000000002",
            title="older",
            description="posted 26 Sep",
            post_id="1791552700000000002",
            posted_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
            source_handle="askrapidkl",
        )

        ids = [record["post_id"] for record in self._records()]

        self.assertEqual(
            ids,
            [
                "1791552500000000001",  # 25 Sep, the other account
                "1791552310047416320",  # 26 Sep 03:15Z
                "1791552408821972992",  # 26 Sep 05:42Z
                "1791552700000000002",  # 26 Sep 10:00Z — the LARGER id, first
                "1791552600000000001",  # 27 Sep 10:00Z — the SMALLER id, last
            ],
        )

    def test_equal_posted_at_falls_back_to_post_id(self):
        same = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)
        # Created in reverse id order, so insertion order cannot explain the
        # result.
        for post_id in ("1791552800000000002", "1791552800000000001"):
            self._store(
                url=f"https://x.com/askrapidkl/status/{post_id}",
                title="tie",
                description="same post time",
                post_id=post_id,
                posted_at=same,
                source_handle="askrapidkl",
            )

        ids = [record["post_id"] for record in self._records("--handle", "askrapidkl")]

        self.assertEqual(
            ids,
            [
                "1791552310047416320",  # 26 Sep, from the shipped fixture
                "1791552408821972992",
                "1791552800000000001",  # the tie pair, smaller id first
                "1791552800000000002",
            ],
        )

    def test_the_same_rows_export_to_the_same_bytes_twice(self):
        first = self._run()[0]
        second = self._run()[0]

        self.assertEqual(first, second)
        self.assertEqual(len(first.splitlines()), 3)

    # --- filtering -----------------------------------------------------

    def test_since_until_and_handle_narrow_the_export(self):
        # The fixture pair is on 26 Sep; the other account is on 25 Sep.
        self.assertEqual(
            [r["post_id"] for r in self._records("--since", "2026-09-26")],
            ["1791552310047416320", "1791552408821972992"],
        )
        self.assertEqual(
            [r["post_id"] for r in self._records("--until", "2026-09-25")],
            ["1791552500000000001"],
        )
        self.assertEqual(
            [r["post_id"] for r in self._records("--handle", "myrapidkl")],
            ["1791552500000000001"],
        )
        # A leading '@' is tolerated, as on the ingest command.
        self.assertEqual(
            [r["post_id"] for r in self._records("--handle", "@askrapidkl")],
            ["1791552310047416320", "1791552408821972992"],
        )
        self.assertEqual(
            len(self._records("--since", "2026-09-01", "--until", "2026-09-30")), 3
        )

    def test_date_bounds_are_whole_utc_days_not_local_ones(self):
        # 16:30Z is already 27 Sep in Asia/Kuala_Lumpur, and the project stores
        # naive local time (USE_TZ = False). A local-day reading of the window
        # would file this post under the 27th; the UTC-day reading keeps it on
        # the 26th.
        self._store(
            url="https://x.com/askrapidkl/status/1791552600000000009",
            title="late utc",
            description="26 Sep 16:30Z",
            post_id="1791552600000000009",
            posted_at=datetime(2026, 9, 26, 16, 30, tzinfo=UTC),
            source_handle="askrapidkl",
        )

        on_the_26th = [r["post_id"] for r in self._records("--until", "2026-09-26")]
        on_the_27th = [r["post_id"] for r in self._records("--since", "2026-09-27")]

        self.assertIn("1791552600000000009", on_the_26th)
        self.assertEqual(on_the_27th, [])

    def test_community_rows_are_never_exported(self):
        records = self._records()
        texts = [record["text"] for record in records]

        self.assertEqual(len(records), 3)
        self.assertNotIn(self.community.description, texts)
        self.assertNotIn(self.community.url, [r["permalink"] for r in records])
        self.assertNotIn(self.community.title, texts)
        # It is still there — the export hides it, it does not delete it.
        self.assertTrue(SocialMediaLink.objects.filter(pk=self.community.pk).exists())

    def test_a_handle_nobody_posted_under_exports_nothing(self):
        out, err = self._run("--handle", "nosuchaccount")

        self.assertEqual(out, "")
        self.assertIn("rows=0", err)

    # --- CSV -----------------------------------------------------------

    def test_csv_escapes_commas_quotes_and_newlines_and_round_trips(self):
        nasty = 'Gangguan di "LRT Aliran Utama",\nper MSI Kelana Jaya'
        self._store(
            url="https://x.com/askrapidkl/status/1791553000000000001",
            title="nasty",
            description=nasty,
            post_id="1791553000000000001",
            posted_at=datetime(2026, 9, 29, 5, 0, tzinfo=UTC),
            source_handle="askrapidkl",
        )
        target = self.tmppath / "export.csv"

        out, err = self._run(
            "--format", "csv", "--handle", "askrapidkl", "--output", str(target)
        )

        # A path means the rows land in the file and stdout carries the summary.
        self.assertIn("rows=3", out)
        self.assertEqual(err, "")
        text = self._read(target)
        # The stdlib writer did the escaping, not the test: embedded quotes are
        # doubled and the comma/newline live inside one quoted cell.
        self.assertIn('"Gangguan di ""LRT Aliran Utama"",', text)
        # …and it reads back identically.
        rows = list(csv.reader(StringIO(text, newline="")))
        self.assertEqual(
            rows[0], ["post_id", "posted_at", "handle", "text", "permalink"]
        )
        self.assertEqual(len(rows), 4)  # header + the two fixture posts + this one
        nasty_row = next(row for row in rows[1:] if row[0] == "1791553000000000001")
        self.assertEqual(nasty_row[3], nasty)

    def test_csv_writes_its_header_even_with_no_rows(self):
        target = self.tmppath / "empty.csv"

        out, err = self._run(
            "--format", "csv", "--handle", "nosuchaccount", "--output", str(target)
        )

        self.assertIn("rows=0", out)
        self.assertEqual(err, "")
        rows = list(csv.reader(StringIO(self._read(target), newline="")))
        self.assertEqual(
            rows, [["post_id", "posted_at", "handle", "text", "permalink"]]
        )

    # --- JSONL ---------------------------------------------------------

    def test_jsonl_writes_one_valid_object_per_row(self):
        out, _ = self._run()

        lines = out.splitlines()
        self.assertEqual(len(lines), 3)
        for line in lines:
            # Would raise on a malformed line — a piped consumer must not be
            # handed half a record.
            self.assertIsInstance(json.loads(line), dict)

    def test_include_raw_toggles_the_raw_payload_column(self):
        plain = self._records("--handle", "askrapidkl")
        self.assertNotIn("raw_payload", plain[0])

        with_raw = self._records("--handle", "askrapidkl", "--include-raw")
        self.assertEqual(
            list(with_raw[0]),
            ["post_id", "posted_at", "handle", "text", "permalink", "raw_payload"],
        )
        stored = SocialMediaLink.objects.get(post_id="1791552310047416320")
        self.assertEqual(with_raw[0]["raw_payload"], stored.raw_payload)
        # A native object, not a JSON string.
        self.assertIsInstance(with_raw[0]["raw_payload"], dict)

    def test_raw_payload_is_json_encoded_in_a_csv_cell(self):
        self._store(
            url="https://x.com/askrapidkl/status/1791553000000000002",
            title="raw",
            description="raw in csv",
            post_id="1791553000000000002",
            posted_at=datetime(2026, 9, 29, 5, 0, tzinfo=UTC),
            source_handle="askrapidkl",
            raw_payload={"id": "1791553000000000002", "text": "raw, in csv"},
        )
        target = self.tmppath / "raw.csv"

        self._run(
            "--format",
            "csv",
            "--include-raw",
            "--handle",
            "askrapidkl",
            "--output",
            str(target),
        )

        rows = list(csv.reader(StringIO(self._read(target), newline="")))
        self.assertEqual(
            rows[0],
            [
                "post_id",
                "posted_at",
                "handle",
                "text",
                "permalink",
                "raw_payload",
            ],
        )
        cell = next(row[5] for row in rows[1:] if row[0] == "1791553000000000002")
        self.assertEqual(
            json.loads(cell), {"id": "1791553000000000002", "text": "raw, in csv"}
        )

    def test_raw_payload_is_not_selected_when_it_is_not_exported(self):
        from incident.management.commands.export_official_posts import (
            EXPORT_COLUMNS,
            _row_fields,
        )

        self.assertNotIn("raw_payload", _row_fields(EXPORT_COLUMNS))
        self.assertEqual(
            _row_fields(EXPORT_COLUMNS + ("raw_payload",))[-1], "raw_payload"
        )

    # --- output & dry run -----------------------------------------------

    def test_stdout_export_keeps_the_summary_off_the_data_stream(self):
        out, err = self._run()

        # Every stdout line is a record, so the export stays pipeable.
        for line in out.splitlines():
            json.loads(line)
        self.assertNotIn("rows=", out)
        self.assertIn("rows=3", err)
        self.assertIn("format=jsonl", err)

    def test_dry_run_reports_the_count_and_writes_nothing(self):
        target = self.tmppath / "dry.jsonl"

        out, _ = self._run("--dry-run", "--output", str(target))

        self.assertFalse(target.exists())
        self.assertIn("rows=3", out)
        self.assertIn("dry_run=True", out)

    def test_dry_run_emits_no_rows_and_no_csv_header(self):
        out, _ = self._run("--dry-run")

        self.assertNotIn("{", out)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertNotIn("post_id,", self._run("--dry-run", "--format", "csv")[0])

    def test_dry_run_counts_the_same_rows_a_real_run_would_write(self):
        target = self.tmppath / "counted.jsonl"

        self._run("--dry-run", "--handle", "myrapidkl", "--output", str(target))
        self._run("--handle", "myrapidkl", "--output", str(target))

        self.assertEqual(len(self._read(target).splitlines()), 1)

    # --- streaming & refusals -------------------------------------------

    def test_records_stream_from_a_cursor_instead_of_a_list(self):
        from incident.management.commands.export_official_posts import EXPORT_COLUMNS

        command = self._command()
        queryset = command._queryset(handles=[], since=None, until=None)

        records = command._iter_records(queryset, EXPORT_COLUMNS)

        # A generator, so a long archive is never a list in memory. The whole
        # set still comes out.
        self.assertIsInstance(records, GeneratorType)
        self.assertEqual(len(list(records)), 3)

    def test_unknown_format_is_refused(self):
        with self.assertRaises(CommandError) as caught:
            self._run("--format", "tsv")

        self.assertIn("tsv", str(caught.exception))

    def test_malformed_date_and_a_reversed_window_are_refused(self):
        with self.assertRaises(CommandError) as caught:
            self._run("--since", "26-09-2026")
        self.assertIn("YYYY-MM-DD", str(caught.exception))

        with self.assertRaises(CommandError) as caught:
            self._run("--since", "2026-09-05", "--until", "2026-09-01")
        self.assertIn("is before", str(caught.exception))

    def test_an_unwritable_destination_raises_command_error(self):
        with self.assertRaises(CommandError) as caught:
            self._run("--output", str(self.tmppath / "missing" / "dir" / "out.jsonl"))

        self.assertIn("could not be written", str(caught.exception))


class ExportOfficialPostsHubPushTests(TestCase):
    """The optional ``--push-to-hub`` path (6.2), with ``datasets`` faked."""

    def setUp(self):
        self.author = get_system_author()
        ExportOfficialPostsFixture.build(self.author)

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command("export_official_posts", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def _fake_datasets(self):
        """Stand in for the optional ``datasets`` package.

        ``from datasets import Dataset`` resolves straight out of
        ``sys.modules``, so replacing that one entry is the whole seam — no
        install, no network, and the assertions can see both the records handed
        over and the ``push_to_hub`` call.
        """
        pushed = mock.Mock(name="dataset")
        dataset_class = mock.Mock(
            name="Dataset", from_dict=mock.Mock(return_value=pushed)
        )
        return SimpleNamespace(Dataset=dataset_class), dataset_class, pushed

    def _read(self, path: Path) -> str:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()

    def test_push_to_hub_sends_the_expected_records_to_a_private_dataset(self):
        module, dataset_class, pushed = self._fake_datasets()
        repo_id = "rosak/rapidkl-official-posts"

        with (
            mock.patch.dict(sys.modules, {"datasets": module}),
            mock.patch.dict(os.environ, {"HF_TOKEN": "hf_secret_token_value"}),
        ):
            _, err = self._run("--push-to-hub", repo_id, "--handle", "askrapidkl")

        # from_dict gets the dataset schema: one key per column, one list of
        # values each, in column order.
        records = dataset_class.from_dict.call_args.args[0]
        self.assertEqual(
            list(records),
            ["post_id", "posted_at", "handle", "text", "permalink"],
        )
        self.assertEqual(
            records["post_id"], ["1791552310047416320", "1791552408821972992"]
        )
        self.assertEqual(records["handle"], ["askrapidkl", "askrapidkl"])
        self.assertIn("Gangguan di LRT Aliran Utama", records["text"][0])
        # Private by default, the repo explicit, and the token passed on but
        # never printed.
        pushed.push_to_hub.assert_called_once_with(
            repo_id, token="hf_secret_token_value", private=True
        )
        self.assertNotIn("hf_secret_token_value", err)
        self.assertIn(f"push_to_hub={repo_id}", err)

    def test_push_to_hub_can_carry_the_raw_column(self):
        module, dataset_class, _ = self._fake_datasets()

        with mock.patch.dict(sys.modules, {"datasets": module}):
            self._run(
                "--push-to-hub",
                "rosak/rapidkl-official-posts",
                "--handle",
                "askrapidkl",
                "--include-raw",
            )

        handed_over = dataset_class.from_dict.call_args.args[0]
        self.assertEqual(
            list(handed_over),
            [
                "post_id",
                "posted_at",
                "handle",
                "text",
                "permalink",
                "raw_payload",
            ],
        )
        # A native object, not the JSON string a CSV cell would carry.
        self.assertIsInstance(handed_over["raw_payload"][0], dict)

    def test_push_also_writes_the_requested_output_file(self):
        module, _, pushed = self._fake_datasets()
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        target = Path(tmpdir.name) / "export.jsonl"

        with mock.patch.dict(sys.modules, {"datasets": module}):
            out, _ = self._run(
                "--push-to-hub", "rosak/rapidkl-official-posts", "--output", str(target)
            )

        pushed.push_to_hub.assert_called_once()
        # The push and the file are independent sinks, and one pass over the
        # queryset feeds both.
        self.assertIn("rows=3", out)
        self.assertEqual(len(self._read(target).splitlines()), 3)

    def test_a_missing_datasets_package_raises_an_actionable_command_error(self):
        # ``sys.modules[name] = None`` is the documented way to make an import
        # fail: CPython raises ModuleNotFoundError (an ImportError) instead of
        # searching the filesystem, so this works whether or not the package
        # happens to be installed.
        with mock.patch.dict(sys.modules, {"datasets": None}):
            with self.assertRaises(CommandError) as caught:
                self._run("--push-to-hub", "rosak/rapidkl-official-posts")

        message = str(caught.exception)
        self.assertIn("--push-to-hub requires the 'datasets' package", message)
        self.assertIn("pip install datasets", message)
        self.assertIn("HF_TOKEN", message)

    def test_dry_run_never_pushes(self):
        module, dataset_class, pushed = self._fake_datasets()

        with mock.patch.dict(sys.modules, {"datasets": module}):
            out, _ = self._run(
                "--dry-run", "--push-to-hub", "rosak/rapidkl-official-posts"
            )

        dataset_class.from_dict.assert_not_called()
        pushed.push_to_hub.assert_not_called()
        self.assertIn("rows=3", out)
        self.assertIn("push_to_hub=rosak/rapidkl-official-posts", out)


# ---------------------------------------------------------------------------
# X (Twitter) Activity API webhook receiver
# ---------------------------------------------------------------------------
#
# Every test in this section pins its secrets and flags with explicit
# ``override_settings``. That is not defensive boilerplate: the dev environment
# carries *real* X API keys, so a test relying on the shipped defaults would
# verify signatures against whatever the operator configured — and a failing
# assertion would print that secret into the test output.

WEBHOOK_URL = "/webhooks/x-api"
#: Obviously fictitious signing secrets. Real ones never appear in the repo.
TEST_OAUTH2_SECRET = "test-oauth2-client-secret"
TEST_LEGACY_SECRET = "test-legacy-consumer-secret"
#: The XAA filter/author id for the tracked account, and the post it delivered.
WEBHOOK_AUTHOR_ID = "2244994945"
WEBHOOK_POST_ID = "1791552310047416320"
WEBHOOK_POST_TEXT = "Gangguan laluan utama &amp; penyehjangan(types): MTR"
WEBHOOK_CREATED_AT = "2026-09-28T04:05:00.000Z"
#: Header name for each signing candidate, kept next to the secret it pairs with
#: so a test never has to guess which one the app prefers.
OAUTH2_SIGNATURE_HEADER = "X-Twitter-Webhooks-Signature-Oauth2"
LEGACY_SIGNATURE_HEADER = "X-Twitter-Webhooks-Signature"

#: Every test class below that drives ``self.client`` needs this. The test runner
#: sets ``settings.DEBUG = False``, which is why ``rosak.urls`` withholds the
#: ``__debug__`` routes — but the toolbar's ``SHOW_TOOLBAR_CALLBACK`` closes over
#: ``rosak.settings.DEBUG``, the *module* global, which the runner does not
#: touch and which is True in this environment. So the middleware stays active
#: and reverses the ``djdt`` namespace that is not there, turning every test
#: client request into ``NoReverseMatch``. Same remedy the other view test
#: classes in this repo already use.
no_debug_toolbar = modify_settings(
    MIDDLEWARE={
        "remove": ["strawberry_django.middlewares.debug_toolbar.DebugToolbarMiddleware"]
    }
)


def xaa_post_create_payload(
    *,
    post_id: str = WEBHOOK_POST_ID,
    text: str = WEBHOOK_POST_TEXT,
    author_id: str = WEBHOOK_AUTHOR_ID,
    username: str | None = "askrapidkl",
    event_type: str = "post.create",
    filter_user_id: str | None = None,
    created_at: str = WEBHOOK_CREATED_AT,
) -> dict:
    """A current-shaped Activity API ``post.create`` delivery.

    ``username=None`` drops the ``includes.users`` expansion, which is what
    forces the reverse (user-id → handle) lookup path.
    """
    event_filter: dict = {}
    if filter_user_id is not None:
        event_filter["user_id"] = filter_user_id
    event = {
        "event_uuid": "0f0f0f0f-0000-4000-8000-000000000001",
        "event_type": event_type,
        "tag": "official-posts",
        "filter": event_filter,
        "payload": {
            "id": post_id,
            "text": text,
            "created_at": created_at,
            "author_id": author_id,
        },
    }
    payload = {"data": event}
    if username is not None:
        payload["includes"] = {
            "users": [{"id": author_id, "username": username, "name": "RapidKL"}]
        }
    return payload


def aaa_post_create_payload(
    *,
    post_id: str = WEBHOOK_POST_ID,
    text: str = WEBHOOK_POST_TEXT,
    user_id: str = WEBHOOK_AUTHOR_ID,
    for_user_id: str = WEBHOOK_AUTHOR_ID,
    created_at: str = WEBHOOK_CREATED_AT,
) -> dict:
    """A deprecated AAA ``tweet_create_events`` delivery (no ``data`` envelope)."""
    return {
        "for_user_id": for_user_id,
        "tweet_create_events": [
            {
                "id": post_id,
                "text": text,
                "created_at": created_at,
                "user_id": user_id,
            }
        ],
    }


def signed_delivery(
    payload: dict,
    *,
    secret: str = TEST_LEGACY_SECRET,
    header: str = LEGACY_SIGNATURE_HEADER,
) -> tuple[bytes, dict[str, str]]:
    """``(raw bytes, headers)`` — the signature covers exactly these bytes.

    Deliberately *not* a helper that both encodes and posts: signing a
    re-serialization of the parsed body is the classic way to make a webhook
    verifier pass in tests and fail in production.
    """
    raw = json.dumps(payload).encode("utf-8")
    return raw, {header: sign_body(secret, raw)}


def fake_x_response(status: int = 200, payload=None, *, unparseable: bool = False):
    """A ``requests`` response stand-in for the management-command tests."""

    def _json():
        if unparseable:
            raise ValueError("no JSON could be decoded")
        return payload

    return SimpleNamespace(status_code=status, json=_json)


class XWebhookSigningTests(TestCase):
    """CRC signing and delivery-signature verification, with no HTTP involved."""

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY=TEST_LEGACY_SECRET
    )
    def test_sign_body_matches_the_published_hmac_sha256_vector(self):
        # RFC 4231 test case 1: key = 0x0b * 20, data = "Hi There". Asserting a
        # vector from outside this codebase is the only way the test can fail if
        # the construction itself is wrong, rather than merely agreeing with a
        # second copy of the same mistake.
        expected = "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
        self.assertEqual(
            sign_body(bytes([0x0B] * 20).decode("latin-1"), b"Hi There"),
            "sha256=" + base64.b64encode(bytes.fromhex(expected)).decode(),
        )

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY=TEST_LEGACY_SECRET
    )
    def test_crc_token_is_the_documented_sha256_base64_form(self):
        token = crc_response_token("hello")

        self.assertTrue(token.startswith("sha256="))
        # Exactly one '=' separator, then standard base64 of a 32-byte digest.
        _, _, encoded = token.partition("=")
        self.assertEqual(len(base64.b64decode(encoded, validate=True)), 32)
        self.assertEqual(token, sign_body(TEST_LEGACY_SECRET, "hello".encode("utf-8")))

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET,
        X_API_SECRET_KEY=TEST_LEGACY_SECRET,
    )
    def test_crc_prefers_the_oauth2_client_secret_when_both_are_set(self):
        # X verifies the CRC answer against the secret it signs with, which is
        # the OAuth 2.0 client secret when the app has one.
        self.assertEqual(
            crc_response_token("hello"),
            sign_body(TEST_OAUTH2_SECRET, b"hello"),
        )

    @override_settings(X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY="")
    def test_crc_without_any_secret_raises_rather_than_signing_with_nothing(self):
        with self.assertRaises(OfficialPostFetchError) as caught:
            crc_response_token("hello")

        self.assertIn("X_API_OAUTH2_CLIENT_SECRET", str(caught.exception))

    def test_has_signing_secret_tracks_the_configured_candidates(self):
        with override_settings(X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY=""):
            self.assertFalse(has_signing_secret())
        with override_settings(X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY="   "):
            self.assertFalse(has_signing_secret())
        with override_settings(
            X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET, X_API_SECRET_KEY=""
        ):
            self.assertTrue(has_signing_secret())

    # --- signature verification -----------------------------------------

    def _headers(self, signature: str, header: str) -> dict[str, str]:
        return {header: signature}

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY=TEST_LEGACY_SECRET
    )
    def test_the_legacy_consumer_secret_signature_is_accepted(self):
        raw = b'{"data":{"event_type":"post.create"}}'
        headers = self._headers(
            sign_body(TEST_LEGACY_SECRET, raw), LEGACY_SIGNATURE_HEADER
        )

        self.assertTrue(verify_webhook_signature(headers, raw))

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET, X_API_SECRET_KEY=""
    )
    def test_the_oauth2_client_secret_signature_is_accepted(self):
        raw = b'{"data":{"event_type":"post.create"}}'
        headers = self._headers(
            sign_body(TEST_OAUTH2_SECRET, raw), OAUTH2_SIGNATURE_HEADER
        )

        self.assertTrue(verify_webhook_signature(headers, raw))

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET,
        X_API_SECRET_KEY=TEST_LEGACY_SECRET,
    )
    def test_either_configured_candidate_is_enough(self):
        # A half-migrated app — OAuth 2.0 secret set, but X still signing with
        # the legacy consumer secret — must keep receiving.
        raw = b"a raw body"
        for secret, header in (
            (TEST_OAUTH2_SECRET, OAUTH2_SIGNATURE_HEADER),
            (TEST_LEGACY_SECRET, LEGACY_SIGNATURE_HEADER),
        ):
            with self.subTest(header=header):
                self.assertTrue(
                    verify_webhook_signature(
                        self._headers(sign_body(secret, raw), header), raw
                    )
                )

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET,
        X_API_SECRET_KEY=TEST_LEGACY_SECRET,
    )
    def test_a_signature_from_the_wrong_secret_is_rejected(self):
        raw = b"a raw body"

        self.assertFalse(
            verify_webhook_signature(
                self._headers(
                    sign_body("some-other-secret", raw), LEGACY_SIGNATURE_HEADER
                ),
                raw,
            )
        )

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET,
        X_API_SECRET_KEY=TEST_LEGACY_SECRET,
    )
    def test_a_signature_over_different_bytes_is_rejected(self):
        signed = b'{"a":1}'
        replayed = b'{"a": 1}'  # same JSON value, different octets

        self.assertFalse(
            verify_webhook_signature(
                self._headers(
                    sign_body(TEST_LEGACY_SECRET, signed), LEGACY_SIGNATURE_HEADER
                ),
                replayed,
            )
        )

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET,
        X_API_SECRET_KEY=TEST_LEGACY_SECRET,
    )
    def test_a_missing_signature_header_is_rejected(self):
        self.assertFalse(verify_webhook_signature({}, b"a raw body"))
        self.assertFalse(
            verify_webhook_signature({LEGACY_SIGNATURE_HEADER: "   "}, b"a raw body")
        )

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET,
        X_API_SECRET_KEY=TEST_LEGACY_SECRET,
    )
    def test_nothing_is_accepted_when_no_secret_is_configured(self):
        # A signature over an empty key is computable by anyone, so an
        # unconfigured candidate must never authenticate a delivery.
        headers = self._headers(sign_body("", b"a raw body"), LEGACY_SIGNATURE_HEADER)

        with override_settings(X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY=""):
            self.assertFalse(verify_webhook_signature(headers, b"a raw body"))

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY=TEST_LEGACY_SECRET
    )
    def test_the_header_name_is_matched_case_insensitively(self):
        raw = b"a raw body"
        signature = sign_body(TEST_LEGACY_SECRET, raw)

        self.assertTrue(
            verify_webhook_signature({"x-twitter-webhooks-signature": signature}, raw)
        )

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY=TEST_LEGACY_SECRET
    )
    def test_a_non_ascii_signature_is_rejected_without_raising(self):
        # compare_digest refuses non-ASCII str; a hostile header must produce a
        # 403, not a 500.
        self.assertFalse(
            verify_webhook_signature(
                {LEGACY_SIGNATURE_HEADER: "sha256=ééé"}, b"a raw body"
            )
        )


@no_debug_toolbar
class XWebhookCrcViewTests(TestCase):
    """``GET /webhooks/x-api`` — X's registration-time CRC challenge."""

    def _get(self, query: str = ""):
        return self.client.get(f"{WEBHOOK_URL}{query}")

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET, X_API_SECRET_KEY=""
    )
    def test_get_returns_the_response_token(self):
        response = self._get("?crc_token=hello")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        # The token is asserted against the same construction X specifies, never
        # printed: a live CRC value is a short-lived credential.
        self.assertEqual(
            body["response_token"], sign_body(TEST_OAUTH2_SECRET, b"hello")
        )
        self.assertNotIn("status", body)

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET, X_API_SECRET_KEY=""
    )
    def test_get_answers_the_legacy_secret_when_it_is_the_only_one(self):
        response = self._get("?crc_token=hello")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["response_token"],
            sign_body(TEST_OAUTH2_SECRET, b"hello"),
        )

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET, X_API_SECRET_KEY=""
    )
    def test_get_without_a_crc_token_is_400(self):
        response = self._get()

        self.assertEqual(response.status_code, 400)
        self.assertIn("crc_token", response.json()["reason"])

    @override_settings(
        X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET, X_API_SECRET_KEY=""
    )
    def test_get_with_a_blank_crc_token_is_400(self):
        response = self._get("?crc_token=")

        self.assertEqual(response.status_code, 400)

    @override_settings(X_API_OAUTH2_CLIENT_SECRET="", X_API_SECRET_KEY="")
    def test_get_without_any_signing_secret_is_503_and_actionable(self):
        with self.assertLogs("incident.views", level="ERROR") as logs:
            response = self._get("?crc_token=hello")

        self.assertEqual(response.status_code, 503)
        self.assertIn("X_API_OAUTH2_CLIENT_SECRET", str(logs.output))
        # The operator is told what to configure but not what is configured.
        self.assertNotIn(TEST_LEGACY_SECRET, response.content.decode())

    def test_other_methods_are_405(self):
        for method in (self.client.put, self.client.delete, self.client.patch):
            with self.subTest(method=method.__name__):
                response = method(WEBHOOK_URL)
                self.assertEqual(response.status_code, 405)
        self.assertIn("GET, POST", self.client.put(WEBHOOK_URL)["Allow"])


@override_settings(
    # DEBUG is False in this environment, so the shipped default cache is the
    # *shared* Redis one — not the DummyCache the docs assume — and these
    # assertions would be decided by whatever a previous run left behind. A
    # private LocMem backend is the only way "a cache hit changes the answer"
    # is actually what is under test.
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "x-webhook-handle-resolution",
        }
    }
)
class XWebhookHandleResolutionTests(TestCase):
    """``includes.users`` first (no network), then a bounded reverse lookup."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_the_includes_expansion_resolves_the_handle_with_no_network(self):
        with mock.patch.object(
            official_posts,
            "_resolve_user_id",
            side_effect=AssertionError("network must not be used"),
        ):
            result = ingest_webhook_payload(xaa_post_create_payload())

        self.assertEqual(result.events, 1)
        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.unresolved, 0)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.source_handle, "askrapidkl")

    @override_settings(OFFICIAL_POST_HANDLES=["askrapidkl", "myrapidkl"])
    def test_without_the_expansion_the_filter_user_id_drives_the_reverse_lookup(self):
        # A user id of its own per test: a positive match is cached forever, so
        # reusing one id would let the previous test decide this one's answer.
        author_id = "7100000000000000001"
        payload = xaa_post_create_payload(
            author_id=author_id, username=None, filter_user_id=author_id
        )

        with mock.patch.object(
            official_posts, "_resolve_user_id", return_value=author_id
        ) as resolve:
            result = ingest_webhook_payload(payload)

        # Bounded: one comparison per tracked handle, then a positive cache.
        self.assertEqual(
            [call.args[0] for call in resolve.call_args_list],
            ["askrapidkl"],
        )
        self.assertEqual(result.ingested, 1)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.source_handle, "askrapidkl")

    @override_settings(OFFICIAL_POST_HANDLES=["askrapidkl", "myrapidkl"])
    def test_a_handle_whose_lookup_fails_does_not_abort_the_others(self):
        author_id = "7100000000000000002"

        with mock.patch.object(
            official_posts,
            "_resolve_user_id",
            side_effect=[
                official_posts.OfficialPostFetchError("X API error: HTTP 429"),
                author_id,
            ],
        ):
            # The warning is the service's, not the webhook parser's: it is
            # logged where the per-handle lookup actually failed.
            with self.assertLogs("incident.services.official_posts", level="WARNING"):
                result = ingest_webhook_payload(
                    xaa_post_create_payload(
                        author_id=author_id, username=None, filter_user_id=author_id
                    )
                )

        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.unresolved, 0)

    @override_settings(OFFICIAL_POST_HANDLES=["askrapidkl", "myrapidkl"])
    def test_an_author_with_no_tracked_handle_is_counted_and_dropped(self):
        # Tracked handles resolve to some *other* id, so nothing matches.
        author_id = "7100000000000000003"

        with mock.patch.object(
            official_posts, "_resolve_user_id", return_value="7100000000000000004"
        ):
            result = ingest_webhook_payload(
                xaa_post_create_payload(
                    author_id=author_id, username=None, filter_user_id=author_id
                )
            )

        # Nothing was attributed and no row was written: a wrong permalink is
        # worse than a dropped post.
        self.assertEqual(result.events, 1)
        self.assertEqual(result.ingested, 0)
        self.assertEqual(result.unresolved, 1)
        self.assertEqual(SocialMediaLink.objects.count(), 0)

    @override_settings(OFFICIAL_POST_HANDLES=["askrapidkl", "myrapidkl"])
    def test_resolve_handle_caches_only_a_positive_match(self):
        matched_id = "7100000000000000005"
        missed_id = "7100000000000000006"

        with mock.patch.object(
            official_posts, "_resolve_user_id", return_value=matched_id
        ) as resolve:
            self.assertEqual(resolve_handle_for_user_id(matched_id), "askrapidkl")
            # Second call is served from the cache: no comparison at all.
            self.assertEqual(resolve_handle_for_user_id(matched_id), "askrapidkl")
        self.assertEqual(resolve.call_count, 1)

        # A miss is never cached, so widening OFFICIAL_POST_HANDLES later starts
        # working without a cache flush — two calls, two walks of the handles.
        with mock.patch.object(
            official_posts, "_resolve_user_id", return_value="7100000000000000007"
        ) as resolve:
            self.assertIsNone(resolve_handle_for_user_id(missed_id))
            self.assertIsNone(resolve_handle_for_user_id(missed_id))
        self.assertEqual(resolve.call_count, 2 * len(settings.OFFICIAL_POST_HANDLES))

        self.assertIsNone(resolve_handle_for_user_id(""))


@no_debug_toolbar
@override_settings(
    # Same reasoning as XWebhookHandleResolutionTests: the deprecated AAA
    # deliveries resolve their handle by reverse lookup, and a cache left in the
    # shared Redis by an earlier run would silently skip that lookup.
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "x-webhook-delivery-view",
        }
    }
)
class XWebhookDeliveryViewTests(TestCase):
    """``POST /webhooks/x-api`` — verify, ingest, acknowledge inside 10 seconds."""

    BASE_SETTINGS = {
        "OFFICIAL_POST_INGESTION_ENABLED": True,
        "OFFICIAL_POST_POLLING_ENABLED": False,
        "OFFICIAL_POST_HANDLES": ["askrapidkl"],
        "X_API_OAUTH2_CLIENT_SECRET": "",
        "X_API_SECRET_KEY": TEST_LEGACY_SECRET,
        "TELEGRAM_ADMIN_CHAT_ID": "-1001234",
    }

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # The symbol incident.views imported, so the enqueue is observable and
        # no broker is contacted.
        self.notify = mock.patch("incident.views.notify_official_post_links").start()
        self.addCleanup(mock.patch.stopall)

    def _post(
        self,
        payload,
        *,
        secret=TEST_LEGACY_SECRET,
        header=LEGACY_SIGNATURE_HEADER,
        **overrides,
    ):
        raw, headers = signed_delivery(payload, secret=secret, header=header)
        with override_settings(**{**self.BASE_SETTINGS, **overrides}):
            return self.client.post(
                WEBHOOK_URL, data=raw, content_type="application/json", headers=headers
            )

    def _post_raw(self, raw: bytes, *, signature: str | None = None, **overrides):
        headers = {}
        if signature is not None:
            headers[LEGACY_SIGNATURE_HEADER] = signature
        with override_settings(**{**self.BASE_SETTINGS, **overrides}):
            return self.client.post(
                WEBHOOK_URL, data=raw, content_type="application/json", headers=headers
            )

    def test_a_signed_delivery_creates_exactly_one_pending_row(self):
        response = self._post(xaa_post_create_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "events": 1,
                "ingested": 1,
                "skipped": 0,
                "unresolved": 0,
            },
        )
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.status, SocialMediaLinkStatus.PENDING_APPROVAL)
        self.assertTrue(link.is_automated)
        self.assertEqual(link.user, get_system_author())
        # Verbatim, byte for byte — including the ampersand.
        self.assertEqual(link.description, WEBHOOK_POST_TEXT)
        self.assertEqual(link.title, WEBHOOK_POST_TEXT[:256])
        # The handle comes from includes.users; the permalink is built from it.
        self.assertEqual(link.source_handle, "askrapidkl")
        self.assertEqual(link.url, f"https://x.com/askrapidkl/status/{WEBHOOK_POST_ID}")
        self.assertEqual(link.platform, IngestPlatform.X)
        # The post's own time, stored as naive local because USE_TZ is off.
        self.assertEqual(
            link.posted_at,
            timezone.make_naive(datetime(2026, 9, 28, 4, 5, tzinfo=UTC)),
        )
        # The provider object is kept whole for the export.
        self.assertEqual(link.raw_payload["id"], WEBHOOK_POST_ID)

    def test_a_new_row_queues_the_notification_once(self):
        self._post(xaa_post_create_payload())

        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.notify.delay.assert_called_once_with([link.id])
        # The task, not a direct send: an inline Telegram round trip would blow
        # the 10-second acknowledgement budget.
        self.assertEqual(self.notify.delay.call_count, 1)

    def test_a_reply_carries_referenced_tweets_and_is_still_ingested(self):
        # Replies, quotes and reposts all arrive as post.create; parity with
        # exclude_retweets=False means they are kept.
        payload = xaa_post_create_payload()
        payload["data"]["payload"]["referenced_tweets"] = [
            {"type": "replied_to", "id": "1791550000000000000"}
        ]

        response = self._post(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ingested"], 1)
        self.assertTrue(
            SocialMediaLink.objects.filter(post_id=WEBHOOK_POST_ID).exists()
        )

    def test_the_oauth2_signature_is_accepted_when_that_secret_is_configured(self):
        response = self._post(
            xaa_post_create_payload(),
            secret=TEST_OAUTH2_SECRET,
            header=OAUTH2_SIGNATURE_HEADER,
            X_API_OAUTH2_CLIENT_SECRET=TEST_OAUTH2_SECRET,
            X_API_SECRET_KEY="",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ingested"], 1)

    def test_a_redelivery_creates_nothing_and_queues_nothing(self):
        first = self._post(xaa_post_create_payload())
        second = self._post(xaa_post_create_payload())

        self.assertEqual(first.json()["ingested"], 1)
        # X retries and redelivers; (platform, post_id) idempotency is what makes
        # the second delivery a no-op rather than a duplicate row.
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            second.json(),
            {
                "status": "ok",
                "events": 1,
                "ingested": 0,
                "skipped": 1,
                "unresolved": 0,
            },
        )
        self.assertEqual(SocialMediaLink.objects.count(), 1)
        self.notify.delay.assert_called_once()

    def test_a_wrong_signature_is_403_and_writes_nothing(self):
        payload = xaa_post_create_payload()
        raw = json.dumps(payload).encode()

        with self.assertLogs("incident.views", level="WARNING") as logs:
            response = self._post_raw(raw, signature=sign_body("wrong", raw))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.notify.delay.assert_not_called()
        # One line, no detail: a prober learns nothing about which header or
        # which secret is configured, and no secret is echoed.
        self.assertIn("signature", str(logs.output))
        self.assertNotIn(TEST_LEGACY_SECRET, str(logs.output))
        self.assertNotIn("wrong", str(logs.output))

    def test_a_missing_signature_is_403_and_writes_nothing(self):
        response = self._post_raw(json.dumps(xaa_post_create_payload()).encode())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.notify.delay.assert_not_called()

    def test_a_delivery_is_403_when_no_signing_secret_is_configured(self):
        raw, headers = signed_delivery(xaa_post_create_payload())

        with override_settings(
            **{
                **self.BASE_SETTINGS,
                "X_API_SECRET_KEY": "",
                "X_API_OAUTH2_CLIENT_SECRET": "",
            }
        ):
            response = self.client.post(
                WEBHOOK_URL, data=raw, content_type="application/json", headers=headers
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(SocialMediaLink.objects.count(), 0)

    def test_the_ingestion_master_switch_off_acknowledges_without_writing(self):
        response = self._post(
            xaa_post_create_payload(), OFFICIAL_POST_INGESTION_ENABLED=False
        )

        # 200, not 5xx: ingestion being off is an operator decision, and an
        # error would only earn a retry storm.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ignored", "reason": "ingestion disabled"},
        )
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.notify.delay.assert_not_called()

    def test_a_non_post_create_event_is_acknowledged_and_ignored(self):
        payload = xaa_post_create_payload(event_type="post.delete")
        payload["data"].pop("payload")

        response = self._post(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(response.json()["events"], 0)
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.notify.delay.assert_not_called()

    def test_the_deprecated_aaa_shape_is_ingested(self):
        with mock.patch.object(
            official_posts, "_resolve_user_id", return_value=WEBHOOK_AUTHOR_ID
        ):
            response = self._post(aaa_post_create_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ingested"], 1)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.source_handle, "askrapidkl")
        self.assertEqual(link.url, f"https://x.com/askrapidkl/status/{WEBHOOK_POST_ID}")
        self.notify.delay.assert_called_once()

    def test_the_aaa_shape_resolves_the_handle_from_for_user_id(self):
        # No author key at all: for_user_id is the only id the delivery carries.
        payload = aaa_post_create_payload()
        payload["tweet_create_events"][0].pop("user_id")

        with mock.patch.object(
            official_posts, "_resolve_user_id", return_value=WEBHOOK_AUTHOR_ID
        ) as resolve:
            response = self._post(payload)

        self.assertEqual(response.json()["ingested"], 1)
        self.assertEqual(resolve.call_args.args[0], "askrapidkl")

    def test_an_unresolvable_handle_is_200_counted_and_logged(self):
        with mock.patch.object(official_posts, "_resolve_user_id", return_value="999"):
            with self.assertLogs(
                "incident.services.x_webhooks", level="WARNING"
            ) as logs:
                response = self._post(
                    xaa_post_create_payload(username=None, filter_user_id="42")
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unresolved"], 1)
        self.assertEqual(response.json()["ingested"], 0)
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.notify.delay.assert_not_called()
        self.assertTrue(any("no tracked handle" in line for line in logs.output))

    def test_a_body_that_is_not_json_is_400(self):
        raw = b"this is not json"
        response = self._post_raw(raw, signature=sign_body(TEST_LEGACY_SECRET, raw))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.notify.delay.assert_not_called()

    def test_a_json_body_that_is_not_an_object_is_400(self):
        raw = b"[1, 2, 3]"
        response = self._post_raw(raw, signature=sign_body(TEST_LEGACY_SECRET, raw))

        self.assertEqual(response.status_code, 400)
        self.assertIn("object", response.json()["reason"])

    def test_a_post_with_no_id_is_skipped_not_fatal(self):
        payload = xaa_post_create_payload()
        payload["data"]["payload"].pop("id")

        with self.assertLogs("incident.services.x_webhooks", level="WARNING"):
            response = self._post(payload)

        # Accounted for as skipped, so events == ingested + skipped + unresolved.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["skipped"], 1)
        self.assertEqual(response.json()["events"], 1)
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.notify.delay.assert_not_called()

    def test_a_broker_outage_still_answers_200(self):
        # The rows are committed; the console can still approve them. A 5xx here
        # would make X redeliver a post we already stored.
        self.notify.delay.side_effect = RuntimeError("broker down")

        with self.assertLogs("incident.views", level="ERROR") as logs:
            response = self._post(xaa_post_create_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ingested"], 1)
        self.assertEqual(SocialMediaLink.objects.count(), 1)
        self.assertTrue(any("enqueue" in line for line in logs.output))

    def test_two_posts_in_one_delivery_are_ingested_and_notified_together(self):
        payload = {
            "for_user_id": WEBHOOK_AUTHOR_ID,
            "tweet_create_events": [
                {
                    "id": WEBHOOK_POST_ID,
                    "text": WEBHOOK_POST_TEXT,
                    "created_at": WEBHOOK_CREATED_AT,
                    "user_id": WEBHOOK_AUTHOR_ID,
                },
                {
                    "id": "1791552310047416321",
                    "text": "second post",
                    "created_at": WEBHOOK_CREATED_AT,
                    "user_id": WEBHOOK_AUTHOR_ID,
                },
            ],
        }

        with mock.patch.object(
            official_posts, "_resolve_user_id", return_value=WEBHOOK_AUTHOR_ID
        ):
            response = self._post(payload)

        self.assertEqual(response.json()["events"], 2)
        self.assertEqual(response.json()["ingested"], 2)
        self.assertEqual(SocialMediaLink.objects.count(), 2)
        # One enqueue for the delivery, carrying both ids — not one per post.
        self.notify.delay.assert_called_once()
        self.assertEqual(
            sorted(self.notify.delay.call_args.args[0]),
            sorted(SocialMediaLink.objects.values_list("id", flat=True)),
        )


class NotifyOfficialPostLinksTaskTests(TestCase):
    """The queued notification the webhook view hands its ids to."""

    def setUp(self):
        self.author = get_system_author()
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))
        ingest_posts(posts, handle="askrapidkl", author=self.author)
        self.ids = list(
            SocialMediaLink.objects.order_by("id").values_list("id", flat=True)
        )

    def test_it_sends_one_message_per_link(self):
        sender = fake_sender()

        with override_settings(TELEGRAM_ADMIN_CHAT_ID="-1001234"):
            with mock.patch("incident.tasks.send_message", sender):
                sent = notify_official_post_links(self.ids)

        self.assertEqual(sent, len(self.ids))
        self.assertEqual(len(sender.calls), len(self.ids))
        for call in sender.calls:
            self.assertEqual(call["chat_id"], "-1001234")
            self.assertEqual(call["parse_mode"], "HTML")
            self.assertIs(call["return_log"], True)
        # The join row is what makes the message reply-/approve-able.
        self.assertEqual(TelegramSocialMediaLinkLog.objects.count(), len(self.ids))

    def test_a_blank_admin_chat_id_is_a_no_op(self):
        sender = fake_sender()

        with override_settings(TELEGRAM_ADMIN_CHAT_ID=""):
            with mock.patch("incident.tasks.send_message", sender):
                sent = notify_official_post_links(self.ids)

        self.assertEqual(sent, 0)
        self.assertEqual(sender.calls, [])
        self.assertEqual(TelegramSocialMediaLinkLog.objects.count(), 0)

    def test_an_empty_id_list_is_a_no_op(self):
        sender = fake_sender()

        with override_settings(TELEGRAM_ADMIN_CHAT_ID="-1001234"):
            with mock.patch("incident.tasks.send_message", sender):
                sent = notify_official_post_links([])

        self.assertEqual(sent, 0)
        self.assertEqual(sender.calls, [])

    def test_a_failing_send_is_contained_and_the_rows_survive(self):
        sender = fake_sender(outcomes=[RuntimeError("bot down")] * len(self.ids))

        with override_settings(TELEGRAM_ADMIN_CHAT_ID="-1001234"):
            with mock.patch("incident.tasks.send_message", sender):
                with self.assertLogs("incident.tasks", level="WARNING"):
                    sent = notify_official_post_links(self.ids)

        self.assertEqual(sent, 0)
        self.assertEqual(SocialMediaLink.objects.count(), len(self.ids))

    def test_an_unknown_id_is_simply_ignored(self):
        sender = fake_sender()

        with override_settings(TELEGRAM_ADMIN_CHAT_ID="-1001234"):
            with mock.patch("incident.tasks.send_message", sender):
                sent = notify_official_post_links([*self.ids, 10**9])

        # One message per link that exists, and no error for the one that does not.
        self.assertEqual(sent, len(self.ids))


class XWebhookCommandTests(TestCase):
    """The operator's registration lever. Every HTTP call is mocked — this
    command is the one surface that talks to X's management API, and the bearer
    token must be asserted absent from every byte of output."""

    TOKEN = "test-app-only-bearer-token"
    SETTINGS = {
        "X_API_BEARER_TOKEN": TOKEN,
        "X_API_OAUTH2_CLIENT_SECRET": TEST_OAUTH2_SECRET,
        "X_API_SECRET_KEY": TEST_LEGACY_SECRET,
        "OFFICIAL_POST_HANDLES": ["askrapidkl", "myrapidkl"],
    }

    def _run(self, *args, **kwargs):
        out, err = StringIO(), StringIO()
        call_command("x_webhook", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    @staticmethod
    def _x_api(responses):
        """A ``requests.request`` stand-in returning ``responses`` in order."""
        return mock.Mock(side_effect=responses)

    def _patched(self, responses):
        return mock.patch(
            "incident.management.commands.x_webhook.requests.request",
            self._x_api(responses),
        )

    def test_register_reports_the_id_and_validity(self):
        payload = {
            "data": {
                "id": "18923",
                "url": "https://api.x/webhooks/x-api",
                "valid": True,
            }
        }

        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(201, payload)]) as request:
                out, _ = self._run("register", "https://api.x/webhooks/x-api")

        self.assertIn("id=18923", out)
        self.assertIn("valid=True", out)
        method, url = request.call_args.args[:2]
        self.assertEqual((method, url), ("POST", "https://api.x.com/2/webhooks"))
        self.assertEqual(
            request.call_args.kwargs["json"], {"url": "https://api.x/webhooks/x-api"}
        )
        # The bearer is sent in the header and printed nowhere.
        self.assertEqual(
            request.call_args.kwargs["headers"],
            {"Authorization": f"Bearer {self.TOKEN}"},
        )
        self.assertNotIn(self.TOKEN, out)

    def test_register_warns_when_the_webhook_is_not_valid_yet(self):
        payload = {
            "data": {
                "id": "18923",
                "url": "https://api.x/webhooks/x-api",
                "valid": False,
            }
        }

        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(201, payload)]):
                out, err = self._run("register", "https://api.x/webhooks/x-api")

        self.assertIn("valid=False", out)
        self.assertIn("CRC", err)

    def test_register_rejects_a_non_https_url_without_calling_x(self):
        with override_settings(**self.SETTINGS):
            with self._patched([]) as request:
                with self.assertRaises(CommandError) as caught:
                    self._run("register", "http://api.x/webhooks/x-api")

        self.assertIn("HTTPS", str(caught.exception))
        request.assert_not_called()

    def test_register_needs_exactly_one_url(self):
        with override_settings(**self.SETTINGS):
            with self.assertRaises(CommandError) as caught:
                self._run("register")

        self.assertIn("exactly one argument", str(caught.exception))

    def test_list_prints_every_webhook(self):
        payload = {
            "data": [
                {
                    "id": "18923",
                    "url": "https://a.example/webhooks/x-api",
                    "valid": True,
                },
                {
                    "id": "18924",
                    "url": "https://b.example/webhooks/x-api",
                    "valid": False,
                },
            ]
        }

        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(200, payload)]) as request:
                out, _ = self._run("list")

        self.assertIn("id=18923", out)
        self.assertIn("https://b.example/webhooks/x-api", out)
        self.assertEqual(
            request.call_args.args[:2], ("GET", "https://api.x.com/2/webhooks")
        )

    def test_list_says_so_when_nothing_is_registered(self):
        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(200, {"data": []})]):
                out, _ = self._run("list")

        self.assertIn("no webhooks are registered", out)

    def test_delete_confirms_the_removal(self):
        with override_settings(**self.SETTINGS):
            with self._patched(
                [fake_x_response(200, {"data": {"deleted": True}})]
            ) as request:
                out, _ = self._run("delete", "18923")

        self.assertIn("deleted webhook id=18923", out)
        self.assertEqual(
            request.call_args.args[:2],
            ("DELETE", "https://api.x.com/2/webhooks/18923"),
        )

    def test_revalidate_puts_the_webhook(self):
        with override_settings(**self.SETTINGS):
            with self._patched(
                [fake_x_response(200, {"data": {"valid": True}})]
            ) as request:
                out, _ = self._run("revalidate", "18923")

        self.assertIn("revalidated webhook id=18923 valid=True", out)
        self.assertEqual(
            request.call_args.args[:2], ("PUT", "https://api.x.com/2/webhooks/18923")
        )

    def test_subscribe_creates_one_subscription_per_handle(self):
        with override_settings(**self.SETTINGS):
            with (
                mock.patch.object(
                    official_posts, "_resolve_user_id", side_effect=["111", "222"]
                ),
                # One scripted response per handle: a second call with an empty
                # script would be a StopIteration, not a silent pass.
                self._patched(
                    [
                        fake_x_response(200, {"data": {"id": "5001"}}),
                        fake_x_response(200, {"data": {"id": "5002"}}),
                    ]
                ) as request,
            ):
                out, _ = self._run(
                    "subscribe", "askrapidkl", "myrapidkl", "--webhook-id", "18923"
                )

        self.assertEqual(request.call_count, 2)
        first, second = request.call_args_list
        self.assertEqual(first.args[1], "https://api.x.com/2/activity/subscriptions")
        self.assertEqual(
            first.kwargs["json"],
            {
                "event_type": "post.create",
                "filter": {"user_id": "111"},
                "webhook_id": "18923",
                "tag": "official-posts",
            },
        )
        self.assertEqual(second.kwargs["json"]["filter"], {"user_id": "222"})
        self.assertIn("subscribed handle=askrapidkl user_id=111", out)
        self.assertNotIn(self.TOKEN, out)

    def test_subscribe_strips_a_leading_at_sign(self):
        with override_settings(**self.SETTINGS):
            with (
                mock.patch.object(
                    official_posts, "_resolve_user_id", return_value="111"
                ),
                self._patched([fake_x_response(200, {"data": {"id": "5001"}})]),
            ):
                out, _ = self._run("subscribe", "@askrapidkl", "--webhook-id", "18923")

        self.assertIn("handle=askrapidkl", out)

    def test_subscribe_needs_at_least_one_handle(self):
        with override_settings(**self.SETTINGS):
            with self._patched([]) as request:
                with self.assertRaises(CommandError) as caught:
                    self._run("subscribe", "--webhook-id", "18923")

        self.assertIn("at least one HANDLE", str(caught.exception))
        request.assert_not_called()

    def test_subscribe_uses_the_only_registered_webhook_when_none_is_given(self):
        with override_settings(**self.SETTINGS):
            with (
                mock.patch.object(
                    official_posts, "_resolve_user_id", return_value="111"
                ),
                self._patched(
                    [
                        fake_x_response(
                            200, {"data": [{"id": "18923", "valid": True}]}
                        ),
                        fake_x_response(200, {"data": {"id": "5001"}}),
                    ]
                ) as request,
            ):
                out, _ = self._run("subscribe", "askrapidkl")

        self.assertIn("subscribing to webhook id=18923", out)
        self.assertEqual(request.call_args.kwargs["json"]["webhook_id"], "18923")

    def test_subscribe_refuses_to_guess_between_several_webhooks(self):
        payload = {"data": [{"id": "18923"}, {"id": "18924"}]}

        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(200, payload)]):
                with self.assertRaises(CommandError) as caught:
                    self._run("subscribe", "askrapidkl")

        # Both ids are named so the operator can pick one; nothing was created.
        self.assertIn("18923, 18924", str(caught.exception))
        self.assertIn("--webhook-id", str(caught.exception))

    def test_subscribe_tells_the_operator_to_register_first(self):
        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(200, {"data": []})]):
                with self.assertRaises(CommandError) as caught:
                    self._run("subscribe", "askrapidkl")

        self.assertIn("register", str(caught.exception))

    def test_a_missing_bearer_token_is_a_command_error(self):
        with override_settings(X_API_BEARER_TOKEN=""):
            with self._patched([]) as request:
                with self.assertRaises(CommandError) as caught:
                    self._run("list")

        self.assertIn("X_API_BEARER_TOKEN", str(caught.exception))
        request.assert_not_called()

    def test_a_crc_validation_failure_is_reported_sanitized(self):
        payload = {
            "errors": [
                {
                    "title": "CrcValidationFailed",
                    "detail": f"the request was signed with {self.TOKEN}",
                }
            ]
        }

        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(403, payload)]):
                with self.assertRaises(CommandError) as caught:
                    self._run("register", "https://api.x/webhooks/x-api")

        message = str(caught.exception)
        self.assertIn("HTTP 403", message)
        self.assertIn("CrcValidationFailed", message)
        # The upstream detail is never quoted and the token never appears.
        self.assertNotIn(self.TOKEN, message)
        self.assertNotIn("signed with", message)

    def test_a_url_validation_failure_is_reported_by_title(self):
        payload = {"errors": [{"title": "UrlValidationFailed", "detail": "port"}]}

        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(400, payload)]):
                with self.assertRaises(CommandError) as caught:
                    self._run("register", "https://api.x/webhooks/x-api")

        self.assertIn("UrlValidationFailed", str(caught.exception))

    def test_a_timeout_is_a_command_error_without_the_token(self):
        import requests as requests_module

        with override_settings(**self.SETTINGS):
            with mock.patch(
                "incident.management.commands.x_webhook.requests.request",
                side_effect=requests_module.Timeout(),
            ):
                with self.assertRaises(CommandError) as caught:
                    self._run("list")

        self.assertIn("timed out", str(caught.exception))
        self.assertNotIn(self.TOKEN, str(caught.exception))

    def test_an_unparseable_response_is_a_command_error(self):
        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(200, unparseable=True)]):
                with self.assertRaises(CommandError) as caught:
                    self._run("list")

        self.assertIn("not valid JSON", str(caught.exception))

    def test_a_registration_that_returns_no_id_is_a_command_error(self):
        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(201, {"data": {}})]):
                with self.assertRaises(CommandError) as caught:
                    self._run("register", "https://api.x/webhooks/x-api")

        self.assertIn("no webhook id", str(caught.exception))

    def test_an_unresolvable_handle_is_a_sanitized_command_error(self):
        with override_settings(**self.SETTINGS):
            with (
                mock.patch.object(
                    official_posts,
                    "_resolve_user_id",
                    side_effect=OfficialPostFetchError("X API error: HTTP 404"),
                ),
                self._patched([]) as request,
            ):
                with self.assertRaises(CommandError) as caught:
                    self._run("subscribe", "nope", "--webhook-id", "18923")

        self.assertIn("HTTP 404", str(caught.exception))
        self.assertNotIn(self.TOKEN, str(caught.exception))
        request.assert_not_called()

    def test_the_help_text_states_the_registration_rules(self):
        from incident.management.commands.x_webhook import Command

        help_text = Command.help
        self.assertIn("HTTPS", help_text)
        self.assertIn("10 seconds", help_text)
        self.assertIn("CrcValidationFailed", help_text)
        self.assertIn("UrlValidationFailed", help_text)
