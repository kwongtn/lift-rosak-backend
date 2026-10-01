import base64
import copy
import csv
import html
import json
import os
import sys
import tempfile
from contextlib import ExitStack
from datetime import UTC, date, datetime, time, timedelta
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
    Agency,
    CalendarIncident,
    CalendarIncidentCategory,
    CalendarIncidentChronology,
    CalendarIncidentMedia,
    LineStatusReport,
    SocialMediaLink,
    SocMedAccount,
    StationIncident,
    VehicleIncident,
)
from incident.services import official_posts
from incident.services.errors import OfficialPostFetchError
from incident.services.line_status import load_line_status_history
from incident.services.official_posts import (
    UNASSIGNED_AGENCY_NAME,
    RawPost,
    ensure_user_profile,
    fetch_user_posts,
    get_system_author,
    ingest_posts,
    latest_post_id,
    load_fixture_posts,
    resolve_account,
    sync_account_profiles,
    tweet_to_raw_post,
)
from incident.services.urls import canonicalize_url
from incident.services.x_webhooks import (
    _users_by_id,
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

#: The registry seeded by incident migration 0029: two agencies, the two
#: tracked X accounts (with their provider user ids baked in, so no profile
#: lookup is needed against seeded rows), and the ``system:official-ingest``
#: author. Tests that pin-hits these constants stay robust to any later
#: cosmetic seed edit.
PRASARANA_AGENCY_NAME = "Prasarana Malaysia Berhad"
SEEDED_ASKRAPIDKL_USER_ID = "2934256998"
SEEDED_MYRAPIDKL_USER_ID = "1375351250745618432"

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
            # ``created`` comes from TimeStampedModel (auto_now_add) and cannot
            # be set through create(). ``occurred_at`` IS the column the feed
            # orders and windows on (the ordering migration), so the fixtures
            # move both: setting only ``created`` would now be a no-op as far as
            # the feed is concerned.
            SocialMediaLink.objects.filter(id=link.id).update(
                created=created, occurred_at=created
            )
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


class PublicFeedLastWeekAndDayAlignTests(TestCase):
    """``lastWeekOnly`` (the last six COMPLETED calendar days — today excluded
    unless ``displayTodayInLastWeek``) and ``alignPageToDay`` (a page never ends
    mid-day; a whole day lands together, so a page may exceed ``first`` — no
    cap)."""

    query = """
        query Feed(
            $first: Int
            $after: String
            $lastWeekOnly: Boolean
            $currentServiceDayOnly: Boolean
            $alignPageToDay: Boolean
            $displayTodayInLastWeek: Boolean
        ) {
            publicSocialMediaLinks(
                first: $first
                after: $after
                lastWeekOnly: $lastWeekOnly
                currentServiceDayOnly: $currentServiceDayOnly
                alignPageToDay: $alignPageToDay
                displayTodayInLastWeek: $displayTodayInLastWeek
            ) {
                totalCount
                edges { node { id } cursor }
                pageInfo { hasNextPage endCursor }
            }
        }
    """

    def setUp(self):
        self.user = User.objects.create(firebase_id="feed-align-user")

    def _link(self, slug, created):
        link = SocialMediaLink.objects.create(
            url=f"https://example.com/{slug}", title=slug, user=self.user
        )
        # created comes from TimeStampedModel (auto_now_add): it cannot be set
        # through create(), only updated afterwards. The feed orders, windows
        # and aligns days on ``occurred_at`` (the ordering migration), so the
        # fixture moves both columns; keeping them equal is what makes these
        # tests still be about the feature they were written for. The
        # disagreeing-columns version of the same contract lives in
        # tests/incident/test_social_link_feed_ordering.py.
        SocialMediaLink.objects.filter(pk=link.pk).update(
            created=created, occurred_at=created
        )
        link.refresh_from_db()
        return link

    def _feed(self, **variables):
        result = execute_graphql(self.query, variables=variables)
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return result.data["publicSocialMediaLinks"]

    def _ids(self, feed):
        return [edge["node"]["id"] for edge in feed["edges"]]

    def test_last_week_only_window_opens_at_midnight_six_days_ago(self):
        """The LOWER bound, on the inclusive window the flag restores.

        The fixture carries a today row on purpose: with the flag on, the
        inclusive seven-day window is the whole claim (six days ago through
        today), so the boundary row proves the lower end and the today row the
        upper one. The default's exclusion of today is a separate test — mixing
        the two here would let a broken exclusion still pass this assertion.
        """
        now = timezone.now()
        start = datetime.combine((now - timedelta(days=6)).date(), time.min)
        boundary = self._link("week-boundary", start)
        today = self._link("week-today", now)
        self._link("week-before", start - timedelta(minutes=1))
        self._link("much-older", now - timedelta(days=30))

        feed = self._feed(first=10, lastWeekOnly=True, displayTodayInLastWeek=True)

        # The exact 00:00 six-days-ago row and today's row are in; 23:59 seven
        # days ago and the older row are not.
        self.assertEqual(self._ids(feed), [str(today.id), str(boundary.id)])
        self.assertEqual(feed["totalCount"], 2)
        # The window narrows the feed, it does not delete the other rows.
        self.assertEqual(SocialMediaLink.objects.count(), 4)

    def test_last_week_only_excludes_today_by_default(self):
        """The new default: a "last week" view does not show the day in progress."""
        now = timezone.now()
        start = datetime.combine((now - timedelta(days=6)).date(), time.min)
        yesterday_last_minute = self._link(
            "yesterday-2359",
            datetime.combine(now.date() - timedelta(days=1), time(23, 59)),
        )
        boundary = self._link("six-days-ago", start)
        today = self._link("today-noon", now)

        feed = self._feed(first=10, lastWeekOnly=True)

        # Yesterday 23:59 is the last minute of the last completed day and stays;
        # the six-days-ago boundary is the exact opening minute.
        self.assertEqual(
            self._ids(feed), [str(yesterday_last_minute.id), str(boundary.id)]
        )
        self.assertGreaterEqual(
            today.occurred_at, datetime.combine(now.date(), time.min)
        )

    def test_a_link_at_exactly_today_midnight_is_excluded(self):
        """The bound is INCLUSIVE of midnight, so a row stamped exactly 00:00 is out."""
        now = timezone.now()
        today_midnight = datetime.combine(now.date(), time.min)
        at_midnight = self._link("today-midnight", today_midnight)
        a_moment_earlier = self._link(
            "just-before-midnight", today_midnight - timedelta(minutes=1)
        )

        excluded = self._feed(first=10, lastWeekOnly=True)

        self.assertEqual(self._ids(excluded), [str(a_moment_earlier.id)])
        self.assertNotIn(str(at_midnight.id), self._ids(excluded))

    def test_display_today_in_last_week_restores_the_inclusive_window(self):
        """The single opt-out puts today back and nothing else changes."""
        now = timezone.now()
        today = self._link("today-with-flag", now)
        older = self._link(
            "yesterday-with-flag",
            datetime.combine(now.date() - timedelta(days=1), time(9, 0)),
        )

        with_flag = self._feed(first=10, lastWeekOnly=True, displayTodayInLastWeek=True)

        self.assertEqual(self._ids(with_flag), [str(today.id), str(older.id)])
        # And the default really would have dropped it, so the assertion is not
        # vacuously satisfied by a flag that is silently ignored.
        self.assertNotIn(
            str(today.id), self._ids(self._feed(first=10, lastWeekOnly=True))
        )

    def test_total_count_reflects_the_today_exclusion(self):
        """The count is taken AFTER the windows, so it reports the closed range."""
        now = timezone.now()
        for index in range(2):
            self._link(f"count-week-{index}", now - timedelta(days=index + 1))
        for index in range(3):
            self._link(f"count-today-{index}", now)

        default_feed = self._feed(first=1, lastWeekOnly=True)
        inclusive_feed = self._feed(
            first=1, lastWeekOnly=True, displayTodayInLastWeek=True
        )

        self.assertEqual(default_feed["totalCount"], 2)
        self.assertEqual(inclusive_feed["totalCount"], 5)
        # ``first`` still bounds the page; only the count moves.
        self.assertEqual(len(default_feed["edges"]), 1)

    def test_the_today_flag_does_nothing_when_last_week_only_is_off(self):
        """The flag only ever lifts an upper bound, and there is no other one."""
        now = timezone.now()
        today = self._link("flag-off-today", now)
        older = self._link("flag-off-older", now - timedelta(days=40))

        without = self._feed(first=10, displayTodayInLastWeek=False)
        with_flag = self._feed(first=10, displayTodayInLastWeek=True)
        unfiltered = self._feed(first=10)

        expected = [str(today.id), str(older.id)]
        self.assertEqual(self._ids(without), expected)
        self.assertEqual(self._ids(with_flag), expected)
        self.assertEqual(without["totalCount"], 2)
        self.assertEqual(with_flag["totalCount"], unfiltered["totalCount"])

    def test_both_windows_together_intersect_and_need_the_today_flag(self):
        """``currentServiceDayOnly`` + ``lastWeekOnly`` INTERSECT, today excluded.

        The two windows open at different instants on the same column — the
        service day at 03:00, ``lastWeekOnly`` at calendar midnight six days ago —
        and ``lastWeekOnly`` additionally CLOSES at today's midnight unless
        ``displayTodayInLastWeek`` says otherwise. Composed, the range is
        therefore ``[service_day_start, today 00:00)``, which is empty for every
        minute between 03:00 and midnight and holds only the 03:00-03:59 sliver of
        the current service day before that. That intersection is the DECIDED
        behaviour, not an accident: the two flags are independent filters on one
        queryset, so a caller wanting the old "current service day" reading
        through the pair must set ``displayTodayInLastWeek: true``.

        The fixture is 05:00 today, chosen so the claim is clock-independent: it is
        at/after the service-day lower bound at every hour of the day (a service
        day never starts before the calendar day it starts in — before 03:00 the
        lower bound is *yesterday's* 03:00) and at/after ``last_week_start`` always,
        while today's midnight upper bound rejects it at every hour.
        """
        now = timezone.now()
        this_morning = self._link(
            "service-day-today",
            datetime.combine(now.date(), time.min) + timedelta(hours=5),
        )

        # The service-day window alone admits it...
        self.assertIn(
            str(this_morning.id),
            self._ids(self._feed(first=10, currentServiceDayOnly=True)),
        )
        # ...the default intersection does not, because it closes at midnight...
        intersected = self._feed(
            first=10, currentServiceDayOnly=True, lastWeekOnly=True
        )
        self.assertEqual(self._ids(intersected), [])
        self.assertEqual(intersected["totalCount"], 0)
        # ...and the flag restores the service-day meaning inside the pair.
        inclusive = self._feed(
            first=10,
            currentServiceDayOnly=True,
            lastWeekOnly=True,
            displayTodayInLastWeek=True,
        )
        self.assertEqual(self._ids(inclusive), [str(this_morning.id)])
        self.assertEqual(inclusive["totalCount"], 1)

    def test_align_page_to_day_false_returns_exactly_first_rows(self):
        now = timezone.now()
        for index in range(4):
            self._link(f"no-align-{index}", now)

        feed = self._feed(first=2, alignPageToDay=False)

        self.assertEqual(len(feed["edges"]), 2)
        self.assertTrue(feed["pageInfo"]["hasNextPage"])

    def test_align_extends_to_finish_the_day_and_cursor_continues(self):
        a_date = timezone.now().date()
        b_date = a_date - timedelta(days=1)
        # Distinct within-day timestamps so the continuation is driven by the
        # ``created__lt`` keyset branch, not only the id tiebreak.
        day_a = [
            self._link("day-a-0", datetime.combine(a_date, time(13, 0))),
            self._link("day-a-1", datetime.combine(a_date, time(12, 0))),
            self._link("day-a-2", datetime.combine(a_date, time(11, 0))),
            self._link("day-a-3", datetime.combine(a_date, time(10, 0))),
        ]
        day_b = [
            self._link(f"day-b-{index}", datetime.combine(b_date, time(9, 0)))
            for index in range(2)
        ]

        page_one = self._feed(first=2, alignPageToDay=True)

        # All four of day A land together, exceeding ``first``.
        self.assertEqual(len(page_one["edges"]), 4)
        self.assertEqual(set(self._ids(page_one)), {str(link.id) for link in day_a})
        self.assertTrue(page_one["pageInfo"]["hasNextPage"])
        self.assertEqual(
            page_one["pageInfo"]["endCursor"], page_one["edges"][-1]["cursor"]
        )

        page_two = self._feed(
            first=2, after=page_one["pageInfo"]["endCursor"], alignPageToDay=True
        )

        self.assertEqual(set(self._ids(page_two)), {str(link.id) for link in day_b})
        self.assertFalse(page_two["pageInfo"]["hasNextPage"])

    def test_align_returns_the_whole_final_day_with_no_cap(self):
        day = timezone.now().date()
        # Insertion order fixes ids. only-day-2/only-day-3 share 10:00 so the
        # extension exercises both the ``created__lt`` continuation and the
        # ``id__lt`` tiebreak (only-day-2 has the higher id and is the lookahead).
        links = [
            self._link("only-day-0", datetime.combine(day, time(12, 0))),
            self._link("only-day-1", datetime.combine(day, time(11, 0))),
            self._link("only-day-2", datetime.combine(day, time(10, 0))),
            self._link("only-day-3", datetime.combine(day, time(10, 0))),
            self._link("only-day-4", datetime.combine(day, time(9, 0))),
        ]

        feed = self._feed(first=2, alignPageToDay=True)

        self.assertEqual(len(feed["edges"]), 5)
        self.assertEqual(set(self._ids(feed)), {str(link.id) for link in links})
        self.assertFalse(feed["pageInfo"]["hasNextPage"])

    def test_align_leaves_a_page_ending_on_a_day_boundary_untouched(self):
        a_date = timezone.now().date()
        b_date = a_date - timedelta(days=1)
        day_a = [
            self._link("boundary-a-0", datetime.combine(a_date, time(12, 0))),
            self._link("boundary-a-1", datetime.combine(a_date, time(11, 0))),
        ]
        self._link("boundary-b", datetime.combine(b_date, time(12, 0)))

        feed = self._feed(first=2, alignPageToDay=True)

        # The lookahead is on the next day, so there is nothing to extend.
        self.assertEqual(len(feed["edges"]), 2)
        self.assertEqual(set(self._ids(feed)), {str(link.id) for link in day_a})
        self.assertTrue(feed["pageInfo"]["hasNextPage"])

    def test_align_last_page_smaller_than_first_is_returned_whole(self):
        a_date = timezone.now().date()
        b_date = a_date - timedelta(days=1)
        for index in range(3):
            self._link(f"tail-a-{index}", datetime.combine(a_date, time(12 - index, 0)))
        for index in range(2):
            self._link(f"tail-b-{index}", datetime.combine(b_date, time(12 - index, 0)))

        feed = self._feed(first=5, alignPageToDay=True)

        self.assertEqual(len(feed["edges"]), 5)
        self.assertFalse(feed["pageInfo"]["hasNextPage"])

    def test_last_week_only_and_align_page_to_day_combine(self):
        now = timezone.now()
        start = datetime.combine((now - timedelta(days=6)).date(), time.min)
        today = now.date()
        in_week = [
            self._link(f"in-week-{index}", datetime.combine(today, time(12 - index, 0)))
            for index in range(3)
        ]
        self._link("out-of-week", start - timedelta(days=1))

        # ``displayTodayInLastWeek`` is what puts today's three rows inside the
        # window: the default excludes today, and this test is about the two
        # features composing, not about the exclusion (covered above). Without it
        # the page would be empty and the alignment would have nothing to align.
        feed = self._feed(
            first=2,
            lastWeekOnly=True,
            alignPageToDay=True,
            displayTodayInLastWeek=True,
        )

        # The day is completed inside the window; the older row is filtered out
        # before either feature so it can neither page nor inflate the count.
        self.assertEqual(set(self._ids(feed)), {str(link.id) for link in in_week})
        self.assertEqual(feed["totalCount"], 3)
        self.assertFalse(feed["pageInfo"]["hasNextPage"])

    def test_the_align_day_completion_still_runs_after_the_today_exclusion(self):
        """Yesterday is the newest day the default window still shows, and it must
        still be completed as a whole day — the exclusion moves the newest day,
        it does not break the alignment that keys on it."""
        yesterday = timezone.now().date() - timedelta(days=1)
        day = [
            self._link(
                f"yesterday-align-{index}",
                datetime.combine(yesterday, time(13 - index, 0)),
            )
            for index in range(3)
        ]
        self._link("today-align-excluded", timezone.now())

        feed = self._feed(first=2, lastWeekOnly=True, alignPageToDay=True)

        self.assertEqual(set(self._ids(feed)), {str(link.id) for link in day})
        self.assertEqual(feed["totalCount"], 3)
        self.assertFalse(feed["pageInfo"]["hasNextPage"])

    def test_negative_first_returns_an_empty_page_without_error(self):
        self._link("negative-first", timezone.now())

        feed = self._feed(first=-1)

        # Legacy behaviour: an invalid negative ``first`` yields an empty page,
        # not an IndexError/500.
        self.assertEqual(feed["edges"], [])
        self.assertFalse(feed["pageInfo"]["hasNextPage"])
        self.assertIsNone(feed["pageInfo"]["endCursor"])
        self.assertEqual(feed["totalCount"], 1)

    def test_total_count_respects_the_window_and_ignores_alignment(self):
        now = timezone.now()
        start = datetime.combine((now - timedelta(days=6)).date(), time.min)
        for index in range(4):
            self._link(f"count-week-{index}", now)
        self._link("count-ancient", start - timedelta(days=10))

        # The four in-window rows are all today, so this is the *inclusive*
        # window: the flag is what keeps them, and the count is what has to agree
        # with the page under both alignment settings. (The default's exclusion
        # of today is pinned in the tests above.)
        aligned = self._feed(
            first=2, lastWeekOnly=True, alignPageToDay=True, displayTodayInLastWeek=True
        )
        plain = self._feed(
            first=2,
            lastWeekOnly=True,
            alignPageToDay=False,
            displayTodayInLastWeek=True,
        )

        self.assertEqual(aligned["totalCount"], 4)
        self.assertEqual(plain["totalCount"], 4)
        self.assertEqual(len(aligned["edges"]), 4)  # day completed
        self.assertEqual(len(plain["edges"]), 2)  # alignment off keeps first


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
        first = ingest_posts(self.posts, author=self.author)

        self.assertEqual(first.fetched, 2)
        self.assertEqual(first.created, 2)
        self.assertEqual(first.skipped, 0)
        self.assertEqual(first.duplicate_urls, 0)
        self.assertEqual(len(first.created_ids), 2)

        second = ingest_posts(self.posts, author=self.author)

        self.assertEqual(second.created, 0)
        self.assertEqual(second.skipped, 2)
        self.assertEqual(second.created_ids, ())
        self.assertEqual(
            SocialMediaLink.objects.filter(socmed_account__handle="askrapidkl").count(),
            2,
        )

    def test_same_url_under_a_second_handle_is_a_duplicate_url_not_a_twin(self):
        ingest_posts(self.posts, author=self.author)
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

        summary = ingest_posts([cross_account], author=self.author)

        self.assertEqual(summary.duplicate_urls, 1)
        self.assertEqual(summary.created, 0)
        self.assertEqual(SocialMediaLink.objects.count(), 2)
        # The existing row is left alone: not rewritten, not re-attributed.
        existing.refresh_from_db()
        self.assertEqual(existing.socmed_account.handle, "askrapidkl")
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

        ingest_posts([post], author=self.author)

        link = SocialMediaLink.objects.get(socmed_account__handle="askrapidkl")
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
        self.assertEqual(link.socmed_account.handle, "askrapidkl")
        self.assertEqual(link.post_id, "1791552310047416320")
        self.assertEqual(link.raw_payload, post.raw)
        self.assertEqual(
            link.normalized_url,
            canonicalize_url("https://x.com/askrapidkl/status/1791552310047416320"),
        )

    def test_latest_post_id_returns_the_highest_numeric_snowflake(self):
        askrapidkl = resolve_account(IngestPlatform.X, handle="askrapidkl")
        myrapidkl = resolve_account(IngestPlatform.X, handle="myrapidkl")
        self.assertIsNone(latest_post_id(askrapidkl))
        ingest_posts(self.posts, author=self.author)

        # The fixture's newest id is numerically the larger one, and a plain
        # lexicographic Max() would pick the smaller.
        self.assertEqual(latest_post_id(askrapidkl), "1791552408821972992")
        self.assertIsNone(latest_post_id(myrapidkl))

    def test_dry_run_counts_creations_but_writes_nothing(self):
        summary = ingest_posts(self.posts, author=self.author, dry_run=True)

        self.assertEqual(summary.fetched, 2)
        self.assertEqual(summary.created, 2)
        self.assertEqual(summary.created_ids, ())
        self.assertEqual(SocialMediaLink.objects.count(), 0)


class OfficialPostEntityDecodingTests(TestCase):
    """HTML entities are decoded once, at the ingest boundary.

    ``tweet_to_raw_post`` is the single mapping behind the poll, the fixture
    loader and the webhook parser, so a test here covers all three callers; the
    webhook case additionally asserts what the stored row looks like.
    """

    #: X sends ``&amp;``/``&lt;``/``&gt;``/``&quot;``/``&#39;`` and numeric
    #: references still encoded. The expected value is written out in full
    #: rather than computed with ``html.unescape``, so the test states the
    #: contract rather than restating the implementation.
    ENCODED = (
        "Jln &amp; LRT &lt;utara&gt; &quot;quote&quot; "
        "&#39;apostrophe&#39; &#8212; 2026"
    )
    DECODED = "Jln & LRT <utara> \"quote\" 'apostrophe' — 2026"

    def setUp(self):
        self.author = get_system_author()

    def _tweet(self, text, *, post_id="1791552310047416320"):
        return {
            "id": post_id,
            "text": text,
            "created_at": "2026-09-28T04:05:00.000Z",
            "author_id": "2244994945",
        }

    def test_the_shared_mapping_decodes_named_and_numeric_entities(self):
        post = tweet_to_raw_post(self._tweet(self.ENCODED), "askrapidkl")

        self.assertEqual(post.text, self.DECODED)
        # The provider object is untouched, so the stored payload keeps the
        # encoded original for export fidelity.
        self.assertEqual(post.raw["text"], self.ENCODED)

    def test_a_plain_ampersand_is_left_exactly_as_sent(self):
        plain = "Taman Bahagia & USJ 21, Selangor."

        post = tweet_to_raw_post(self._tweet(plain), "askrapidkl")

        self.assertEqual(post.text, plain)

    def test_text_is_decoded_exactly_once(self):
        # ``&amp;amp;`` is an escaped entity, not a literal ``&amp;``. Decoding
        # twice would store ``&`` and quietly corrupt the post.
        post = tweet_to_raw_post(self._tweet("a &amp;amp; b"), "askrapidkl")

        self.assertEqual(post.text, "a &amp; b")

    def test_the_fixture_loader_decodes_too(self):
        # The other two callers of the shared mapping, so both store the same
        # characters: a saved payload goes through the identical code path.
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))

        # The fixture holds a plain ``&``; decoding must leave it alone.
        self.assertIn("&", posts[0].text)
        self.assertNotIn("&amp;", posts[0].text)

    def test_the_stored_row_is_decoded_and_the_raw_payload_is_not(self):
        ingest_posts(
            [tweet_to_raw_post(self._tweet(self.ENCODED), "askrapidkl")],
            author=self.author,
        )

        link = SocialMediaLink.objects.get(socmed_account__handle="askrapidkl")
        self.assertEqual(link.description, self.DECODED)
        self.assertEqual(link.title, self.DECODED[:256])
        self.assertEqual(link.raw_payload["text"], self.ENCODED)

    def test_title_truncation_counts_decoded_characters(self):
        # Longer than the CharField(256) once decoded: truncation must measure
        # the decoded text, so ``description`` keeps every character and
        # ``title`` is the first 256 of what the operator actually published.
        decoded = "&" * 40 + "ekor " * 80
        encoded = "&amp;" * 40 + "ekor " * 80
        ingest_posts(
            [tweet_to_raw_post(self._tweet(encoded), "askrapidkl")],
            author=self.author,
        )

        link = SocialMediaLink.objects.get(socmed_account__handle="askrapidkl")
        self.assertEqual(link.description, decoded)
        self.assertEqual(link.title, decoded[:256])
        self.assertEqual(len(link.title), 256)


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

    @override_settings(
        OFFICIAL_POST_INGESTION_ENABLED=True,
        OFFICIAL_POST_POLLING_ENABLED=True,
        X_API_BEARER_TOKEN="t",
    )
    def test_only_enabled_registry_accounts_are_polled(self):
        # ``is_enabled`` gates POLLING only (the webhook path ingests
        # regardless); an account flipped off must leave the task entirely.
        SocMedAccount.objects.filter(handle="myrapidkl").update(is_enabled=False)
        posts = load_fixture_posts(str(SAMPLE_FIXTURE))

        with mock.patch("incident.tasks.fetch_user_posts", return_value=posts) as fetch:
            result = ingest_official_posts()

        self.assertEqual(
            [call.args[0].handle for call in fetch.call_args_list], ["askrapidkl"]
        )
        self.assertEqual(result["handles"]["askrapidkl"]["created"], 2)
        self.assertNotIn("myrapidkl", result["handles"])

    @override_settings(
        OFFICIAL_POST_INGESTION_ENABLED=True,
        OFFICIAL_POST_POLLING_ENABLED=True,
        X_API_BEARER_TOKEN="t",
    )
    def test_an_empty_registry_returns_the_uniform_zero_totals_shape(self):
        SocMedAccount.objects.all().delete()
        with mock.patch(
            "incident.tasks.fetch_user_posts",
            side_effect=AssertionError("fetch called"),
        ) as fetch:
            result = ingest_official_posts()

        # The registry is the single source of truth for what to poll; an empty
        # one must still give callers the shape they can sum over.
        self.assertEqual(
            result,
            {
                "handles": {},
                "fetched": 0,
                "created": 0,
                "skipped": 0,
                "duplicate_urls": 0,
            },
        )
        fetch.assert_not_called()
        self.assertEqual(SocialMediaLink.objects.count(), 0)


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
    """The pagination walk is bounded by ``limit`` *and* by a page cap (4.8.6).

    ``fetch_user_posts`` now takes a registry account, not a handle. The seeded
    accounts already carry their ``user_id``, so no profile lookup is ever made
    against them (the one test that needs the lookup builds a fresh account).
    """

    def setUp(self):
        # A seeded account carries its user_id, so the fetch skips the profile
        # lookup entirely and starts straight on the tweets endpoint.
        self.account = resolve_account(IngestPlatform.X, handle="askrapidkl")
        self.assertIsNotNone(self.account)

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
            posts = fetch_user_posts(self.account, limit=3)
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
            posts = fetch_user_posts(self.account, limit=10_000)
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
                self.account,
                since_id="1791552310047416320",
                start_time=datetime(2026, 9, 1, tzinfo=UTC),
                end_time=datetime(2026, 9, 2, 23, 59, 59, tzinfo=UTC),
                limit=5,
                exclude_retweets=True,
            )

        tweets_url, params, headers = captured[-1]
        self.assertIn(f"/2/users/{self.account.user_id}/tweets", tweets_url)
        self.assertEqual(params["since_id"], "1791552310047416320")
        self.assertEqual(params["start_time"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(params["end_time"], "2026-09-02T23:59:59+00:00")
        self.assertEqual(params["exclude"], "retweets")
        self.assertEqual(params["max_results"], 5)
        self.assertEqual(headers["Authorization"], "Bearer test-bearer-token")

    def test_a_missing_user_id_is_resolved_once_and_persisted(self):
        # Not a seeded row: ``user_id`` stays empty, which is the only state
        # that triggers the profile lookup. The registry is the source of
        # truth, so the id is resolved through ``ensure_user_profile`` and
        # persisted once — a second fetch must not pay the lookup again.
        agency = Agency.objects.get(name=PRASARANA_AGENCY_NAME)
        account = SocMedAccount.objects.create(
            agency=agency,
            platform=IngestPlatform.X,
            handle="freshaccount",
            user_id="",
        )
        username_lookups = []

        def fake_get_json(url, *, params, headers, context):
            if "by/username" in url:
                username_lookups.append(url)
                return {
                    "data": {
                        "id": "424242",
                        "name": "Fresh Account",
                        "username": "freshaccount",
                    }
                }
            return {"data": []}

        with mock.patch.object(official_posts, "_get_json", side_effect=fake_get_json):
            fetch_user_posts(account, limit=1)
            fetch_user_posts(account, limit=1)

        # One profile lookup for the whole life of the account, not per fetch.
        self.assertEqual(len(username_lookups), 1)
        account.refresh_from_db()
        self.assertEqual(account.user_id, "424242")
        self.assertEqual(account.display_name, "Fresh Account")
        self.assertIsNotNone(account.resolved_at)


class SocMedAccountRegistrySeedTests(TestCase):
    """Migration 0029's registry seed is present — and pinned, so a later seed
    edit that would break the pipeline is caught at the source instead of only
    in the dozens of behaviour tests that quietly depend on it."""

    def test_the_two_agencies_are_seeded(self):
        names = {agency.name for agency in Agency.objects.all()}
        self.assertIn(PRASARANA_AGENCY_NAME, names)
        self.assertIn(UNASSIGNED_AGENCY_NAME, names)

    def test_the_tracked_accounts_are_seeded_with_their_user_ids(self):
        accounts = {account.handle: account for account in SocMedAccount.objects.all()}
        self.assertIn("askrapidkl", accounts)
        self.assertIn("myrapidkl", accounts)
        self.assertEqual(accounts["askrapidkl"].user_id, SEEDED_ASKRAPIDKL_USER_ID)
        self.assertEqual(accounts["myrapidkl"].user_id, SEEDED_MYRAPIDKL_USER_ID)

    def test_the_seeded_payloads_match_a_live_profile_lookup_shape(self):
        # The provider ``data`` object is baked into the seed so staging/prod
        # cost no API call, and it matches the shape ``ensure_user_profile``
        # persists on a live lookup — seeding and resolving cannot diverge.
        account = SocMedAccount.objects.get(handle="askrapidkl")
        self.assertEqual(account.display_name, "Ask Rapid KL")
        self.assertIsInstance(account.raw_payload, dict)
        self.assertEqual(account.raw_payload["id"], SEEDED_ASKRAPIDKL_USER_ID)
        self.assertEqual(account.raw_payload["username"], "askrapidkl")
        self.assertIsNotNone(account.resolved_at)
        self.assertTrue(account.is_enabled)
        self.assertEqual(account.agency.name, PRASARANA_AGENCY_NAME)

    def test_the_system_author_is_seeded(self):
        self.assertIsNotNone(get_system_author())


class SocMedAccountRegistryTests(TestCase):
    """``resolve_account`` / ``ensure_user_profile`` / ``sync_account_profiles``:
    the DB registry is the single source of truth, ``resolve_account`` never
    calls the API, and the sole network lookup is ``ensure_user_profile``."""

    def test_lookup_finds_by_user_id_and_by_handle(self):
        by_user_id = resolve_account(
            IngestPlatform.X, user_id=SEEDED_ASKRAPIDKL_USER_ID
        )
        self.assertIsNotNone(by_user_id)
        self.assertEqual(by_user_id.handle, "askrapidkl")

        by_handle = resolve_account(IngestPlatform.X, handle="myrapidkl")
        self.assertIsNotNone(by_handle)
        self.assertEqual(by_handle.user_id, SEEDED_MYRAPIDKL_USER_ID)

    def test_a_hit_backfills_a_missing_user_id(self):
        # A row registered by handle alone (empty user_id) is backfilled when a
        # delivery carrying the id resolves to it — no second row, no API call.
        agency = Agency.objects.get(name=PRASARANA_AGENCY_NAME)
        account = SocMedAccount.objects.create(
            agency=agency,
            platform=IngestPlatform.X,
            handle="backfillme",
            user_id="",
        )

        resolved = resolve_account(
            IngestPlatform.X, handle="backfillme", user_id="424242"
        )

        # A fresh queryset fetch is a new instance — compare by identity key,
        # not object identity.
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, account.id)
        account.refresh_from_db()
        self.assertEqual(account.user_id, "424242")

    def test_a_hit_with_a_user_object_refreshes_the_profile_columns(self):
        # A webhook delivery with the full user object keeps the row current
        # for free, which is what keeps the later sync sweep short.
        account = resolve_account(
            IngestPlatform.X,
            handle="askrapidkl",
            raw_payload={
                "id": SEEDED_ASKRAPIDKL_USER_ID,
                "username": "askrapidkl",
            },
            display_name="Fresh name",
        )

        self.assertEqual(account.display_name, "Fresh name")
        account.refresh_from_db()
        self.assertEqual(account.display_name, "Fresh name")
        self.assertIsNotNone(account.resolved_at)

    def test_an_unknown_handle_is_auto_registered_under_unassigned(self):
        # No API call: the row is written with an empty user_id, resolved later
        # by ``ensure_user_profile`` (or backfilled by a delivery).
        account = resolve_account(IngestPlatform.X, handle="brandnew", create=True)

        self.assertIsNotNone(account)
        self.assertEqual(account.agency.name, UNASSIGNED_AGENCY_NAME)
        self.assertEqual(account.user_id, "")
        # Same account on a second resolution, never a twin.
        again = resolve_account(IngestPlatform.X, handle="brandnew", create=True)
        self.assertEqual(again.id, account.id)
        self.assertEqual(SocMedAccount.objects.filter(handle="brandnew").count(), 1)

    def test_create_without_a_handle_never_registers(self):
        self.assertIsNone(resolve_account(IngestPlatform.X, user_id="777", create=True))
        self.assertFalse(SocMedAccount.objects.filter(user_id="777").exists())

    def test_no_match_and_no_create_returns_none_without_an_api_call(self):
        with mock.patch.object(
            official_posts,
            "_get_json",
            side_effect=AssertionError("HTTP called"),
        ):
            self.assertIsNone(
                resolve_account(IngestPlatform.X, handle="nobody", create=False)
            )

    # --- ensure_user_profile --------------------------------------------

    def test_ensure_user_profile_is_a_no_op_when_the_id_is_set(self):
        account = SocMedAccount.objects.get(handle="askrapidkl")

        with mock.patch.object(
            official_posts,
            "_get_json",
            side_effect=AssertionError("HTTP called"),
        ):
            self.assertIs(ensure_user_profile(account), account)

        account.refresh_from_db()
        self.assertEqual(account.user_id, SEEDED_ASKRAPIDKL_USER_ID)

    def test_ensure_user_profile_resolves_and_persists_a_missing_id(self):
        agency = Agency.objects.get(name=PRASARANA_AGENCY_NAME)
        account = SocMedAccount.objects.create(
            agency=agency,
            platform=IngestPlatform.X,
            handle="resolveable",
            user_id="",
        )

        with mock.patch.object(
            official_posts,
            "_get_json",
            return_value={
                "data": {
                    "id": "424242",
                    "name": "Resolveable",
                    "username": "resolveable",
                }
            },
        ):
            refreshed = ensure_user_profile(account)

        account.refresh_from_db()
        self.assertEqual(refreshed.user_id, "424242")
        self.assertEqual(account.user_id, "424242")
        self.assertEqual(account.display_name, "Resolveable")
        self.assertEqual(account.raw_payload["username"], "resolveable")
        self.assertIsNotNone(account.resolved_at)

    def test_ensure_user_profile_raises_when_the_payload_carries_no_id(self):
        agency = Agency.objects.get(name=PRASARANA_AGENCY_NAME)
        account = SocMedAccount.objects.create(
            agency=agency,
            platform=IngestPlatform.X,
            handle="noidentity",
            user_id="",
        )

        with mock.patch.object(
            official_posts,
            "_get_json",
            return_value={"data": {"username": "noidentity"}},
        ):
            with self.assertRaises(OfficialPostFetchError) as caught:
                ensure_user_profile(account)

        self.assertIn("no user id", str(caught.exception))

    # --- sync_account_profiles -------------------------------------------

    def test_sync_resolves_every_missing_id_and_reports_the_count(self):
        agency = Agency.objects.get(name=PRASARANA_AGENCY_NAME)
        first = SocMedAccount.objects.create(
            agency=agency, platform=IngestPlatform.X, handle="sync-a", user_id=""
        )
        second = SocMedAccount.objects.create(
            agency=agency, platform=IngestPlatform.X, handle="sync-b", user_id=""
        )
        payloads = {
            "sync-a": {"data": {"id": "111", "name": "A", "username": "sync-a"}},
            "sync-b": {"data": {"id": "222", "name": "B", "username": "sync-b"}},
        }

        def fake_get_json(url, *, params, headers, context):
            return payloads[url.rsplit("/", 1)[-1]]

        with mock.patch.object(official_posts, "_get_json", side_effect=fake_get_json):
            resolved = sync_account_profiles()

        self.assertEqual(resolved, 2)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.user_id, "111")
        self.assertEqual(second.user_id, "222")

    def test_a_per_account_failure_does_not_abort_the_sweep(self):
        agency = Agency.objects.get(name=PRASARANA_AGENCY_NAME)
        SocMedAccount.objects.create(
            agency=agency, platform=IngestPlatform.X, handle="dead-a", user_id=""
        )
        good = SocMedAccount.objects.create(
            agency=agency, platform=IngestPlatform.X, handle="good-b", user_id=""
        )
        call_count = 0

        def fake_get_json(url, *, params, headers, context):
            nonlocal call_count
            call_count += 1
            if "dead-a" in url:
                raise OfficialPostFetchError("X API error: HTTP 429")
            return {"data": {"id": "222", "name": "B", "username": "good-b"}}

        with self.assertLogs("incident.services.official_posts", level="WARNING"):
            with mock.patch.object(
                official_posts, "_get_json", side_effect=fake_get_json
            ):
                resolved = sync_account_profiles()

        self.assertEqual(resolved, 1)
        good.refresh_from_db()
        self.assertEqual(good.user_id, "222")
        # Both rows were attempted; one failure did not stop the other.
        self.assertEqual(call_count, 2)

    def test_sync_makes_no_api_calls_when_nothing_is_missing(self):
        with mock.patch.object(
            official_posts,
            "_get_json",
            side_effect=AssertionError("HTTP called"),
        ):
            self.assertEqual(sync_account_profiles(), 0)

    # --- model constraints -------------------------------------------------

    def test_duplicate_platform_and_handle_is_rejected(self):
        agency = Agency.objects.first()
        SocMedAccount.objects.create(
            agency=agency, platform=IngestPlatform.X, handle="dup"
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SocMedAccount.objects.create(
                    agency=agency, platform=IngestPlatform.X, handle="dup"
                )

    def test_a_non_empty_user_id_is_unique_per_platform(self):
        agency = Agency.objects.first()
        SocMedAccount.objects.create(
            agency=agency, platform=IngestPlatform.X, handle="one", user_id="424242"
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SocMedAccount.objects.create(
                    agency=agency,
                    platform=IngestPlatform.X,
                    handle="two",
                    user_id="424242",
                )

    def test_an_empty_user_id_is_shared_by_many(self):
        # ``user_id=""`` is the "not yet resolved" state; the uniqueness must
        # never treat several unresolved rows as duplicates.
        agency = Agency.objects.first()
        for handle in ("empty-a", "empty-b"):
            SocMedAccount.objects.create(
                agency=agency, platform=IngestPlatform.X, handle=handle, user_id=""
            )
        self.assertEqual(SocMedAccount.objects.filter(user_id="").count(), 2)

    def test_one_account_may_hold_a_post_id_only_once(self):
        account = SocMedAccount.objects.get(handle="askrapidkl")
        author = get_system_author()
        kwargs = dict(
            url="https://x.com/askrapidkl/status/1791552310047416320",
            user=author,
            socmed_account=account,
            post_id="1791552310047416320",
        )
        SocialMediaLink.objects.create(title="first", description="first", **kwargs)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SocialMediaLink.objects.create(
                    title="twin", description="twin", **kwargs
                )


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
        # Poll only the one account this class cares about: ``is_enabled`` is
        # the polling gate, and the other seeded account would re-fetch the
        # same askrapidkl-handle posts (adding noise to the totals), not new
        # ones.
        SocMedAccount.objects.filter(handle="myrapidkl").update(is_enabled=False)

    def _ingest(self, sender=None, *, posts=None, **extra_settings):
        """Run the beat task with HTTP stubbed; ``sender=None`` uses the real
        ``send_message`` (only the PTB application is then faked)."""
        task_settings = {
            "OFFICIAL_POST_INGESTION_ENABLED": True,
            "OFFICIAL_POST_POLLING_ENABLED": True,
            "X_API_BEARER_TOKEN": "t",
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


class PublicFeedHiddenGateTests(TestCase):
    """``HIDDEN`` is a moderation decision: never public, never resurrectable."""

    feed_query = """
        query Feed($first: Int, $status: SocialMediaLinkStatus, $mine: Boolean) {
            publicSocialMediaLinks(first: $first, status: $status, mine: $mine) {
                totalCount
                edges { node { id status } }
            }
        }
    """

    def setUp(self):
        self.community_author = User.objects.create(firebase_id="feed-hidden-community")
        self.system_author = get_system_author()

    def _link(self, slug, *, user=None, **kwargs):
        return SocialMediaLink.objects.create(
            url=f"https://example.com/{slug}",
            title=slug,
            user=user or self.community_author,
            **kwargs,
        )

    def _feed(self, *, user=None, **variables):
        result = execute_graphql(self.feed_query, variables=variables, user=user)
        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        return result.data["publicSocialMediaLinks"]

    def _ids(self, feed):
        return [edge["node"]["id"] for edge in feed["edges"]]

    def test_hidden_rows_never_reach_the_public_feed_and_nothing_else_changes(self):
        hidden_auto = self._link(
            "auto-hidden",
            status=SocialMediaLinkStatus.HIDDEN,
            is_automated=True,
            user=self.system_author,
        )
        # Hidden is a moderation decision, not an ingestion artefact: a
        # hand-submitted row is hidden by it too.
        hidden_community = self._link(
            "community-hidden", status=SocialMediaLinkStatus.HIDDEN
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

        feed = self._feed(first=10)

        ids = self._ids(feed)
        self.assertNotIn(str(hidden_auto.id), ids)
        self.assertNotIn(str(hidden_community.id), ids)
        # The other two states are untouched, and so is the automated-pending
        # gate: a hidden row is excluded for a different, unconditional reason.
        self.assertIn(str(live_auto.id), ids)
        self.assertIn(str(community_pending.id), ids)
        self.assertIn(str(community_live.id), ids)
        # totalCount comes from the same queryset, so page and count agree.
        self.assertEqual(feed["totalCount"], 3)
        self.assertEqual(SocialMediaLink.objects.count(), 5)

    def test_an_explicit_hidden_filter_cannot_resurrect_a_hidden_row(self):
        self._link(
            "auto-hidden",
            status=SocialMediaLinkStatus.HIDDEN,
            is_automated=True,
            user=self.system_author,
        )
        self._link("community-hidden", status=SocialMediaLinkStatus.HIDDEN)

        feed = self._feed(first=10, status="HIDDEN")

        # The exclusion is applied after the narrowing, so asking for HIDDEN by
        # name returns an empty page instead of what the gate removed.
        self.assertEqual(feed["edges"], [])
        self.assertEqual(feed["totalCount"], 0)
        # Read gate, not a deletion: both rows are still stored for the console.
        self.assertEqual(
            SocialMediaLink.objects.filter(status=SocialMediaLinkStatus.HIDDEN).count(),
            2,
        )

    def test_the_owner_still_sees_their_own_hidden_link_under_mine(self):
        other_author = User.objects.create(firebase_id="feed-hidden-other")
        mine = self._link(
            "mine-hidden",
            status=SocialMediaLinkStatus.HIDDEN,
            user=self.community_author,
        )
        theirs = self._link(
            "other-hidden", status=SocialMediaLinkStatus.HIDDEN, user=other_author
        )

        feed = self._feed(first=10, mine=True, user=self.community_author)

        # ``mine`` is the owner's own submission list, not a public feed, so the
        # moderation gate is deliberately not applied there.
        ids = self._ids(feed)
        self.assertIn(str(mine.id), ids)
        self.assertNotIn(str(theirs.id), ids)
        self.assertEqual(feed["totalCount"], 1)

    def test_the_console_queue_still_returns_hidden_rows(self):
        # An admin has to be able to *find* a hidden row in order to un-hide it,
        # so the console query is deliberately left unfiltered.
        hidden = self._link(
            "auto-hidden",
            status=SocialMediaLinkStatus.HIDDEN,
            is_automated=True,
            user=self.system_author,
        )
        query = """
            query Console {
                socialMediaLinks { id status isAutomated }
            }
        """
        with patch(
            "rosak.permissions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = execute_graphql(query, user=self.community_author)

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        rows = {row["id"]: row for row in result.data["socialMediaLinks"]}
        self.assertEqual(rows[str(hidden.id)]["status"], "HIDDEN")
        self.assertIs(rows[str(hidden.id)]["isAutomated"], True)


class SocialMediaLinkAutomatedFlagTests(TestCase):
    """``isAutomated`` on the scalar, and who may set ``HIDDEN``."""

    feed_query = """
        query Feed($first: Int) {
            publicSocialMediaLinks(first: $first) {
                totalCount
                edges { node { id status isAutomated } }
            }
        }
    """

    update_query = """
        mutation Update($id: ID!, $input: SocialMediaLinkInput!) {
            updateSocialMediaLink(socialMediaLinkId: $id, input: $input) { ok }
        }
    """

    def setUp(self):
        self.community_author = User.objects.create(firebase_id="automated-flag-user")
        self.system_author = get_system_author()

    def test_is_automated_is_resolvable_and_true_only_for_ingested_rows(self):
        ingested = SocialMediaLink.objects.create(
            url="https://example.com/ingested",
            title="ingested",
            user=self.system_author,
            status=SocialMediaLinkStatus.LIVE,
            is_automated=True,
        )
        submitted = SocialMediaLink.objects.create(
            url="https://example.com/submitted",
            title="submitted",
            user=self.community_author,
            status=SocialMediaLinkStatus.LIVE,
        )

        result = execute_graphql(self.feed_query, variables={"first": 10})

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        rows = {
            edge["node"]["id"]: edge["node"]
            for edge in result.data["publicSocialMediaLinks"]["edges"]
        }
        self.assertIs(rows[str(ingested.id)]["isAutomated"], True)
        self.assertIs(rows[str(submitted.id)]["isAutomated"], False)
        # Non-null in the wire contract, not a nullable best-effort field.
        self.assertIn("isAutomated: Boolean!", str(schema))

    def test_legacy_rows_default_to_not_automated(self):
        link = SocialMediaLink.objects.create(
            url="https://example.com/legacy",
            title="legacy",
            user=self.community_author,
        )

        self.assertIs(link.is_automated, False)

    def test_an_admin_update_can_hide_a_link_but_a_submitter_cannot(self):
        link = SocialMediaLink.objects.create(
            url="https://example.com/to-hide",
            title="to hide",
            user=self.community_author,
            status=SocialMediaLinkStatus.LIVE,
        )
        hide_input = {"url": link.url, "title": link.title, "status": "HIDDEN"}

        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = execute_graphql(
                self.update_query,
                variables={"id": str(link.id), "input": hide_input},
                user=self.community_author,
            )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        self.assertTrue(result.data["updateSocialMediaLink"]["ok"])
        link.refresh_from_db()
        self.assertEqual(link.status, SocialMediaLinkStatus.HIDDEN)

        # A non-admin edit is still forced back into the approval queue, so
        # HIDDEN remains an admin decision the submitter can neither set nor keep.
        with patch(
            "incident.schema.mutations.interactions.has_admin_claim",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = execute_graphql(
                self.update_query,
                variables={"id": str(link.id), "input": hide_input},
                user=self.community_author,
            )

        self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
        link.refresh_from_db()
        self.assertEqual(link.status, SocialMediaLinkStatus.PENDING_APPROVAL)


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
                socmed_account__handle="askrapidkl",
                status=SocialMediaLinkStatus.PENDING_APPROVAL,
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

    def test_dry_run_with_an_unregistered_handle_is_refused(self):
        # Auto-registration is itself a write, so a preview may only point at an
        # account the registry already knows: a dry run must write no rows of
        # any kind — link rows or account rows.
        accounts_before = SocMedAccount.objects.count()

        with self.assertRaises(CommandError) as caught:
            self._run(
                "--handle",
                "brandnew",
                "--fixture",
                str(SAMPLE_FIXTURE),
                "--dry-run",
            )

        self.assertIn("not in the registry", str(caught.exception))
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.assertEqual(SocMedAccount.objects.count(), accounts_before)

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
            self.assertEqual(link.socmed_account.handle, "myrapidkl")
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
        ingest_posts(posts, author=author)
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
        # The registry account direct-row writes below are attributed to.
        self.askrapidkl = resolve_account(IngestPlatform.X, handle="askrapidkl")
        self.assertIsNotNone(self.askrapidkl)
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
            "socmed_account": self.askrapidkl,
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
        )
        self._store(
            url="https://x.com/askrapidkl/status/1791552700000000002",
            title="older",
            description="posted 26 Sep",
            post_id="1791552700000000002",
            posted_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
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
#: What the stored text must be: entities are decoded once, at the ingest
#: boundary, so the row carries the characters the operator published.
WEBHOOK_POST_TEXT_DECODED = "Gangguan laluan utama & penyehjangan(types): MTR"
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
    nested_includes: bool = True,
    top_level_includes: bool = False,
    top_level_username: str | None = None,
) -> dict:
    """A current-shaped Activity API ``post.create`` delivery.

    ``username=None`` drops the ``includes.users`` expansion, which is what
    forces the reverse (user-id → handle) lookup path.

    ``nested_includes`` puts the expansion where X actually puts it — on the
    event object, ``data.includes`` — and is the default so the suite exercises
    the real envelope. ``top_level_includes`` reproduces the defensive fallback
    for a differently-shaped delivery, and ``top_level_username`` gives it a
    conflicting value for the precedence test.
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
    if username is not None and nested_includes:
        event["includes"] = {
            "users": [{"id": author_id, "username": username, "name": "RapidKL"}]
        }
    if top_level_includes:
        payload["includes"] = {
            "users": [
                {
                    "id": author_id,
                    "username": (
                        username if top_level_username is None else top_level_username
                    ),
                    "name": "RapidKL",
                }
            ]
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


class XWebhookHandleResolutionTests(TestCase):
    """Attribution through the registry: ``includes.users`` first (no network),
    then a user-id lookup with at most one bounded ``sync_account_profiles``
    sweep. ``resolve_account`` is the one path every delivery goes through and
    it never calls the API."""

    def test_the_includes_expansion_resolves_the_handle_with_no_network(self):
        with mock.patch.object(
            official_posts,
            "_get_json",
            side_effect=AssertionError("network must not be used"),
        ):
            result = ingest_webhook_payload(xaa_post_create_payload())

        self.assertEqual(result.events, 1)
        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.unresolved, 0)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.socmed_account.handle, "askrapidkl")

    def test_the_nested_includes_expansion_resolves_the_handle_with_no_network(self):
        # Regression: X puts the expansion on the event object (data.includes).
        # Reading only the top level resolved nothing, so a real delivery made
        # a profile sweep, failed offline, and was counted unresolved — the
        # whole ingest path was dead in production while the tests passed.
        payload = xaa_post_create_payload()
        self.assertIn("includes", payload["data"])

        with mock.patch.object(
            official_posts,
            "_get_json",
            side_effect=AssertionError("network must not be used"),
        ):
            result = ingest_webhook_payload(payload)

        self.assertEqual(result.events, 1)
        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.unresolved, 0)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.socmed_account.handle, "askrapidkl")

    def test_a_top_level_includes_expansion_is_still_accepted(self):
        # The defensive fallback: a differently-shaped delivery must keep working.
        with mock.patch.object(
            official_posts,
            "_get_json",
            side_effect=AssertionError("network must not be used"),
        ):
            result = ingest_webhook_payload(
                xaa_post_create_payload(nested_includes=False, top_level_includes=True)
            )

        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.unresolved, 0)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.socmed_account.handle, "askrapidkl")

    def test_the_nested_includes_wins_over_a_top_level_one(self):
        payload = xaa_post_create_payload(
            username="askrapidkl",
            nested_includes=True,
            top_level_includes=True,
            top_level_username="askrapidkl_old",
        )

        users = _users_by_id(payload)
        self.assertIn(WEBHOOK_AUTHOR_ID, users)
        self.assertEqual(users[WEBHOOK_AUTHOR_ID]["username"], "askrapidkl")

        result = ingest_webhook_payload(payload)

        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.socmed_account.handle, "askrapidkl")
        self.assertEqual(result.ingested, 1)

    def test_a_malformed_includes_expansion_is_tolerated(self):
        # Anything unparseable must degrade to the user-id lookup, not raise.
        for includes in (
            {},
            {"users": None},
            {"users": "askrapidkl"},
            "askrapidkl",
            None,
        ):
            with self.subTest(includes=includes):
                payload = xaa_post_create_payload(username=None)
                payload["data"]["includes"] = includes
                self.assertEqual(_users_by_id(payload), {})

    def test_an_incomplete_user_expansion_is_skipped(self):
        payload = xaa_post_create_payload(username=None)
        payload["data"]["includes"] = {
            "users": [
                "not-a-dict",
                {"username": "askrapidkl"},
                {"id": WEBHOOK_AUTHOR_ID},
                {"id": "  ", "username": "askrapidkl"},
                {"id": WEBHOOK_AUTHOR_ID, "username": " @askrapidkl "},
            ]
        }

        users = _users_by_id(payload)
        self.assertEqual(set(users), {WEBHOOK_AUTHOR_ID})
        # The whole user object is kept verbatim; only the validity check
        # strips the surrounding whitespace.
        self.assertEqual(users[WEBHOOK_AUTHOR_ID]["username"], " @askrapidkl ")
        self.assertEqual(users[WEBHOOK_AUTHOR_ID]["id"], WEBHOOK_AUTHOR_ID)

    def test_a_seeded_user_id_resolves_without_a_profile_sweep(self):
        # The migration-0029 account already carries its user_id, so a delivery
        # with no expansion resolves by user_id alone — no sweep, no network.
        with (
            mock.patch.object(
                official_posts,
                "_get_json",
                side_effect=AssertionError("network must not be used"),
            ),
            mock.patch(
                "incident.services.x_webhooks.sync_account_profiles",
                side_effect=AssertionError("a profile sweep must not run here"),
            ),
        ):
            result = ingest_webhook_payload(
                xaa_post_create_payload(
                    author_id=SEEDED_ASKRAPIDKL_USER_ID, username=None
                )
            )

        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.unresolved, 0)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.socmed_account.handle, "askrapidkl")

    def test_an_unknown_user_id_gets_one_bounded_sweep_then_retries(self):
        # Bounded: one profile sweep, then the user-id lookup is retried once.
        # The sweep registers the row (resolving accounts whose user_id is
        # empty), and that row is what makes the retry resolve — never a second
        # sweep, never a direct API call from the webhook path.
        author_id = "7100000000000000001"
        agency = Agency.objects.get(name=UNASSIGNED_AGENCY_NAME)

        def sweep():
            SocMedAccount.objects.create(
                agency=agency,
                platform=IngestPlatform.X,
                handle="brandnew",
                user_id=author_id,
            )
            return 1

        with mock.patch(
            "incident.services.x_webhooks.sync_account_profiles", side_effect=sweep
        ) as sync:
            result = ingest_webhook_payload(
                xaa_post_create_payload(
                    author_id=author_id, username=None, filter_user_id=author_id
                )
            )

        self.assertEqual(sync.call_count, 1)
        self.assertEqual(result.events, 1)
        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.unresolved, 0)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.socmed_account.handle, "brandnew")

    def test_the_filter_hint_never_overrides_the_real_author(self):
        # The subscription filter's user_id is only a fallback: a reply by a
        # different account must not be attributed to the tracked handle.
        author_id = "7100000000000000003"

        with mock.patch(
            "incident.services.x_webhooks.sync_account_profiles", return_value=0
        ):
            result = ingest_webhook_payload(
                xaa_post_create_payload(
                    author_id=author_id,
                    username=None,
                    filter_user_id=SEEDED_ASKRAPIDKL_USER_ID,
                )
            )

        # Nothing was attributed and no row was written: a wrong permalink is
        # worse than a dropped post.
        self.assertEqual(result.events, 1)
        self.assertEqual(result.ingested, 0)
        self.assertEqual(result.unresolved, 1)
        self.assertEqual(SocialMediaLink.objects.count(), 0)

    def test_an_unresolvable_author_is_counted_and_dropped(self):
        with mock.patch(
            "incident.services.x_webhooks.sync_account_profiles", return_value=0
        ):
            with self.assertLogs(
                "incident.services.x_webhooks", level="WARNING"
            ) as logs:
                result = ingest_webhook_payload(
                    xaa_post_create_payload(
                        author_id="7100000000000000002", username=None
                    )
                )

        self.assertEqual(result.events, 1)
        self.assertEqual(result.ingested, 0)
        self.assertEqual(result.unresolved, 1)
        self.assertEqual(SocialMediaLink.objects.count(), 0)
        self.assertTrue(any("no known account" in line for line in logs.output))


class XWebhookEntityDecodingTests(TestCase):
    """A real delivery stores decoded text while keeping the payload encoded.

    The webhook is the primary ingest path, so this pins the end-to-end
    contract: what the row says and what the export copy says.
    """

    def test_a_delivery_stores_decoded_text_and_keeps_the_encoded_payload(self):
        result = ingest_webhook_payload(xaa_post_create_payload())

        self.assertEqual(result.ingested, 1)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.description, WEBHOOK_POST_TEXT_DECODED)
        self.assertEqual(link.title, WEBHOOK_POST_TEXT_DECODED[:256])
        # Export fidelity: the provider object is stored exactly as it arrived.
        self.assertEqual(link.raw_payload["text"], WEBHOOK_POST_TEXT)

    def test_a_delivery_with_an_already_escaped_entity_is_not_decoded_twice(self):
        result = ingest_webhook_payload(
            xaa_post_create_payload(text="a &amp;amp; b &#38;#39;")
        )

        self.assertEqual(result.ingested, 1)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        # One decode only: ``&amp;amp;`` is an escaped entity and ``&#38;#39;``
        # an escaped numeric reference. A second pass would store a bare ``&``.
        self.assertEqual(link.description, "a &amp; b &#39;")
        self.assertEqual(link.raw_payload["text"], "a &amp;amp; b &#38;#39;")


@no_debug_toolbar
class XWebhookDeliveryViewTests(TestCase):
    """``POST /webhooks/x-api`` — verify, ingest, acknowledge inside 10 seconds."""

    BASE_SETTINGS = {
        "OFFICIAL_POST_INGESTION_ENABLED": True,
        "OFFICIAL_POST_POLLING_ENABLED": False,
        "X_API_OAUTH2_CLIENT_SECRET": "",
        "X_API_SECRET_KEY": TEST_LEGACY_SECRET,
        "TELEGRAM_ADMIN_CHAT_ID": "-1001234",
    }

    def setUp(self):
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
        # Verbatim after the single entity decode, including the ampersand.
        self.assertEqual(link.description, WEBHOOK_POST_TEXT_DECODED)
        self.assertEqual(link.title, WEBHOOK_POST_TEXT_DECODED[:256])
        # The provider object is kept whole for the export — still encoded.
        self.assertEqual(link.raw_payload["text"], WEBHOOK_POST_TEXT)
        # The handle comes from includes.users; the permalink is built from it.
        self.assertEqual(link.socmed_account.handle, "askrapidkl")
        self.assertEqual(link.url, f"https://x.com/askrapidkl/status/{WEBHOOK_POST_ID}")
        self.assertEqual(link.socmed_account.platform, IngestPlatform.X)
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
        # The AAA delivery carries the seeded account's user_id, so the registry
        # resolves it with no network and no profile sweep.
        response = self._post(
            aaa_post_create_payload(user_id=SEEDED_ASKRAPIDKL_USER_ID)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ingested"], 1)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.socmed_account.handle, "askrapidkl")
        self.assertEqual(link.url, f"https://x.com/askrapidkl/status/{WEBHOOK_POST_ID}")
        self.notify.delay.assert_called_once()

    def test_the_aaa_shape_resolves_the_handle_from_for_user_id(self):
        # No author key at all: for_user_id is the only id the delivery carries,
        # and it identifies a seeded account by user_id.
        payload = aaa_post_create_payload(for_user_id=SEEDED_ASKRAPIDKL_USER_ID)
        payload["tweet_create_events"][0].pop("user_id")

        response = self._post(payload)

        self.assertEqual(response.json()["ingested"], 1)
        link = SocialMediaLink.objects.get(post_id=WEBHOOK_POST_ID)
        self.assertEqual(link.socmed_account.handle, "askrapidkl")

    def test_an_unresolvable_handle_is_200_counted_and_logged(self):
        # An id no seeded account carries: the bounded profile sweep runs once
        # (resolving nothing), the delivery is counted unresolved and dropped.
        with mock.patch(
            "incident.services.x_webhooks.sync_account_profiles", return_value=0
        ):
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
        self.assertTrue(any("no known account" in line for line in logs.output))

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
            "for_user_id": SEEDED_ASKRAPIDKL_USER_ID,
            "tweet_create_events": [
                {
                    "id": WEBHOOK_POST_ID,
                    "text": WEBHOOK_POST_TEXT,
                    "created_at": WEBHOOK_CREATED_AT,
                    "user_id": SEEDED_ASKRAPIDKL_USER_ID,
                },
                {
                    "id": "1791552310047416321",
                    "text": "second post",
                    "created_at": WEBHOOK_CREATED_AT,
                    "user_id": SEEDED_ASKRAPIDKL_USER_ID,
                },
            ],
        }

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
        ingest_posts(posts, author=self.author)
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
            # One scripted response per handle: a second call with an empty
            # script would be a StopIteration, not a silent pass. The seeded
            # accounts already carry their user_ids, so no API lookup happens
            # before the subscription calls.
            with self._patched(
                [
                    fake_x_response(200, {"data": {"id": "5001"}}),
                    fake_x_response(200, {"data": {"id": "5002"}}),
                ]
            ) as request:
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
                "filter": {"user_id": SEEDED_ASKRAPIDKL_USER_ID},
                "webhook_id": "18923",
                "tag": "official-posts",
            },
        )
        self.assertEqual(
            second.kwargs["json"]["filter"], {"user_id": SEEDED_MYRAPIDKL_USER_ID}
        )
        self.assertIn(
            f"subscribed handle=askrapidkl user_id={SEEDED_ASKRAPIDKL_USER_ID}", out
        )
        self.assertNotIn(self.TOKEN, out)

    def test_subscribe_strips_a_leading_at_sign(self):
        with override_settings(**self.SETTINGS):
            with self._patched([fake_x_response(200, {"data": {"id": "5001"}})]):
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
            with self._patched(
                [
                    fake_x_response(200, {"data": [{"id": "18923", "valid": True}]}),
                    fake_x_response(200, {"data": {"id": "5001"}}),
                ]
            ) as request:
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
        # ``_user_id`` resolves through the *service's* functions (imported
        # function-locally inside the command), so the lookup is patched at its
        # source. The unknown handle auto-registers under Unassigned, then the
        # profile lookup fails and the subscription is refused.
        with override_settings(**self.SETTINGS):
            with (
                mock.patch(
                    "incident.services.official_posts.ensure_user_profile",
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
