"""Vote business logic over the generic Vote model, scoped to CalendarIncident."""

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType

from common.models import User, Vote
from incident.models import CalendarIncident

from .access import get_incident


async def _incident_content_type() -> ContentType:
    return await sync_to_async(ContentType.objects.get_for_model)(CalendarIncident)


async def set_incident_vote(user: User, *, incident_id: int, value: int) -> None:
    await get_incident(incident_id)

    content_type = await _incident_content_type()
    await sync_to_async(Vote.objects.update_or_create)(
        user=user,
        content_type=content_type,
        object_id=incident_id,
        defaults={"value": value},
    )


async def remove_incident_vote(user: User, *, incident_id: int) -> bool:
    content_type = await _incident_content_type()
    deleted_count, _ = await Vote.objects.filter(
        user=user,
        content_type=content_type,
        object_id=incident_id,
    ).adelete()
    return deleted_count > 0
