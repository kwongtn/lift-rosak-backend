from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident, CalendarIncidentChronology


class CalendarIncidentChronologyTests(TestCase):
    def test_chronology_independent_status(self):
        incident = CalendarIncident.objects.create(
            title="Test Incident",
            brief="Test brief",
            severity="MINOR",
            start_datetime=timezone.now(),
            status=CalendarIncidentStatus.DRAFT,
        )
        chronology = CalendarIncidentChronology.objects.create(
            calendar_incident=incident,
            status=CalendarIncidentStatus.PENDING_APPROVAL,
            indicator="GREEN",
            datetime=timezone.now(),
        )
        assert chronology.status == CalendarIncidentStatus.PENDING_APPROVAL
        assert incident.status == CalendarIncidentStatus.DRAFT

    def test_chronology_cannot_be_live_if_parent_not_live(self):
        incident = CalendarIncident.objects.create(
            title="Test Incident",
            brief="Test brief",
            severity="MINOR",
            start_datetime=timezone.now(),
            status=CalendarIncidentStatus.DRAFT,
        )
        chronology = CalendarIncidentChronology.objects.create(
            calendar_incident=incident,
            status=CalendarIncidentStatus.DRAFT,
            indicator="GREEN",
            datetime=timezone.now(),
        )
        chronology.status = CalendarIncidentStatus.LIVE
        with self.assertRaises(ValidationError):
            chronology.full_clean()

    def test_chronology_can_be_live_if_parent_is_live(self):
        """Chronology CAN be LIVE when parent incident is LIVE."""
        incident = CalendarIncident.objects.create(
            title="Live Incident",
            brief="Live brief",
            severity="MAJOR",
            start_datetime=timezone.now(),
            status=CalendarIncidentStatus.LIVE,
        )
        chronology = CalendarIncidentChronology.objects.create(
            calendar_incident=incident,
            status=CalendarIncidentStatus.LIVE,
            indicator="GREEN",
            datetime=timezone.now(),
        )
        chronology.full_clean()  # Should not raise
        assert chronology.status == CalendarIncidentStatus.LIVE

    def test_chronology_status_independent_from_parent(self):
        """Chronology status is independent - can be different from parent."""
        incident = CalendarIncident.objects.create(
            title="Draft Incident",
            brief="Draft brief",
            severity="MINOR",
            start_datetime=timezone.now(),
            status=CalendarIncidentStatus.DRAFT,
        )
        chronology = CalendarIncidentChronology.objects.create(
            calendar_incident=incident,
            status=CalendarIncidentStatus.PENDING_APPROVAL,
            indicator="GREEN",
            datetime=timezone.now(),
        )
        assert chronology.status == CalendarIncidentStatus.PENDING_APPROVAL
        assert incident.status == CalendarIncidentStatus.DRAFT
