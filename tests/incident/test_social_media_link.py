import asyncio
import copy

import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from dotmap import DotMap

from common.models import User
from incident.models import CalendarIncident, CalendarIncidentCategory, SocialMediaLink
from incident.schema.keyset import decode_keyset_cursor, encode_keyset_cursor
from incident.schema.loaders import IncidentContextLoaders
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


class _FakeInfo:
    """Minimal info stand-in carrying a user (or None) for resolver calls."""

    class _Ctx:
        def __init__(self, user):
            self.user = user

    def __init__(self, user=None):
        self.context = self._Ctx(user)


def _ids(connection):
    return [edge.node.id for edge in connection.edges]


async def _make_incident(title):
    return await sync_to_async(CalendarIncident.objects.create)(
        title=title,
        brief="brief",
        severity="MINOR",
        start_datetime=timezone.now(),
    )


async def _make_incident_link(incident, user_n, *, title="", created=None):
    user = await sync_to_async(User.objects.create)(
        firebase_id=f"test-inc-link-{incident.id}-{user_n}"
    )
    link = await sync_to_async(SocialMediaLink.objects.create)(
        url=f"https://example.com/inc-{incident.id}-{user_n}",
        title=title or f"Incident link {incident.id} #{user_n}",
        user=user,
        content_object=incident,
    )
    if created is not None:
        await sync_to_async(SocialMediaLink.objects.filter(id=link.id).update)(
            created=created
        )
        await sync_to_async(link.refresh_from_db)()
    return link


def _build_schema():
    import django

    django.setup()
    from rosak.schema import Query

    return strawberry.Schema(query=Query)


def _context(user=None):
    return DotMap(
        {
            "loaders": {"incident": copy.deepcopy(IncidentContextLoaders)},
            "request": None,
            "response": None,
            "user": user,
        }
    )


async def _links_for_incident(incident_id, *, first=10, after=None):
    """Real-schema execution of the nested links field for one incident."""
    schema = _build_schema()
    query = """
        query IncidentLinks($first: Int, $after: String) {
          calendarIncidents {
            id
            links(first: $first, after: $after) {
              edges { node { id url title status } cursor }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
    """
    result = await schema.execute(
        query,
        context_value=_context(),
        variable_values={"first": first, "after": after},
    )
    assert result.errors is None, result.errors
    for incident in result.data["calendarIncidents"]:
        if incident["id"] == str(incident_id):
            return incident["links"]
    raise AssertionError(f"incident {incident_id} not in calendarIncidents")


