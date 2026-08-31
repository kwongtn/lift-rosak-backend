"""Vote, social media link, and extraction mutations."""

import strawberry
from graphql.error import GraphQLError
from strawberry.types import Info

from common.schema.scalars import GenericMutationReturn
from incident import extraction, services
from incident.schema.inputs import ExtractDataInput, SocialMediaLinkInput
from incident.schema.scalars import ExtractedIncidentDataScalar
from rosak.permissions import IsAdmin, IsLoggedIn

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


@strawberry.type
class SocialMediaLinkMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def submit_social_media_link(
        self, info: Info, input: SocialMediaLinkInput
    ) -> GenericMutationReturn:
        try:
            await services.submit_social_media_link(
                info.context.user,
                write=services.SocialMediaLinkWrite(
                    url=input.url,
                    title=maybe_value(input.title, "") or "",
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
