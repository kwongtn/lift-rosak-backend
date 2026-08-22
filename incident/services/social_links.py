"""Social media link submission and completion business logic."""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from common.models import User
from incident.models import CalendarIncident, SocialMediaLink

from .access import get_incident


@dataclass(frozen=True, slots=True)
class SocialMediaLinkWrite:
    url: str
    title: str = ""
    incident_id: int | None = None
    category_ids: tuple[int, ...] = ()
    line_ids: tuple[int, ...] = ()
    vehicle_ids: tuple[int, ...] = ()
    station_ids: tuple[int, ...] = ()


async def submit_social_media_link(
    user: User, *, write: SocialMediaLinkWrite
) -> SocialMediaLink:
    content_type = None
    object_id = None
    if write.incident_id is not None:
        await get_incident(write.incident_id)
        content_type = await sync_to_async(ContentType.objects.get_for_model)(
            CalendarIncident
        )
        object_id = write.incident_id

    link = await sync_to_async(SocialMediaLink.objects.create)(
        url=write.url,
        title=write.title,
        user=user,
        content_type=content_type,
        object_id=object_id,
    )
    if write.category_ids:
        await sync_to_async(link.categories.set)(write.category_ids)
    if write.line_ids:
        await sync_to_async(link.lines.set)(write.line_ids)
    if write.vehicle_ids:
        await sync_to_async(link.vehicles.set)(write.vehicle_ids)
    if write.station_ids:
        await sync_to_async(link.stations.set)(write.station_ids)
    return link


async def mark_social_media_link_completed(
    admin: User, *, link_id: int
) -> SocialMediaLink:
    link = await SocialMediaLink.objects.aget(pk=link_id)

    def _sync() -> None:
        if link.completed:
            return
        link.completed = True
        link.completed_at = timezone.now()
        link.completed_by = admin
        link.save()

    await sync_to_async(_sync)()
    await sync_to_async(link.refresh_from_db)()
    return link
