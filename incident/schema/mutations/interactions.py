"""Vote, social media link, and extraction mutations."""

from typing import List, Optional

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
from incident.schema.scalars import (
    ExtractedIncidentDataScalar,
    FeedLinkPayload,
    VoteMutationPayload,
)

# Imported from the submodule, NOT as ``services.UNSET``: the service package
# re-exports the write helpers, and this sentinel is a detail of the write
# dataclass's tri-state, not a public service API. Do not "tidy" it into the
# package namespace.
#
# ``social_link_threads`` follows the same rule as the sentinel above and
# ``social_link_visibility`` does: grouping is a self-contained service, so it
# is referenced by module rather than added to the package re-export.
from incident.services import social_link_threads
from incident.services.social_links import UNSET as OCCURRED_AT_UNSET
from rosak.permissions import IsAdmin, IsLoggedIn, has_admin_claim

from .shared import maybe_value, raise_service_error


def _vote_payload(outcome: services.VoteOutcome) -> VoteMutationPayload:
    """The one place a `VoteOutcome` becomes a GraphQL payload.

    Every vote mutation returns this, so "what the client sees after a click" is
    the same shape for incidents, chronology rows and social-media links.
    """
    return VoteMutationPayload(
        ok=True,
        user_vote=outcome.user_vote,
        vote_score=outcome.vote_score,
        upvotes=outcome.upvotes,
        downvotes=outcome.downvotes,
    )


