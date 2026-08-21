"""Chronology CRUD and reorder mutations."""

import strawberry
from strawberry.types import Info

from common.schema.scalars import GenericMutationReturn
from incident import services
from incident.schema.inputs import CalendarIncidentChronologyInput
from rosak.permissions import IsAdmin, IsLoggedIn, has_admin_claim

from .shared import chronology_write_from_input, raise_service_error


@strawberry.type
class ChronologyMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def create_chronology(
        self,
        info: Info,
        calendar_incident_id: strawberry.ID,
        input: CalendarIncidentChronologyInput,
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.create_chronology(
                info.context.user,
                is_admin=is_admin,
                calendar_incident_id=int(calendar_incident_id),
                write=chronology_write_from_input(input),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def update_chronology(
        self,
        info: Info,
        chronology_id: strawberry.ID,
        input: CalendarIncidentChronologyInput,
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.update_chronology(
                info.context.user,
                is_admin=is_admin,
                chronology_id=int(chronology_id),
                write=chronology_write_from_input(input),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsAdmin])
    async def approve_chronology(
        self, info: Info, chronology_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.approve_chronology(
                info.context.user, chronology_id=int(chronology_id)
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def reorder_chronology(
        self, info: Info, chronology_id: strawberry.ID, target_order: int
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.reorder_chronology(
                info.context.user,
                is_admin=is_admin,
                chronology_id=int(chronology_id),
                target_order=target_order,
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def delete_chronology(
        self, info: Info, chronology_id: strawberry.ID
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.delete_chronology(
                info.context.user,
                is_admin=is_admin,
                chronology_id=int(chronology_id),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)
