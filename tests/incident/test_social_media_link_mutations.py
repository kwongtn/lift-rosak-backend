import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from common.models import User
from incident import services
from incident.enums import SocialMediaLinkStatus
from incident.models import CalendarIncident, SocialMediaLink
from operation.models import Line, Station, Vehicle, VehicleType


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"test-user-sml-{n}")


async def _make_incident() -> CalendarIncident:
    return await sync_to_async(CalendarIncident.objects.create)(
        title="Tagged Incident",
        brief="Test brief",
        severity="MINOR",
        start_datetime=timezone.now(),
    )


@pytest.mark.django_db
async def test_submit_social_media_link_with_and_without_incident():
    user = await _make_user(1)
    incident = await _make_incident()

    tagged = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/123",
            title="Delay thread",
            incident_id=incident.id,
        ),
    )
    await sync_to_async(tagged.refresh_from_db)()
    incident_ct = await sync_to_async(ContentType.objects.get_for_model)(
        CalendarIncident
    )
    assert tagged.object_id == incident.id
    assert tagged.content_type_id == incident_ct.id
    assert tagged.user_id == user.id
    assert not tagged.completed

    untagged = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(url="https://x.com/lrt/status/456"),
    )
    assert untagged.content_type_id is None
    assert untagged.object_id is None

    with pytest.raises(services.IncidentServiceError):
        await services.submit_social_media_link(
            user,
            is_admin=False,
            write=services.SocialMediaLinkWrite(
                url="https://x.com/lrt/status/789", incident_id=999999
            ),
        )


@pytest.mark.django_db
async def test_submit_social_media_link_with_line_vehicle_station_tags():
    from operation.models import Line, Station, Vehicle, VehicleType

    user = await _make_user(5)

    line = await sync_to_async(Line.objects.create)(
        code="TST", display_name="Test Line", display_color="#123456"
    )
    v_type = await sync_to_async(VehicleType.objects.create)(
        internal_name="TST_TYPE", display_name="Test Type"
    )
    vehicle = await sync_to_async(Vehicle.objects.create)(
        identification_no="TST-01", vehicle_type=v_type
    )
    station = await sync_to_async(Station.objects.create)(display_name="Test Station")

    link = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/999",
            title="Tagged with assets",
            line_ids=(line.id,),
            vehicle_ids=(vehicle.id,),
            station_ids=(station.id,),
        ),
    )

    assert await sync_to_async(list)(link.lines.values_list("id", flat=True)) == [
        line.id
    ]
    assert await sync_to_async(list)(link.vehicles.values_list("id", flat=True)) == [
        vehicle.id
    ]
    assert await sync_to_async(list)(link.stations.values_list("id", flat=True)) == [
        station.id
    ]


@pytest.mark.django_db
async def test_submit_social_media_link_title_null_and_omitted_coerce_to_empty():
    user = await _make_user(10)

    link_none = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/null-title",
            title=None,  # type: ignore[arg-type]
        ),
    )
    await sync_to_async(link_none.refresh_from_db)()
    assert link_none.title == ""

    # Omitted title (default "") already stores ""
    link_default = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/default-title",
        ),
    )
    await sync_to_async(link_default.refresh_from_db)()
    assert link_default.title == ""

    link_empty = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/empty-title",
            title="",
        ),
    )
    await sync_to_async(link_empty.refresh_from_db)()
    assert link_empty.title == ""


@pytest.mark.django_db
async def test_mark_social_media_link_completed_records_admin_user():
    submitter = await _make_user(2)
    admin = await _make_user(3)
    link = await services.submit_social_media_link(
        submitter,
        is_admin=False,
        write=services.SocialMediaLinkWrite(url="https://x.com/lrt/status/111"),
    )

    completed = await services.mark_social_media_link_completed(admin, link_id=link.id)
    assert completed.completed
    assert completed.completed_by_id == admin.id
    assert completed.completed_at is not None

    first_completed_at = completed.completed_at
    other_admin = await _make_user(4)
    remarkeed = await services.mark_social_media_link_completed(
        other_admin, link_id=link.id
    )
    assert remarkeed.completed_by_id == admin.id
    assert remarkeed.completed_at == first_completed_at