@strawberry.type
class VoteMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def upvote(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> VoteMutationPayload:
        outcome = await services.set_incident_vote(
            info.context.user, incident_id=int(calendar_incident_id), value=1
        )
        return _vote_payload(outcome)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def downvote(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> VoteMutationPayload:
        outcome = await services.set_incident_vote(
            info.context.user, incident_id=int(calendar_incident_id), value=-1
        )
        return _vote_payload(outcome)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def remove_vote(
        self, info: Info, calendar_incident_id: strawberry.ID
    ) -> VoteMutationPayload:
        outcome = await services.remove_incident_vote(
            info.context.user, incident_id=int(calendar_incident_id)
        )
        return _vote_payload(outcome)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def upvote_chronology(
        self, info: Info, chronology_id: strawberry.ID
    ) -> VoteMutationPayload:
        try:
            outcome = await services.set_chronology_vote(
                info.context.user, chronology_id=int(chronology_id), value=1
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return _vote_payload(outcome)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def downvote_chronology(
        self, info: Info, chronology_id: strawberry.ID
    ) -> VoteMutationPayload:
        try:
            outcome = await services.set_chronology_vote(
                info.context.user, chronology_id=int(chronology_id), value=-1
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return _vote_payload(outcome)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def remove_chronology_vote(
        self, info: Info, chronology_id: strawberry.ID
    ) -> VoteMutationPayload:
        try:
            outcome = await services.remove_chronology_vote(
                info.context.user, chronology_id=int(chronology_id)
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return _vote_payload(outcome)


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
                    # Omitted and explicit null both mean "now()": there is no
                    # null state at insert time, the column is NOT NULL.
                    occurred_at=maybe_value(input.occurred_at),
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
                    # Tri-state, and all three states differ: UNSET (a falsy
                    # Maybe — Strawberry's ``Some.__bool__`` is always True, so
                    # this is exactly "omitted") must reach the service as its
                    # own sentinel. Collapsing it into the explicit null would
                    # silently reset the event time to the submission instant
                    # on every partial re-send.
                    occurred_at=(
                        OCCURRED_AT_UNSET
                        if not input.occurred_at
                        else input.occurred_at.value
                    ),
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
    async def group_social_media_links(
        self,
        info: Info,
        link_ids: List[strawberry.ID],
        parent_id: Optional[strawberry.ID] = None,
    ) -> GenericMutationReturn:
        """Group links as sublinks; omit ``parentId`` to start a new thread.

        Deliberately a dedicated id-only mutation rather than a mode of
        ``updateSocialMediaLink``: that input is REPLACE-NOT-PATCH (it blanks
        ``title`` and strips four M2M tag sets on every call), so routing a
        grouping action through it would silently destroy the links' metadata.

        Returns the root's id in ``id`` so the client can refetch that one thread
        (root + sublinks) instead of guessing which row it now belongs to — the
        same convention ``submitLineStatusReport`` uses.

        ``parentId`` is a BREAKING RENAME of the previous ``threadId``, and
        deliberately NOT an alias. An alias would keep accepting the old
        argument and so keep serving the one-level behaviour it named: a client
        sending ``threadId`` would go on nesting its links under the thread's
        root and would never discover that the sublink level it now wants is
        spelled differently. It is declared ``ID = null`` rather than a
        ``Maybe`` because omitted and explicit null genuinely mean the same thing
        here — "no target, elect a root" — and a ``Maybe`` would advertise a
        third state that does not exist. ``reorderSocialMediaLinks`` below is the
        opposite case, and does need one.
        """
        is_admin = await has_admin_claim(info.context.user)
        try:
            root = await social_link_threads.group_social_media_links(
                info.context.user,
                is_admin=is_admin,
                link_ids=[int(link_id) for link_id in link_ids],
                parent_id=(int(parent_id) if parent_id is not None else None),
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True, id=root.id)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def ungroup_social_media_links(
        self, info: Info, link_ids: List[strawberry.ID]
    ) -> GenericMutationReturn:
        """Detach the given links, promoting them to roots. ``ok`` only — there is
        no row to name back, since a link's own sublinks stay attached to it.
        """
        is_admin = await has_admin_claim(info.context.user)
        try:
            await social_link_threads.ungroup_social_media_links(
                info.context.user,
                is_admin=is_admin,
                link_ids=[int(link_id) for link_id in link_ids],
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def reorder_social_media_links(
        self,
        info: Info,
        link_ids: List[strawberry.ID],
        parent_id: strawberry.Maybe[Optional[strawberry.ID]] = strawberry.UNSET,
    ) -> GenericMutationReturn:
        """Set one sibling sequence explicitly; ``ok`` only.

        WHY A ``Maybe`` HERE AND NOT IN ``groupSocialMediaLinks``: there, omitted
        and ``null`` mean the same thing (elect a root), so ``ID = null`` is the
        honest signature. Here they are genuinely DIFFERENT requests — an explicit
        ``parentId: null`` means "reorder the ROOTS" and is a real use (the
        console deciding which link leads a thread), while an OMITTED
        ``parentId`` names no sibling set at all. A plain ``ID = null`` would
        silently answer the second with the first, so a client that forgot the
        argument would reorder every root in the system.

        The three states, all of which reach this resolver:

        * UNSET (omitted) — falsy, because ``Some.__bool__`` is always ``True``
          while ``UNSET`` is falsy. Rejected below.
        * ``Some(None)`` — truthy, ``.value is None``: reorder the roots.
        * ``Some(ID)`` — truthy, ``.value`` is the id: reorder that link's sublinks.
        """
        if not parent_id:
            raise GraphQLError(
                "reorderSocialMediaLinks requires parentId. Send an explicit "
                "null to reorder the roots, or the id of the link whose sublinks "
                "are being ordered."
            )
        is_admin = await has_admin_claim(info.context.user)
        try:
            await social_link_threads.reorder_social_media_links(
                info.context.user,
                is_admin=is_admin,
                parent_id=(
                    int(parent_id.value) if parent_id.value is not None else None
                ),
                link_ids=[int(link_id) for link_id in link_ids],
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
                # Omitted and explicit null both mean "now()": the column is
                # NOT NULL, so the default has to fire in the INSERT.
                occurred_at=maybe_value(input.occurred_at),
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
    ) -> VoteMutationPayload:
        try:
            outcome = await services.set_social_media_link_vote(
                info.context.user, link_id=int(social_media_link_id), value=1
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return _vote_payload(outcome)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def downvote_social_media_link(
        self, info: Info, social_media_link_id: strawberry.ID
    ) -> VoteMutationPayload:
        try:
            outcome = await services.set_social_media_link_vote(
                info.context.user, link_id=int(social_media_link_id), value=-1
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return _vote_payload(outcome)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def remove_social_media_link_vote(
        self, info: Info, social_media_link_id: strawberry.ID
    ) -> VoteMutationPayload:
        try:
            outcome = await services.remove_social_media_link_vote(
                info.context.user, link_id=int(social_media_link_id)
            )
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return _vote_payload(outcome)


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
