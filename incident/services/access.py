"""Author/admin access rules and incident lookup shared by the services."""

from common.models import User
from incident.models import CalendarIncident

from .errors import IncidentServiceError


def is_author(actor: User, incident: CalendarIncident) -> bool:
    return incident.created_by_id is not None and incident.created_by_id == actor.id


def may_edit(actor: User, *, is_admin: bool, incident: CalendarIncident) -> bool:
    return is_admin or is_author(actor, incident)


async def get_incident(incident_id: int) -> CalendarIncident:
    try:
        return await CalendarIncident.objects.aget(pk=incident_id)
    except CalendarIncident.DoesNotExist as exc:
        raise IncidentServiceError(
            f"CalendarIncident {incident_id} does not exist."
        ) from exc
