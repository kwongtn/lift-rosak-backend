import pytest
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from common.models import User
from incident import services
from incident.models import CalendarIncident


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
        write=services.SocialMediaLinkWrite(url="https://x.com/lrt/status/456"),
    )
    assert untagged.content_type_id is None
    assert untagged.object_id is None

    with pytest.raises(services.IncidentServiceError):
        await services.submit_social_media_link(
            user,
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
async def test_mark_social_media_link_completed_records_admin_user():
    submitter = await _make_user(2)
    admin = await _make_user(3)
    link = await services.submit_social_media_link(
        submitter,
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
