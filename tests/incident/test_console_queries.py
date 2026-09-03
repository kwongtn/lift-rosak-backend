"""Tests for the admin-only console queue queries (pending incidents, social links)."""

import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.models import User
from incident import services
from incident.enums import CalendarIncidentStatus
from incident.models import CalendarIncidentCategory, SocialMediaLink
from incident.schema.resolvers import (
    get_calendar_incident_categories,
    get_pending_calendar_incidents,
    get_social_media_links,
)
from incident.services.incidents import replace_chronologies


def _write(**overrides) -> services.IncidentWrite:
    defaults = dict(
        title="Queue Incident",
        brief="Queue brief",
        start_datetime=timezone.now(),
        severity="MINOR",
    )
    defaults.update(overrides)
    return services.IncidentWrite(**defaults)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=f"test-user-console-{n}"
    )


async def _make_pending(user_n: int = 0, **overrides):
    user = await _make_user(user_n)
    incident = await services.create_incident(
        user, is_admin=False, data=_write(**overrides)
    )
    incident.status = CalendarIncidentStatus.PENDING_APPROVAL
    await sync_to_async(incident.save)()
    return incident


@pytest.mark.django_db
async def test_pending_incidents_text_search():
    title_hit = await _make_pending(title="LRT line down")
    brief_hit = await _make_pending(user_n=1, brief="signal failure at KL Sentral")
    details_hit = await _make_pending(user_n=2, details="platform 3 flooded")
    chronology_hit = await _make_pending(user_n=3)
    await replace_chronologies(
        chronology_hit,
        (
            services.ChronologyWrite(
                indicator="BLUE",
                content="news",
                source_url="https://twitter.com/lrt-meltdown",
            ),
        ),
        inherit_status=CalendarIncidentStatus.PENDING_APPROVAL,
    )
    await _make_pending(user_n=4, title="Unrelated disruption")

    assert {
        i.id
        for i in await get_pending_calendar_incidents(
            None, search=strawberry.Some("line down")
        )
    } == {title_hit.id}
    assert {
        i.id
        for i in await get_pending_calendar_incidents(
            None, search=strawberry.Some("kl sentral")
        )
    } == {brief_hit.id}
    assert {
        i.id
        for i in await get_pending_calendar_incidents(
            None, search=strawberry.Some("flooded")
        )
    } == {details_hit.id}
    assert {
        i.id
        for i in await get_pending_calendar_incidents(
            None, search=strawberry.Some("twitter.com/lrt")
        )
    } == {chronology_hit.id}
    assert (
        await get_pending_calendar_incidents(None, search=strawberry.Some("zebra"))
        == []
    )


@pytest.mark.django_db
async def test_pending_incidents_excludes_other_statuses():
    pending = await _make_pending(user_n=10)
    user = await _make_user(11)
    live = await services.create_incident(user, is_admin=True, data=_write())
    draft = await services.create_incident(user, is_admin=False, data=_write())

    results = await get_pending_calendar_incidents(None)
    result_ids = {i.id for i in results}

    assert pending.id in result_ids
    assert live.id not in result_ids
    assert draft.id not in result_ids


@pytest.mark.django_db
async def test_pending_incidents_includes_live_with_pending_deletion_chronologies():
    """Spec E1 surface: LIVE incidents with a PENDING_DELETION chronology join the queue."""

    admin = await _make_user(61)

    live_with_request = await services.create_incident(
        admin, is_admin=True, data=_write(title="Live with pending deletion")
    )
    # Two pending-deletion rows on one incident exercise the join dedup below.
    await replace_chronologies(
        live_with_request,
        (
            services.ChronologyWrite(
                indicator="BLUE",
                content="mark for delete",
                source_url="https://x.com/live-pending-delete",
            ),
            services.ChronologyWrite(
                indicator="GRAY",
                content="also marked",
                source_url="",
            ),
        ),
        inherit_status=CalendarIncidentStatus.PENDING_DELETION,
    )

    live_clean = await services.create_incident(
        admin, is_admin=True, data=_write(title="Live clean")
    )
    await replace_chronologies(
        live_clean,
        (
            services.ChronologyWrite(
                indicator="GREEN", content="all good", source_url=""
            ),
        ),
        inherit_status=CalendarIncidentStatus.LIVE,
    )

    pending = await _make_pending(user_n=62, title="Pending approval row")

    results = await get_pending_calendar_incidents(None)
    result_ids = [i.id for i in results]
    assert live_with_request.id in result_ids
    assert result_ids.count(live_with_request.id) == 1
    assert live_clean.id not in result_ids
    assert pending.id in result_ids
    # Oldest-first across both segments; live_with_request predates `pending`.
    assert result_ids.index(live_with_request.id) < result_ids.index(pending.id)

    search_ids = {
        i.id
        for i in await get_pending_calendar_incidents(
            None, search=strawberry.Some("live-pending-delete")
        )
    }
    assert search_ids == {live_with_request.id}


@pytest.mark.django_db
async def test_social_media_links_text_search():
    user = await _make_user(20)
    url_hit = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://x.com/prasarana/status/1", title="", user=user
    )
    title_hit = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/a", title="LRT service alert", user=user
    )
    await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/b", title="unrelated", user=user
    )

    assert {
        link.id
        for link in await get_social_media_links(
            None, search=strawberry.Some("prasarana")
        )
    } == {url_hit.id}
    assert {
        link.id
        for link in await get_social_media_links(
            None, search=strawberry.Some("service alert")
        )
    } == {title_hit.id}


@pytest.mark.django_db
async def test_social_media_links_category_filter():
    user = await _make_user(30)
    category = await sync_to_async(CalendarIncidentCategory.objects.create)(
        name="Disruption"
    )
    tagged = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/tagged", title="", user=user
    )
    await sync_to_async(tagged.categories.set)([category])
    untagged = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/untagged", title="", user=user
    )

    results = await get_social_media_links(
        None, category_id=strawberry.Some(str(category.id))
    )

    assert [link.id for link in results] == [tagged.id]
    assert untagged.id not in {link.id for link in results}


@pytest.mark.django_db
async def test_social_media_links_completed_filter():
    user = await _make_user(40)
    admin = await _make_user(41)
    open_link = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/open", title="", user=user
    )
    done_link = await sync_to_async(SocialMediaLink.objects.create)(
        url="https://example.com/done", title="", user=user
    )
    await services.mark_social_media_link_completed(admin, link_id=done_link.id)

    incomplete_ids = {
        link.id
        for link in await get_social_media_links(None, completed=strawberry.Some(False))
    }
    complete_ids = {
        link.id
        for link in await get_social_media_links(None, completed=strawberry.Some(True))
    }

    assert open_link.id in incomplete_ids
    assert open_link.id not in complete_ids
    assert done_link.id in complete_ids
    assert done_link.id not in incomplete_ids


@pytest.mark.django_db
async def test_categories_query_lists_all_ordered_by_name():
    await sync_to_async(CalendarIncidentCategory.objects.create)(name="Zebra")
    await sync_to_async(CalendarIncidentCategory.objects.create)(name="Alpha")

    names = [c.name for c in await get_calendar_incident_categories(None)]

    assert names == sorted(names)