class CalendarIncidentLinksTests(TransactionTestCase):
    """Nested CalendarIncidentScalar.links(first, after) — executed through the
    real schema so the incident_links DataLoader path is covered end-to-end.
    Same keyset cursor + ordering as the root publicSocialMediaLinks resolver.
    Asserts membership/relative order only (async tests do not get per-test
    rollback; other tests' rows are irrelevant)."""

    async def _links(self, incident_id, **kwargs):
        return await _links_for_incident(incident_id, **kwargs)

    @pytest.mark.django_db
    async def test_links_returns_incidents_links_newest_first(self):
        incident = await _make_incident("Links order incident")
        oldest = await _make_incident_link(incident, 1, created="2026-08-01T08:00:00Z")
        middle = await _make_incident_link(incident, 2, created="2026-08-01T09:00:00Z")
        newest = await _make_incident_link(incident, 3, created="2026-08-01T10:00:00Z")

        connection = await self._links(incident.id)
        ids = [edge["node"]["id"] for edge in connection["edges"]]

        self.assertIn(str(oldest.id), ids)
        self.assertIn(str(middle.id), ids)
        self.assertIn(str(newest.id), ids)
        self.assertLess(ids.index(str(newest.id)), ids.index(str(oldest.id)))
        self.assertFalse(connection["pageInfo"]["hasNextPage"])
        self.assertEqual(
            connection["pageInfo"]["endCursor"], connection["edges"][-1]["cursor"]
        )

    @pytest.mark.django_db
    async def test_links_excludes_other_incidents_and_untagged(self):
        incident = await _make_incident("Links include incident")
        other = await _make_incident("Links other incident")
        tagged = await _make_incident_link(incident, 1)
        await _make_incident_link(other, 2)

        connection = await self._links(incident.id)
        ids = [edge["node"]["id"] for edge in connection["edges"]]
        self.assertIn(str(tagged.id), ids)
        self.assertEqual(len(ids), 1)

    @pytest.mark.django_db
    async def test_links_paginates_via_cursor_without_overlap(self):
        incident = await _make_incident("Links paginated incident")
        for i in range(5):
            await _make_incident_link(incident, i)

        first = await self._links(incident.id, first=2)
        first_ids = [edge["node"]["id"] for edge in first["edges"]]
        self.assertEqual(len(first_ids), 2)
        self.assertTrue(first["pageInfo"]["hasNextPage"])
        self.assertIsNotNone(first["pageInfo"]["endCursor"])

        second = await self._links(
            incident.id, first=2, after=first["pageInfo"]["endCursor"]
        )
        second_ids = [edge["node"]["id"] for edge in second["edges"]]
        self.assertEqual(len(second_ids), 2)
        self.assertTrue(second["pageInfo"]["hasNextPage"])
        self.assertEqual(set(first_ids) & set(second_ids), set())

        last = await self._links(
            incident.id, first=2, after=second["pageInfo"]["endCursor"]
        )
        last_ids = [edge["node"]["id"] for edge in last["edges"]]
        self.assertEqual(len(last_ids), 1)
        self.assertFalse(last["pageInfo"]["hasNextPage"])
        self.assertEqual(set(first_ids) & set(last_ids), set())
        self.assertEqual(set(second_ids) & set(last_ids), set())

    @pytest.mark.django_db
    async def test_links_empty_connection_for_linkless_incident(self):
        incident = await _make_incident("Links empty incident")

        connection = await self._links(incident.id)
        self.assertEqual(connection["edges"], [])
        self.assertFalse(connection["pageInfo"]["hasNextPage"])
        self.assertIsNone(connection["pageInfo"]["endCursor"])

    @pytest.mark.django_db
    async def test_links_cursor_is_consumable_by_root_resolver(self):
        """The nested field's cursor decodes to the same keyset tuple the root
        resolver applies — cursor contract is shared (keyset.py)."""
        incident = await _make_incident("Links cursor contract incident")
        link = await _make_incident_link(incident, 1)

        connection = await self._links(incident.id)
        cursor = connection["edges"][0]["cursor"]
        reloaded = await sync_to_async(SocialMediaLink.objects.get)(id=link.id)
        self.assertEqual(decode_keyset_cursor(cursor), (reloaded.created, reloaded.id))
        self.assertEqual(encode_keyset_cursor(*decode_keyset_cursor(cursor)), cursor)

        # The same cursor drives the root resolver's keyset predicate — walk one
        # page with it and assert the keyset link is excluded (it is the edge the
        # cursor was built from).
        root = await get_public_social_media_links(
            None,
            _FakeInfo(),
            incident_id=strawberry.Some(str(incident.id)),
            first=1,
            after=cursor,
        )
        self.assertNotIn(str(link.id), _ids(root))