@pytest.mark.django_db
async def test_submit_social_media_link_status_defaulting():
    """Admin submit -> LIVE; user submit -> PENDING_APPROVAL."""
    user = await _make_user(20)
    admin = await _make_user(21)

    user_link = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(url="https://x.com/lrt/status/user"),
    )
    await sync_to_async(user_link.refresh_from_db)()
    assert user_link.status == SocialMediaLinkStatus.PENDING_APPROVAL

    admin_link = await services.submit_social_media_link(
        admin,
        is_admin=True,
        write=services.SocialMediaLinkWrite(url="https://x.com/lrt/status/admin"),
    )
    await sync_to_async(admin_link.refresh_from_db)()
    assert admin_link.status == SocialMediaLinkStatus.LIVE


@pytest.mark.django_db
async def test_submit_social_media_link_description_round_trip():
    user = await _make_user(25)

    link = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/desc",
            title="With description",
            description="A description of the link",
        ),
    )
    await sync_to_async(link.refresh_from_db)()
    assert link.description == "A description of the link"


@pytest.mark.django_db
async def test_update_social_media_link_description_and_status():
    user = await _make_user(30)
    link = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/update-me",
            title="Original title",
            description="Original description",
        ),
    )
    await sync_to_async(link.refresh_from_db)()
    assert link.status == SocialMediaLinkStatus.PENDING_APPROVAL

    updated = await services.update_social_media_link(
        user,
        link_id=link.id,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/update-me",
            title="Updated title",
            description="Updated description",
            status=SocialMediaLinkStatus.LIVE,
        ),
    )
    await sync_to_async(updated.refresh_from_db)()
    assert updated.title == "Updated title"
    assert updated.description == "Updated description"
    assert updated.status == SocialMediaLinkStatus.LIVE


@pytest.mark.django_db
async def test_update_social_media_link_tri_state_omitted_unchanged():
    """Omitting description/status leaves them unchanged."""
    user = await _make_user(35)
    link = await services.submit_social_media_link(
        user,
        is_admin=True,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/tri",
            title="Title",
            description="My desc",
        ),
    )
    await sync_to_async(link.refresh_from_db)()
    assert link.status == SocialMediaLinkStatus.LIVE
    assert link.description == "My desc"

    updated = await services.update_social_media_link(
        user,
        link_id=link.id,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/tri",
            title="Title",
            # description and status omitted -> unchanged
        ),
    )
    await sync_to_async(updated.refresh_from_db)()
    assert updated.description == "My desc"
    assert updated.status == SocialMediaLinkStatus.LIVE


@pytest.mark.django_db
async def test_admin_resolver_filters():
    from incident.schema.resolvers import get_social_media_links

    user = await _make_user(41)

    line = await sync_to_async(Line.objects.create)(
        code="FLT", display_name="Filter Line", display_color="#123456"
    )
    v_type = await sync_to_async(VehicleType.objects.create)(
        internal_name="FLT_TYPE", display_name="Filter Type"
    )
    vehicle = await sync_to_async(Vehicle.objects.create)(
        identification_no="FLT-01", vehicle_type=v_type
    )
    station = await sync_to_async(Station.objects.create)(display_name="Filter Station")

    base_time = timezone.now()

    link_all = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(
            url="https://x.com/lrt/status/flt-all",
            line_ids=(line.id,),
            vehicle_ids=(vehicle.id,),
            station_ids=(station.id,),
        ),
    )
    # Force created to a deterministic value for date-range filtering.
    await sync_to_async(SocialMediaLink.objects.filter(pk=link_all.id).update)(
        created=base_time
    )

    link_none = await services.submit_social_media_link(
        user,
        is_admin=False,
        write=services.SocialMediaLinkWrite(url="https://x.com/lrt/status/flt-none"),
    )

    # line_id filter
    res = await get_social_media_links(None, line_id=strawberry.Some(str(line.id)))
    ids = {link.id for link in res}
    assert link_all.id in ids
    assert link_none.id not in ids

    # vehicle_id filter
    res = await get_social_media_links(
        None, vehicle_id=strawberry.Some(str(vehicle.id))
    )
    ids = {link.id for link in res}
    assert link_all.id in ids
    assert link_none.id not in ids

    # station_id filter
    res = await get_social_media_links(
        None, station_id=strawberry.Some(str(station.id))
    )
    ids = {link.id for link in res}
    assert link_all.id in ids
    assert link_none.id not in ids

    # created_after / created_before range
    res = await get_social_media_links(
        None,
        created_after=strawberry.Some(base_time.replace(microsecond=0)),
    )
    ids = {link.id for link in res}
    assert link_all.id in ids
