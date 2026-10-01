"""Vote business logic over the generic Vote model.

The core helpers are content-type-agnostic (any model with a GenericRelation
to common.Vote works). The incident- and chronology-scoped wrappers keep the
existing public function signatures so callers and tests are unaffected.

Every write helper returns a `VoteOutcome`: the target's vote state as it stands
immediately after the write. A GraphQL vote mutation hands that snapshot back so
the client's post-click display comes from the server instead of from an
optimistic guess that races its own echo (and every other voter).
"""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Sum

from common.models import User, Vote
from incident.models import CalendarIncidentChronology, SocialMediaLink

from .access import get_incident
from .errors import IncidentServiceError


@dataclass(frozen=True)
class VoteOutcome:
    """The vote state of a target right after a write, for whoever performed it.

    `user_vote` is the CALLER's own vote (-1 / 0 / 1) and the counters cover
    every voter, so one snapshot is enough to repaint a vote control completely.
    """

    user_vote: int
    vote_score: int
    upvotes: int
    downvotes: int


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


def _aggregate_votes(user: User, content_type: ContentType, object_id: int) -> dict:
    """Counters AND the caller's own vote in ONE round-trip.

    `my_up` / `my_down` are filtered counts rather than a second query: the
    `unique_together ("user", "content_type", "object_id")` constraint means a
    caller can hold at most one of them, so the pair answers "what does the
    caller see" without the second query a separate lookup would need.
    """
    return Vote.objects.filter(
        content_type=content_type,
        object_id=object_id,
    ).aggregate(
        vote_score=Sum("value"),
        upvotes=Count("pk", filter=Q(value=1)),
        downvotes=Count("pk", filter=Q(value=-1)),
        my_up=Count("pk", filter=Q(user=user, value=1)),
        my_down=Count("pk", filter=Q(user=user, value=-1)),
    )


async def _vote_outcome(user: User, *, target) -> VoteOutcome:
    content_type = await _content_type_for(type(target))
    row = await sync_to_async(_aggregate_votes)(user, content_type, target.pk)
    return VoteOutcome(
        user_vote=1 if row["my_up"] else (-1 if row["my_down"] else 0),
        # `Sum` is None on a target nobody has voted on — a brand new link's score is 0, not None.
        vote_score=row["vote_score"] or 0,
        upvotes=row["upvotes"],
        downvotes=row["downvotes"],
    )


async def _get_chronology(chronology_id: int) -> CalendarIncidentChronology:
    try:
        return await CalendarIncidentChronology.objects.aget(pk=chronology_id)
    except CalendarIncidentChronology.DoesNotExist as exc:
        raise IncidentServiceError(
            f"CalendarIncidentChronology {chronology_id} does not exist."
        ) from exc


async def _get_social_media_link(link_id: int) -> SocialMediaLink:
    try:
        return await SocialMediaLink.objects.aget(pk=link_id)
    except SocialMediaLink.DoesNotExist as exc:
        raise IncidentServiceError(
            f"SocialMediaLink {link_id} does not exist."
        ) from exc


# --- Incident-scoped wrappers (backward compatible) ---


async def set_incident_vote(user: User, *, incident_id: int, value: int) -> VoteOutcome:
    incident = await get_incident(incident_id)
    await _apply_vote(user, target=incident, value=value)
    return await _vote_outcome(user, target=incident)


async def remove_incident_vote(user: User, *, incident_id: int) -> VoteOutcome:
    incident = await get_incident(incident_id)
    await _remove_vote(user, target=incident)
    return await _vote_outcome(user, target=incident)


# --- Chronology-scoped wrappers ---


async def set_chronology_vote(
    user: User, *, chronology_id: int, value: int
) -> VoteOutcome:
    chronology = await _get_chronology(chronology_id)
    await _apply_vote(user, target=chronology, value=value)
    return await _vote_outcome(user, target=chronology)


async def remove_chronology_vote(user: User, *, chronology_id: int) -> VoteOutcome:
    chronology = await _get_chronology(chronology_id)
    await _remove_vote(user, target=chronology)
    return await _vote_outcome(user, target=chronology)


# --- Social-media-link-scoped wrappers ---


async def set_social_media_link_vote(
    user: User, *, link_id: int, value: int
) -> VoteOutcome:
    link = await _get_social_media_link(link_id)
    await _apply_vote(user, target=link, value=value)
    return await _vote_outcome(user, target=link)


async def remove_social_media_link_vote(user: User, *, link_id: int) -> VoteOutcome:
    link = await _get_social_media_link(link_id)
    await _remove_vote(user, target=link)
    return await _vote_outcome(user, target=link)