class PublicSocialMediaLinkTests(TransactionTestCase):
    def test_public_social_media_links_no_auth_required(self):
        approved = _make_link(1, completed=True)
        pending = _make_link(2, completed=False)

        results = asyncio.run(get_public_social_media_links(None, _FakeInfo()))
        result_ids = _ids(results)

        self.assertIn(approved.id, result_ids)
        self.assertIn(pending.id, result_ids)

    def test_public_social_media_links_returns_both_approved_and_pending(self):
        approved = _make_link(10, completed=True)
        pending = _make_link(11, completed=False)

        results = asyncio.run(get_public_social_media_links(None, _FakeInfo()))
        by_id = {edge.node.id: edge.node for edge in results.edges}

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
            get_public_social_media_links(
                None, _FakeInfo(), line_id=strawberry.Some(str(line_a.id))
            )
        )
        ids_a = _ids(results_a)
        self.assertIn(link_on_a.id, ids_a)
        self.assertNotIn(link_on_b.id, ids_a)

        results_b = asyncio.run(
            get_public_social_media_links(
                None, _FakeInfo(), line_id=strawberry.Some(str(line_b.id))
            )
        )
        ids_b = _ids(results_b)
        self.assertIn(link_on_b.id, ids_b)
        self.assertNotIn(link_on_a.id, ids_b)

    def test_public_social_media_links_ordered_newest_first(self):
        oldest = _make_link(30)
        middle = _make_link(31)
        newest = _make_link(32)

        results = asyncio.run(get_public_social_media_links(None, _FakeInfo()))
        result_ids = _ids(results)

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

        results = asyncio.run(get_public_social_media_links(None, _FakeInfo()))
        result_ids = _ids(results)

        self.assertIn(tagged.id, result_ids)
        self.assertIn(untagged.id, result_ids)

    def test_public_social_media_links_incident_id_filters(self):
        incident = CalendarIncident.objects.create(
            title="Incident with links",
            brief="brief",
            severity="MINOR",
            start_datetime=timezone.now(),
        )
        other_incident = CalendarIncident.objects.create(
            title="Other incident",
            brief="brief",
            severity="MINOR",
            start_datetime=timezone.now(),
        )
        content_type = ContentType.objects.get_for_model(CalendarIncident)

        tagged = _make_link(50)
        tagged.content_type = content_type
        tagged.object_id = incident.id
        tagged.save()

        other = _make_link(51)
        other.content_type = content_type
        other.object_id = other_incident.id
        other.save()

        untagged = _make_link(52)

        results = asyncio.run(
            get_public_social_media_links(
                None, _FakeInfo(), incident_id=strawberry.Some(str(incident.id))
            )
        )
        ids = _ids(results)
        self.assertIn(tagged.id, ids)
        self.assertNotIn(other.id, ids)
        self.assertNotIn(untagged.id, ids)

    def test_public_social_media_links_pagination_first_page(self):
        for i in range(5):
            _make_link(60 + i)

        results = asyncio.run(get_public_social_media_links(None, _FakeInfo(), first=3))
        ids = _ids(results)

        self.assertEqual(len(ids), 3)
        self.assertTrue(results.page_info.has_next_page)
        self.assertIsNotNone(results.page_info.end_cursor)

    def test_public_social_media_links_pagination_next_page_no_overlap(self):
        for i in range(5):
            _make_link(70 + i)

        first_page = asyncio.run(
            get_public_social_media_links(None, _FakeInfo(), first=2)
        )
        first_ids = _ids(first_page)
        self.assertEqual(len(first_ids), 2)
        self.assertTrue(first_page.page_info.has_next_page)

        second_page = asyncio.run(
            get_public_social_media_links(
                None, _FakeInfo(), first=2, after=first_page.page_info.end_cursor
            )
        )
        second_ids = _ids(second_page)
        self.assertEqual(len(second_ids), 2)
        self.assertTrue(second_page.page_info.has_next_page)

        # No overlap between pages.
        self.assertEqual(set(first_ids) & set(second_ids), set())

    def test_public_social_media_links_pagination_last_page(self):
        for i in range(3):
            _make_link(80 + i)

        results = asyncio.run(
            get_public_social_media_links(None, _FakeInfo(), first=10)
        )
        ids = _ids(results)

        self.assertEqual(len(ids), 3)
        self.assertFalse(results.page_info.has_next_page)

    def test_public_social_media_links_mine_logged_in(self):
        owner = User.objects.create(firebase_id="mine-owner")
        other = User.objects.create(firebase_id="mine-other")

        own_link = _make_link(90)
        own_link.user = owner
        own_link.save()

        other_link = _make_link(91)
        other_link.user = other
        other_link.save()

        results = asyncio.run(
            get_public_social_media_links(
                None, _FakeInfo(user=owner), mine=strawberry.Some(True)
            )
        )
        ids = _ids(results)
        self.assertIn(own_link.id, ids)
        self.assertNotIn(other_link.id, ids)

    def test_public_social_media_links_mine_anonymous(self):
        results = asyncio.run(
            get_public_social_media_links(
                None, _FakeInfo(user=None), mine=strawberry.Some(True)
            )
        )
        self.assertEqual(results.edges, [])
        self.assertFalse(results.page_info.has_next_page)
