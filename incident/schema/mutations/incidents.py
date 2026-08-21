"""CalendarIncident CRUD mutations."""

import strawberry
from strawberry.types import Info

from common.schema.scalars import GenericMutationReturn
from incident import services
from incident.schema.inputs import CalendarIncidentInput
from rosak.permissions import IsAdmin, IsLoggedIn, has_admin_claim

from .shared import (
    chronology_writes,
    maybe_value,
    raise_service_error,
    write_from_input,
)


@strawberry.type
class IncidentCrudMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def create_calendar_incident(
        self, info: Info, input: CalendarIncidentInput
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            incident = await services.create_incident(
                info.context.user,
                is_admin=is_admin,
                data=write_from_input(input),
                chronologies=chronology_writes(input),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True, id=incident.id)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def update_calendar_incident(
        self,
        info: Info,
        calendar_incident_id: strawberry.ID,
        input: CalendarIncidentInput,
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.update_incident(
                info.context.user,
                is_admin=is_admin,
                incident_id=int(calendar_incident_id),
                expected_version=maybe_value(input.version),
                data=write_from_input(input),
                chronologies=chronology_writes(input),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def submit_calendar_incident(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.submit_incident(
                info.context.user,
                is_admin=is_admin,
                incident_id=int(calendar_incident_id),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsAdmin])
    async def approve_calendar_incident(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.approve_incident(
                info.context.user, incident_id=int(calendar_incident_id)
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsAdmin])
    async def reject_calendar_incident(
        self, info: Info, calendar_incident_id: strawberry.ID, reason: str
    ) -> GenericMutationReturn:
        try:
            await services.reject_incident(
                info.context.user,
                incident_id=int(calendar_incident_id),
                reason=reason,
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def delete_calendar_incident(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.delete_incident(
                info.context.user,
                is_admin=is_admin,
                incident_id=int(calendar_incident_id),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)
