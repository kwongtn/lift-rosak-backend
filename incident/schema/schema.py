from decimal import Decimal
from typing import List

import strawberry
import strawberry_django
from graphql.error import GraphQLError
from strawberry.types import Info

from common.schema.scalars import GenericMutationReturn
from incident import services
from incident.schema.filters import (
    CalendarIncidentFilter,
    StationIncidentFilter,
    VehicleIncidentFilter,
)
from incident.schema.inputs import (
    CalendarIncidentChronologyInput,
    CalendarIncidentInput,
)
from incident.schema.orderings import CalendarIncidentOrder
from incident.schema.resolvers import get_calendar_incidents_by_severity_count
from incident.schema.scalars import (
    CalendarIncidentGroupByDateSeverityScalar,
    CalendarIncidentScalar,
    StationIncident,
    VehicleIncident,
)
from rosak.permissions import IsAdmin, IsLoggedIn, has_admin_claim


def _maybe_value(maybe_field, default=None):
    """Unwrap a Strawberry Maybe field.

    Returns `default` when the field was omitted (UNSET) or is a plain
    None; otherwise returns the wrapped payload (`Some(value)` -> `value`,
    `Some(None)` -> `None`).
    """
    if maybe_field is None or maybe_field is strawberry.UNSET:
        return default
    return maybe_field.value


def _write_from_input(data: CalendarIncidentInput) -> services.IncidentWrite:
    return services.IncidentWrite(
        title=data.title,
        brief=data.brief,
        start_datetime=data.start_datetime,
        severity=data.severity,
        end_datetime=_maybe_value(data.end_datetime),
        long_term=_maybe_value(data.long_term, False),
        inaccurate=_maybe_value(data.inaccurate, False),
        impact_factor=Decimal(str(_maybe_value(data.impact_factor, 0))),
        details=_maybe_value(data.details, ""),
        line_ids=tuple(_maybe_value(data.line_ids) or ()),
        vehicle_ids=tuple(_maybe_value(data.vehicle_ids) or ()),
        station_ids=tuple(_maybe_value(data.station_ids) or ()),
        category_ids=tuple(_maybe_value(data.category_ids) or ()),
    )


def _chronology_write_from_input(
    chronology: CalendarIncidentChronologyInput,
) -> services.ChronologyWrite:
    return services.ChronologyWrite(
        indicator=chronology.indicator,
        datetime=_maybe_value(chronology.datetime),
        source_url=_maybe_value(chronology.source_url, ""),
        content=_maybe_value(chronology.content, ""),
    )


def _chronology_writes(
    data: CalendarIncidentInput,
) -> tuple[services.ChronologyWrite, ...]:
    return tuple(
        _chronology_write_from_input(chronology)
        for chronology in _maybe_value(data.chronologies) or ()
    )


def _raise_service_error(exc: services.IncidentServiceError) -> None:
    raise GraphQLError(str(exc)) from exc


@strawberry.type
class IncidentScalars:
    vehicle_incidents: List[VehicleIncident] = strawberry_django.field(
        filters=VehicleIncidentFilter
    )
    station_incidents: List[StationIncident] = strawberry_django.field(
        filters=StationIncidentFilter
    )

    calendar_incidents: List[CalendarIncidentScalar] = strawberry_django.field(
        filters=CalendarIncidentFilter,
        order=CalendarIncidentOrder,
    )

    calendar_incidents_by_severity_count: List[
        CalendarIncidentGroupByDateSeverityScalar
    ] = strawberry.field(resolver=get_calendar_incidents_by_severity_count)


@strawberry.type
class IncidentMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def create_calendar_incident(
        self, info: Info, input: CalendarIncidentInput
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.create_incident(
                info.context.user,
                is_admin=is_admin,
                data=_write_from_input(input),
                chronologies=_chronology_writes(input),
            )
        except services.IncidentServiceError as exc:
            _raise_service_error(exc)
        return GenericMutationReturn(ok=True)

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
                expected_version=_maybe_value(input.version),
                data=_write_from_input(input),
                chronologies=_chronology_writes(input),
            )
        except services.IncidentServiceError as exc:
            _raise_service_error(exc)
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
            _raise_service_error(exc)
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
            _raise_service_error(exc)
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
            _raise_service_error(exc)
        return GenericMutationReturn(ok=True)

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
                write=_chronology_write_from_input(input),
            )
        except services.IncidentServiceError as exc:
            _raise_service_error(exc)
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
                write=_chronology_write_from_input(input),
            )
        except services.IncidentServiceError as exc:
            _raise_service_error(exc)
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
            _raise_service_error(exc)
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
            _raise_service_error(exc)
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
            _raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def upvote(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> GenericMutationReturn:
        await services.set_incident_vote(
            info.context.user, incident_id=int(calendar_incident_id), value=1
        )
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def downvote(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> GenericMutationReturn:
        await services.set_incident_vote(
            info.context.user, incident_id=int(calendar_incident_id), value=-1
        )
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def remove_vote(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> GenericMutationReturn:
        await services.remove_incident_vote(
            info.context.user, incident_id=int(calendar_incident_id)
        )
        return GenericMutationReturn(ok=True)
