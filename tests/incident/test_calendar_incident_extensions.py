from django.test import TestCase
from django.utils import timezone

from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncident


class CalendarIncidentExtensionsTests(TestCase):
    def test_soft_delete_preserves_record(self):
        incident = CalendarIncident.objects.create(
            title="Test Incident",
            brief="Test brief",
            severity="MINOR",
            start_datetime=timezone.now(),
            status=CalendarIncidentStatus.DRAFT,
        )
        incident_id = incident.id

        incident.delete()

        self.assertEqual(
            CalendarIncident.deleted_objects.filter(id=incident_id).count(), 1
        )
        self.assertEqual(
            CalendarIncident.all_objects.filter(id=incident_id).count(), 1
        )

        deleted_incident = CalendarIncident.all_objects.get(id=incident_id)
        self.assertIsNotNone(deleted_incident.deleted)

    def test_audit_history_tracks_changes(self):
        incident = CalendarIncident.objects.create(
            title="Original Title",
            brief="Original brief",
            severity="MINOR",
            start_datetime=timezone.now(),
            status=CalendarIncidentStatus.DRAFT,
        )

        incident.title = "Updated Title"
        incident.save()

        self.assertEqual(incident.history.count(), 2)
        self.assertEqual(incident.history.first().title, "Updated Title")

    def test_draft_pattern_with_parent_incident(self):
        live_incident = CalendarIncident.objects.create(
            title="Live Incident",
            brief="Live incident brief",
            severity="MAJOR",
            start_datetime=timezone.now(),
            status=CalendarIncidentStatus.LIVE,
        )

        draft_revision = CalendarIncident.objects.create(
            title="Draft Revision",
            brief="Draft revision brief",
            severity="MAJOR",
            start_datetime=timezone.now(),
            status=CalendarIncidentStatus.PENDING_APPROVAL,
            parent_incident=live_incident,
        )

        self.assertEqual(draft_revision.parent_incident, live_incident)
        self.assertIn(draft_revision, live_incident.draft_revisions.all())
