"""Social media link submission and completion business logic."""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from common.models import User
from incident.enums import SocialMediaLinkStatus
from incident.models import CalendarIncident, SocialMediaLink

from .access import get_incident
from .errors import IncidentServiceError


class _Unset:
    """Sentinel type for "the caller never mentioned this field".

    Named and shaped after ``strawberry.UNSET`` so the mutation layer can hand
    an omitted GraphQL field straight through instead of inventing a private
    vocabulary. Falsy, so ``if not write.x`` treats it as absent.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class SocialMediaLinkWrite:
    url: str
    title: str = ""
    # None = don't change (update); "" / "text" = set to that value.
    description: str | None = None
    incident_id: int | None = None
    category_ids: tuple[int, ...] = ()
    line_ids: tuple[int, ...] = ()
    vehicle_ids: tuple[int, ...] = ()
    station_ids: tuple[int, ...] = ()
    # None = don't change (update); enum value = set to that value.
    status: str | None = None
    # TRIP-STATE, and the three states do NOT mean the same thing on the two
    # write paths, so read the call site before reusing this field:
    #   UNSET         -> update: leave the stored value alone;
    #                    submit: omit the kwarg so the column default fires.
    #   datetime      -> set verbatim, both paths.
    #   None          -> update: reset to ``link.created`` ("this happened when
    #                    it was reported"), the one always-present non-null
    #                    fallback since a community link has no provider post
    #                    time; submit: no explicit-null state exists, the
    #                    column is NOT NULL, so it collapses to the default.
    occurred_at: dt.datetime | None | _Unset = UNSET


async def submit_social_media_link(
    user: User, *, is_admin: bool, write: SocialMediaLinkWrite
) -> SocialMediaLink:
    content_type = None
    object_id = None
    if write.incident_id is not None:
        await get_incident(write.incident_id)
        content_type = await sync_to_async(ContentType.objects.get_for_model)(
            CalendarIncident
        )
        object_id = write.incident_id

    status = (
        SocialMediaLinkStatus.LIVE
        if is_admin
        else SocialMediaLinkStatus.PENDING_APPROVAL
    )
    # Omitted entirely (not passed as None) when the caller gave no
    # ``occurred_at``: the column is NOT NULL with ``default=timezone.now``, and
    # the INSERT already generates ``created`` in the same statement, so the
    # default lands within microseconds of it. Passing None here would violate
    # NOT NULL (IntegrityError), and passing timezone.now() ourselves would
    # duplicate the model's one source of truth for "when nothing was supplied".
    occurred_at_kwargs: dict[str, Any] = {}
    if isinstance(write.occurred_at, dt.datetime):
        occurred_at_kwargs["occurred_at"] = write.occurred_at

    link = await sync_to_async(SocialMediaLink.objects.create)(
        url=write.url,
        title=write.title or "",
        description=write.description or "",
        user=user,
        status=status,
        content_type=content_type,
        object_id=object_id,
        **occurred_at_kwargs,
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


async def update_social_media_link(
    user: User, *, is_admin: bool, link_id: int, write: SocialMediaLinkWrite
) -> SocialMediaLink:
    link = await SocialMediaLink.objects.aget(pk=link_id)

    if not is_admin and link.user_id != user.id:
        raise IncidentServiceError(
            f"SocialMediaLink {link_id} is not owned by this user."
        )

    def _sync() -> None:
        link.url = write.url
        link.title = write.title or ""
        if write.description is not None:
            link.description = write.description
        if write.status is not None:
            link.status = write.status
        if isinstance(write.occurred_at, dt.datetime):
            link.occurred_at = write.occurred_at
        elif write.occurred_at is None:
            # Explicit null, not an omission: the caller wants the "happened
            # when it was reported" reading back. ``link.created`` is the only
            # non-null value guaranteed to exist on every link (occurred_at is
            # NOT NULL, posted_at is provider-only and usually NULL here).
            link.occurred_at = link.created
        # else: UNSET — leave whatever the card already renders alone.
        if write.incident_id is not None:
            content_type = ContentType.objects.get_for_model(CalendarIncident)
            link.content_type = content_type
            link.object_id = write.incident_id
        # incident_id is submit-only; None leaves the association untouched.
        if not is_admin:
            # Non-admin edits go back into the approval queue (mirrors
            # incident edits) instead of landing live.
            link.status = SocialMediaLinkStatus.PENDING_APPROVAL
            link.completed = False
            link.completed_at = None
            link.completed_by = None
        link.save()
        link.categories.set(write.category_ids)
        link.lines.set(write.line_ids)
        link.vehicles.set(write.vehicle_ids)
        link.stations.set(write.station_ids)

    if write.incident_id is not None:
        await get_incident(write.incident_id)

    await sync_to_async(_sync)()
    await sync_to_async(link.refresh_from_db)()
    return link


async def delete_social_media_link(
    user: User, *, link_id: int, is_admin: bool = False
) -> None:
    link = await SocialMediaLink.objects.aget(pk=link_id)
    if not is_admin and link.user_id != user.id:
        raise IncidentServiceError(
            f"SocialMediaLink {link_id} is not owned by this user."
        )
    await link.adelete()
