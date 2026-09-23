"""Vote, social media link, and extraction mutations."""

import strawberry
from graphql.error import GraphQLError
from strawberry.types import Info

from common.schema.scalars import GenericMutationReturn
from incident import extraction, services
from incident.schema.inputs import (
    ExtractDataInput,
    FeedLinkInput,
    LineStatusReportInput,
    SocialMediaLinkInput,
)
from incident.schema.scalars import ExtractedIncidentDataScalar, FeedLinkPayload
from rosak.permissions import IsAdmin, IsLoggedIn, has_admin_claim

from .shared import maybe_value, raise_service_error


@strawberry.type
class VoteMutations:
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

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def upvote_chronology(
        self, info: Info, chronology_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.set_chronology_vote(
                info.context.user, chronology_id=int(chronology_id), value=1
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def downvote_chronology(
        self, info: Info, chronology_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.set_chronology_vote(
                info.context.user, chronology_id=int(chronology_id), value=-1
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def remove_chronology_vote(
        self, info: Info, chronology_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.remove_chronology_vote(
                info.context.user, chronology_id=int(chronology_id)
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)


@strawberry.type
class SocialMediaLinkMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def submit_social_media_link(
        self, info: Info, input: SocialMediaLinkInput
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.submit_social_media_link(
                info.context.user,
                is_admin=is_admin,
                write=services.SocialMediaLinkWrite(
                    url=input.url,
                    title=maybe_value(input.title, "") or "",
                    description=maybe_value(input.description, "") or "",
                    incident_id=(
                        int(incident_id)
                        if (incident_id := maybe_value(input.incident_id)) is not None
                        else None
                    ),
                    category_ids=tuple(maybe_value(input.category_ids) or ()),
                    line_ids=tuple(maybe_value(input.line_ids) or ()),
                    vehicle_ids=tuple(maybe_value(input.vehicle_ids) or ()),
                    station_ids=tuple(maybe_value(input.station_ids) or ()),
                ),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsAdmin])
    async def mark_social_media_link_completed(
        self, info: Info, social_media_link_id: strawberry.ID
    ) -> GenericMutationReturn:
        await services.mark_social_media_link_completed(
            info.context.user, link_id=int(social_media_link_id)
        )
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def update_social_media_link(
        self,
        info: Info,
        social_media_link_id: strawberry.ID,
        input: SocialMediaLinkInput,
    ) -> GenericMutationReturn:
        is_admin = await has_admin_claim(info.context.user)
        try:
            await services.update_social_media_link(
                info.context.user,
                is_admin=is_admin,
                link_id=int(social_media_link_id),
                write=services.SocialMediaLinkWrite(
                    url=input.url,
                    title=maybe_value(input.title, "") or "",
                    # Tri-state: omit (UNSET) leaves unchanged; Some(v) sets to v.
                    description=(
                        input.description.value if input.description else None
                    ),
                    incident_id=(
                        int(incident_id)
                        if (incident_id := maybe_value(input.incident_id)) is not None
                        else None
                    ),
                    category_ids=tuple(maybe_value(input.category_ids) or ()),
                    line_ids=tuple(maybe_value(input.line_ids) or ()),
                    vehicle_ids=tuple(maybe_value(input.vehicle_ids) or ()),
                    station_ids=tuple(maybe_value(input.station_ids) or ()),
                    status=input.status.value if input.status else None,
                ),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsAdmin])
    async def delete_social_media_link(
        self, info: Info, social_media_link_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.delete_social_media_link(
                info.context.user,
                link_id=int(social_media_link_id),
                is_admin=True,
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def submit_feed_link(
        self, info: Info, input: FeedLinkInput
    ) -> FeedLinkPayload:
        try:
            result = await services.submit_feed_link(
                info.context.user,
                url=input.url,
                title=maybe_value(input.title),
                line_ids=[
                    int(line_id) for line_id in (maybe_value(input.line_ids) or ())
                ],
                station_ids=[
                    int(station_id)
                    for station_id in (maybe_value(input.station_ids) or ())
                ],
                status=maybe_value(input.status),
                delay_minutes=maybe_value(input.delay_minutes),
                notes=maybe_value(input.notes, "") or "",
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return FeedLinkPayload(
            ok=True,
            link=result.link,
            is_duplicate=result.is_duplicate,
            duplicate_of_id=result.duplicate_of_id,
            user_vote=result.user_vote,
        )

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def submit_line_status_report(
        self, info: Info, input: LineStatusReportInput
    ) -> GenericMutationReturn:
        try:
            report = await services.submit_line_status_report(
                info.context.user,
                line_id=int(input.line_id),
                status=input.status,
                station_ids=[
                    int(station_id)
                    for station_id in (maybe_value(input.station_ids) or ())
                ],
                delay_minutes=maybe_value(input.delay_minutes),
                notes=maybe_value(input.notes, "") or "",
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True, id=report.id)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def upvote_social_media_link(
        self, info: Info, social_media_link_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.set_social_media_link_vote(
                info.context.user, link_id=int(social_media_link_id), value=1
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def downvote_social_media_link(
        self, info: Info, social_media_link_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.set_social_media_link_vote(
                info.context.user, link_id=int(social_media_link_id), value=-1
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def remove_social_media_link_vote(
        self, info: Info, social_media_link_id: strawberry.ID
    ) -> GenericMutationReturn:
        try:
            await services.remove_social_media_link_vote(
                info.context.user, link_id=int(social_media_link_id)
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)


@strawberry.type
class ExtractionMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def extract_data_from_url(
        self, info: Info, input: ExtractDataInput
    ) -> ExtractedIncidentDataScalar:
        auth_header = info.context.request.headers.get("Authorization")
        id_token = auth_header.removeprefix("Bearer ").strip() if auth_header else None
        try:
            result = await extraction.extract_data_from_url(
                url=input.url, id_token=id_token
            )
        except extraction.ExtractionError as exc:
            raise GraphQLError(str(exc)) from exc
        return ExtractedIncidentDataScalar(
            request_id=result["requestId"], data=result["data"]
        )
