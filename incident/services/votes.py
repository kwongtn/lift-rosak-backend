"""Vote business logic over the generic Vote model.

The core helpers are content-type-agnostic (any model with a GenericRelation
to common.Vote works). The incident- and chronology-scoped wrappers keep the
existing public function signatures so callers and tests are unaffected.
"""

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType

from common.models import User, Vote
from incident.models import CalendarIncidentChronology

from .access import get_incident
from .errors import IncidentServiceError


async def _content_type_for(model) -> ContentType:
    return await sync_to_async(ContentType.objects.get_for_model)(model)


async def _apply_vote(user: User, *, target, value: int) -> None:
    content_type = await _content_type_for(type(target))
    await sync_to_async(Vote.objects.update_or_create)(
        user=user,
        content_type=content_type,
        object_id=target.pk,
        defaults={"value": value},
    )


async def _remove_vote(user: User, *, target) -> bool:
    content_type = await _content_type_for(type(target))
    deleted_count, _ = await Vote.objects.filter(
        user=user,
        content_type=content_type,
        object_id=target.pk,
    ).adelete()
    return deleted_count > 0


async def _get_chronology(chronology_id: int) -> CalendarIncidentChronology:
    try:
        return await CalendarIncidentChronology.objects.aget(pk=chronology_id)
    except CalendarIncidentChronology.DoesNotExist as exc:
        raise IncidentServiceError(
            f"CalendarIncidentChronology {chronology_id} does not exist."
        ) from exc


# --- Incident-scoped wrappers (backward compatible) ---


async def set_incident_vote(user: User, *, incident_id: int, value: int) -> None:
    incident = await get_incident(incident_id)
    await _apply_vote(user, target=incident, value=value)


async def remove_incident_vote(user: User, *, incident_id: int) -> bool:
    incident = await get_incident(incident_id)
    return await _remove_vote(user, target=incident)


# --- Chronology-scoped wrappers ---


async def set_chronology_vote(user: User, *, chronology_id: int, value: int) -> None:
    chronology = await _get_chronology(chronology_id)
    await _apply_vote(user, target=chronology, value=value)


async def remove_chronology_vote(user: User, *, chronology_id: int) -> bool:
    chronology = await _get_chronology(chronology_id)
    return await _remove_vote(user, target=chronology)
