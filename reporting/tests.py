from django.contrib.gis.geos import Point
from django.test import TestCase

from common.models import User
from operation.models import Asset, Station
from reporting.enums import ReportType
from reporting.models import Report, Vote


class ReportingModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="reporter-user-1")
        self.station = Station.objects.create(
            display_name="Subang Jaya", location=Point(101.58, 3.08)
        )
        self.asset = Asset.objects.create(
            station=self.station, officialid="LFT-A", status="ACTIVE"
        )

    def test_create_report_and_vote(self):
        report = Report.objects.create(
            reporter=self.user,
            asset=self.asset,
            type=ReportType.FUNCTIONAL_BREAKDOWN,
            description="Lift door not closing",
        )
        self.assertEqual(report.type, ReportType.FUNCTIONAL_BREAKDOWN)
        self.assertFalse(report.is_removed)

        vote = Vote.objects.create(
            user=self.user,
            report=report,
            is_upvote=True,
        )
        self.assertTrue(vote.is_upvote)
        self.assertFalse(vote.is_downvote)

    def test_soft_delete(self):
        report = Report.objects.create(
            reporter=self.user,
            asset=self.asset,
            type=ReportType.COSMETIC_BREAKDOWN,
            description="Dirty station floor",
        )
        report.delete()
        self.assertTrue(report.is_removed)
        self.assertEqual(Report.objects.count(), 0)
        self.assertEqual(Report.all_objects.count(), 1)
