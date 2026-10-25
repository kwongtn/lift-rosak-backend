"""Chronology and incident datetimes reach the services as naive KL wall time.

``USE_TZ = False``: the DB reads back naive Asia/Kuala_Lumpur values, while the
GraphQL ``DateTime`` scalar parses ``...Z`` and offset strings to aware values
(the web console sent ``...Z`` until rosak_firebase f853bb67; stale bundles and
other API clients still can).
These tests pin the one conversion point (``shared.naive_kl``) and the bug it
closes: ``replace_chronologies`` could never match an aware key against a stored
naive one, so a pending chronology was silently recreated as LIVE.
"""

from datetime import UTC, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from strawberry.types.maybe import Some

from common.models import User
from incident.enums import (
    CalendarIncidentChronologyIndicator,
    CalendarIncidentSeverity,
    CalendarIncidentStatus,
)
from incident.models import CalendarIncident, CalendarIncidentChronology
from incident.schema.inputs import (
    CalendarIncidentChronologyInput,
    CalendarIncidentInput,
)
from incident.schema.mutations.shared import (
    chronology_write_from_input,
    write_from_input,
)
from incident.tests import execute_graphql


class InputDatetimeFrameTests(SimpleTestCase):
    """The resolver boundary hands the services naive KL wall time."""

    def _chronology(self, value):
        return chronology_write_from_input(
            CalendarIncidentChronologyInput(indicator="GREEN", datetime=Some(value))
        )

    def test_aware_utc_chronology_time_becomes_naive_kl(self):
        write = self._chronology(datetime(2026, 10, 24, 1, 0, tzinfo=UTC))

        self.assertEqual(write.datetime, datetime(2026, 10, 24, 9, 0))
        self.assertIsNone(write.datetime.tzinfo)

    def test_aware_kl_chronology_time_keeps_its_wall_time(self):
        kl = ZoneInfo(settings.TIME_ZONE)

        write = self._chronology(datetime(2026, 10, 24, 9, 0, tzinfo=kl))

        self.assertEqual(write.datetime, datetime(2026, 10, 24, 9, 0))
        self.assertIsNone(write.datetime.tzinfo)

    def test_naive_chronology_time_is_not_shifted(self):
        write = self._chronology(datetime(2026, 10, 24, 9, 0))

        self.assertEqual(write.datetime, datetime(2026, 10, 24, 9, 0))

    def test_an_omitted_chronology_time_stays_none(self):
        self.assertIsNone(
            chronology_write_from_input(
                CalendarIncidentChronologyInput(indicator="GREEN")
            ).datetime
        )

    def test_incident_start_and_end_become_naive_kl(self):
        write = write_from_input(
            CalendarIncidentInput(
                title="Frame",
                brief="Frame",
                start_datetime=datetime(2026, 10, 24, 0, 30, tzinfo=UTC),
                severity="MINOR",
                end_datetime=Some(datetime(2026, 10, 24, 16, 30, tzinfo=UTC)),
            )
        )

        self.assertEqual(write.start_datetime, datetime(2026, 10, 24, 8, 30))
        self.assertEqual(write.end_datetime, datetime(2026, 10, 25, 0, 30))

    def test_a_null_incident_end_stays_none(self):
        write = write_from_input(
            CalendarIncidentInput(
                title="Frame",
                brief="Frame",
                start_datetime=datetime(2026, 10, 24, 8, 30),
                severity="MINOR",
                end_datetime=Some(None),
            )
        )

        self.assertIsNone(write.end_datetime)


class ChronologyPendingStateSurvivesInputFrameTests(TestCase):
    """Re-saving a LIVE incident must not cancel a pending chronology.

    The web console posted every chronology time as ``...Z`` (aware UTC) until
    rosak_firebase f853bb67, and other clients still can, while the stored value
    reads back as naive KL. The identity key that matches an old
    row to its re-sent twin therefore never matched, and a PENDING_DELETION (or
    PENDING_APPROVAL) chronology was silently recreated as LIVE.
    """

    UPDATE = """
        mutation Update($id: ID!, $input: CalendarIncidentInput!) {
            updateCalendarIncident(calendarIncidentId: $id, input: $input) {
                ok
            }
        }
    """
    #: One 09:00 KL instant in the three spellings a client may send.
    SPELLINGS = (
        "2026-10-24T01:00:00.000Z",
        "2026-10-24T09:00:00+08:00",
        "2026-10-24T09:00:00",
    )

    def setUp(self):
        self.admin = User.objects.create(firebase_id="chronology-frame-admin")
        self.incident = CalendarIncident.objects.create(
            title="Frame",
            brief="Frame",
            severity=CalendarIncidentSeverity.MINOR,
            start_datetime=datetime(2026, 10, 24, 8, 0),
            status=CalendarIncidentStatus.LIVE,
            created_by=self.admin,
        )

    def _chronology(self, status):
        return CalendarIncidentChronology.objects.create(
            calendar_incident=self.incident,
            indicator=CalendarIncidentChronologyIndicator.GREEN,
            datetime=datetime(2026, 10, 24, 9, 0),
            content="train stalled",
            status=status,
        )

    def _admin_resave(self, spelling):
        with patch(
            "incident.schema.mutations.incidents.has_admin_claim",
            return_value=True,
        ):
            return execute_graphql(
                self.UPDATE,
                variables={
                    "id": str(self.incident.id),
                    "input": {
                        "title": "Frame",
                        "brief": "Frame",
                        "startDatetime": "2026-10-24T00:00:00.000Z",
                        "severity": "MINOR",
                        "chronologies": [
                            {
                                "indicator": "GREEN",
                                "datetime": spelling,
                                "content": "train stalled",
                            }
                        ],
                    },
                },
                user=self.admin,
            )

    def _assert_survives(self, status):
        for spelling in self.SPELLINGS:
            with self.subTest(spelling=spelling, status=status):
                self.incident.chronologies.all().delete()
                self._chronology(status)

                result = self._admin_resave(spelling)

                self.assertIsNone(result.errors, msg=f"errors: {result.errors}")
                rows = list(self.incident.chronologies.all())
                self.assertEqual([row.status for row in rows], [status])
                # The same instant is stored: nothing was shifted twice.
                self.assertEqual(rows[0].datetime, datetime(2026, 10, 24, 9, 0))

    def test_pending_deletion_survives_an_admin_resave(self):
        self._assert_survives(CalendarIncidentStatus.PENDING_DELETION)

    def test_pending_approval_survives_an_admin_resave(self):
        self._assert_survives(CalendarIncidentStatus.PENDING_APPROVAL)

    def test_the_incident_start_is_stored_at_the_same_instant(self):
        self._admin_resave(self.SPELLINGS[0])

        self.incident.refresh_from_db()
        # 00:00Z is 08:00 KL: normalising must not double-shift the stored value.
        self.assertEqual(self.incident.start_datetime, datetime(2026, 10, 24, 8, 0))
