import asyncio

import strawberry
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from common.models import User
from incident.models import CalendarIncident, CalendarIncidentCategory, SocialMediaLink
from incident.schema.resolvers import get_public_social_media_links
from incident.services import delete_social_media_link
from incident.services.errors import IncidentServiceError
from operation.models import Line, Station, Vehicle, VehicleType


class SocialMediaLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-sml")
        self.admin_user = User.objects.create(firebase_id="test-admin-sml")

    def test_social_media_link_category_relationship(self):
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

    def test_social_media_link_generic_fk_to_incident(self):
        """SocialMediaLink can link to CalendarIncident via GenericForeignKey"""
        incident = CalendarIncident.objects.create(
            title="Test Incident",
            brief="Test incident brief",
            severity="MINOR",
            start_datetime=timezone.now(),
        )

        link = SocialMediaLink.objects.create(
            url="https://example.com/news",
            user=self.user,
            content_object=incident,
        )

        assert link.content_object == incident
        assert link.content_type == ContentType.objects.get_for_model(CalendarIncident)
        assert link.object_id == incident.id

    def test_social_media_link_without_content_object(self):
        """SocialMediaLink can exist without being tagged to any object (just dumping)"""
        link = SocialMediaLink.objects.create(
            url="https://example.com/random",
            user=self.user,
        )

        assert link.content_object is None
        assert link.content_type is None
        assert link.object_id is None

    def test_just_reporting_category_exists(self):
        self.assertTrue(
            CalendarIncidentCategory.objects.filter(name="Just Reporting").exists()
        )


class SocialMediaLinkAsyncTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create(firebase_id="test-user-sml-async")
        self.other_user = User.objects.create(firebase_id="other-user-async")

    def test_delete_social_media_link_ownership(self):
        """Owner can delete their link; non-owner raises IncidentServiceError."""
        link = SocialMediaLink.objects.create(
            url="https://example.com/test",
            user=self.user,
        )

        # Owner can delete
        asyncio.run(delete_social_media_link(self.user, link_id=link.id))
        self.assertFalse(SocialMediaLink.objects.filter(id=link.id).exists())

        # Non-owner cannot delete
        link2 = SocialMediaLink.objects.create(
            url="https://example.com/test2",
            user=self.user,
        )
        with self.assertRaises(IncidentServiceError):
            asyncio.run(delete_social_media_link(self.other_user, link_id=link2.id))
        self.assertTrue(SocialMediaLink.objects.filter(id=link2.id).exists())


def _make_link(user_n, *, completed=False):
    user = User.objects.create(firebase_id=f"test-pub-sml-{user_n}")
    return SocialMediaLink.objects.create(
        url=f"https://example.com/pub-{user_n}",
        title=f"Public link {user_n}",
        user=user,
        completed=completed,
    )


class PublicSocialMediaLinkTests(TransactionTestCase):
    reset_sequences = True

    def test_public_social_media_links_no_auth_required(self):
        approved = _make_link(1, completed=True)
        pending = _make_link(2, completed=False)

        results = asyncio.run(get_public_social_media_links(None))
        result_ids = {link.id for link in results}

        self.assertIn(approved.id, result_ids)
        self.assertIn(pending.id, result_ids)

    def test_public_social_media_links_returns_both_approved_and_pending(self):
        approved = _make_link(10, completed=True)
        pending = _make_link(11, completed=False)

        results = asyncio.run(get_public_social_media_links(None))
        by_id = {link.id: link for link in results}

        self.assertIn(approved.id, by_id)
        self.assertIn(pending.id, by_id)
        self.assertTrue(by_id[approved.id].completed)
        self.assertFalse(by_id[pending.id].completed)

    def test_public_social_media_links_line_id_filters(self):
        line_a = Line.objects.create(
            code="PUB_A", display_name="Public Line A", display_color="#111111"
        )
        line_b = Line.objects.create(
            code="PUB_B", display_name="Public Line B", display_color="#222222"
        )

        link_on_a = _make_link(20)
        link_on_a.lines.set([line_a])

        link_on_b = _make_link(21)
        link_on_b.lines.set([line_b])

        results_a = asyncio.run(
            get_public_social_media_links(None, line_id=strawberry.Some(str(line_a.id)))
        )
        ids_a = {link.id for link in results_a}
        self.assertIn(link_on_a.id, ids_a)
        self.assertNotIn(link_on_b.id, ids_a)

        results_b = asyncio.run(
            get_public_social_media_links(None, line_id=strawberry.Some(str(line_b.id)))
        )
        ids_b = {link.id for link in results_b}
        self.assertIn(link_on_b.id, ids_b)
        self.assertNotIn(link_on_a.id, ids_b)

    def test_public_social_media_links_ordered_newest_first(self):
        oldest = _make_link(30)
        middle = _make_link(31)
        newest = _make_link(32)

        results = asyncio.run(get_public_social_media_links(None))
        result_ids = [link.id for link in results]

        self.assertIn(oldest.id, result_ids)
        self.assertIn(middle.id, result_ids)
        self.assertIn(newest.id, result_ids)
        self.assertLess(result_ids.index(newest.id), result_ids.index(oldest.id))

    def test_public_social_media_links_no_line_id_returns_all(self):
        line = Line.objects.create(
            code="PUB_ALL", display_name="Public All", display_color="#333333"
        )
        tagged = _make_link(40)
        tagged.lines.set([line])
        untagged = _make_link(41)

        results = asyncio.run(get_public_social_media_links(None))
        result_ids = {link.id for link in results}

        self.assertIn(tagged.id, result_ids)
        self.assertIn(untagged.id, result_ids)
