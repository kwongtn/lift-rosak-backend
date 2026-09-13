"""Regression tests for the legacy-status backfill in incident 0015/0016.

When ``status`` was introduced, every pre-existing incident/chronology was
created with the new DRAFT default. The migrations backfill those legacy rows to
LIVE so that only rows created *after* the migration keep the DRAFT default.
"""

import importlib

from django.apps import apps as django_apps
from django.test import TestCase
from django.utils import timezone

from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident, CalendarIncidentChronology

migration_0015 = importlib.import_module(
    "incident.migrations.0015_calendarincident_deleted_and_more"
)
migration_0016 = importlib.import_module(
    "incident.migrations.0016_calendarincidentchronology_deleted_and_more"
)


def _create_incident(**overrides):
    fields = {
        "title": "Legacy Incident",
        "brief": "Legacy brief",
        "severity": "MINOR",
        "start_datetime": timezone.now(),
    }
    fields.update(overrides)
    return CalendarIncident.objects.create(**fields)


def _create_chronology(incident):
    return CalendarIncidentChronology.objects.create(
        calendar_incident=incident,
        indicator="GREEN",
        datetime=timezone.now(),
    )


class LegacyStatusBackfillTests(TestCase):
    def test_new_entries_default_to_draft(self):
        incident = _create_incident()
        chronology = _create_chronology(incident)

        self.assertEqual(incident.status, CalendarIncidentStatus.DRAFT)
        self.assertEqual(chronology.status, CalendarIncidentStatus.DRAFT)

    def test_backfill_marks_legacy_entries_live(self):
        incident = _create_incident()
        chronology = _create_chronology(incident)

        migration_0015.backfill_existing_incidents_live(django_apps, None)
        migration_0016.backfill_existing_chronologies_live(django_apps, None)

        incident.refresh_from_db()
        chronology.refresh_from_db()
        self.assertEqual(incident.status, CalendarIncidentStatus.LIVE)
        self.assertEqual(chronology.status, CalendarIncidentStatus.LIVE)

    def test_backfill_is_reversible(self):
        incident = _create_incident()
        chronology = _create_chronology(incident)

        migration_0015.backfill_existing_incidents_live(django_apps, None)
        migration_0016.backfill_existing_chronologies_live(django_apps, None)
        migration_0015.revert_existing_incidents_draft(django_apps, None)
        migration_0016.revert_existing_chronologies_draft(django_apps, None)

        incident.refresh_from_db()
        chronology.refresh_from_db()
        self.assertEqual(incident.status, CalendarIncidentStatus.DRAFT)
        self.assertEqual(chronology.status, CalendarIncidentStatus.DRAFT)
