from collections import defaultdict

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Sum
from strawberry.dataloader import DataLoader

from common.models import Vote
from incident.models import CalendarIncident, CalendarIncidentMedia, SocialMediaLink


async def batch_load_medias_from_calendar_incident(keys):
    incident_medias = CalendarIncidentMedia.objects.filter(
        calendar_incident_id__in=keys,
    ).select_related("media")

    incident_dict = defaultdict(set)
    async for incident_media in incident_medias:
        incident_dict[incident_media.calendar_incident_id].add(incident_media.media)

    return [incident_dict.get(key, set()) for key in keys]


async def batch_load_vote_scores(keys):
    """
    Batch load net vote scores (sum of vote values).
    Keys: list of (content_type_id, object_id) tuples
    Returns: list of integers (net scores aligned to keys)
    """
    content_type_ids = [k[0] for k in keys]
    object_ids = [k[1] for k in keys]

    votes = await sync_to_async(list)(
        Vote.objects.filter(
            content_type_id__in=content_type_ids,
            object_id__in=object_ids,
        )
        .values("content_type_id", "object_id")
        .annotate(score=Sum("value"))
    )

    scores = {(v["content_type_id"], v["object_id"]): v["score"] or 0 for v in votes}
    return [scores.get(k, 0) for k in keys]


async def batch_load_vote_breakdown(keys):
    """
    Batch load vote breakdown (upvote/downvote counts).
    Keys: list of (content_type_id, object_id) tuples
    Returns: list of dict {"upvotes": int, "downvotes": int}
    """
    content_type_ids = [k[0] for k in keys]
    object_ids = [k[1] for k in keys]

    votes = await sync_to_async(list)(
        Vote.objects.filter(
            content_type_id__in=content_type_ids,
            object_id__in=object_ids,
        )
        .values("content_type_id", "object_id", "value")
        .annotate(count=Count("id"))
    )

    breakdown = defaultdict(lambda: {"upvotes": 0, "downvotes": 0})
    for v in votes:
        key = (v["content_type_id"], v["object_id"])
        if v["value"] == 1:
            breakdown[key]["upvotes"] = v["count"]
        elif v["value"] == -1:
            breakdown[key]["downvotes"] = v["count"]

    return [breakdown[k] for k in keys]


async def batch_load_user_vote_value(keys):
    """
    Batch load current user's vote value for objects.
    Keys: list of (user_id, content_type_id, object_id) tuples
    Returns: list of int (-1, 0, 1) aligned to keys
    """
    user_ids = [k[0] for k in keys]
    content_type_ids = [k[1] for k in keys]
    object_ids = [k[2] for k in keys]

    votes = await sync_to_async(list)(
        Vote.objects.filter(
            user_id__in=user_ids,
            content_type_id__in=content_type_ids,
            object_id__in=object_ids,
        ).values("user_id", "content_type_id", "object_id", "value")
    )

    vote_map = {
        (v["user_id"], v["content_type_id"], v["object_id"]): v["value"] for v in votes
    }
    return [vote_map.get(k, 0) for k in keys]


async def batch_load_incident_links(keys):
    """
    Batch load SocialMediaLink rows for the incident cards' link lists (page one).

    Keys: list of ``(incident_id, first)`` tuples — the nested
    ``CalendarIncidentScalar.links`` field, when called without ``after``, loads
    through this loader, so a feed of N cards issues ONE row query instead of
    N+1 (repo rule: resolvers that fan out to related rows must use a loader).

    Continuation pages (``after`` present) are NOT loadable this way: each parent
    carries its own per-parent keyset cursor, so per-parent windows cannot be
    batched into one shared query — the field queries those individually
    (documented in the field's docstring).

    Returns: list of lists of SocialMediaLink, aligned to keys, each sliced to
    ``first + 1`` rows (the extra row lets the field compute has_next_page
    without a separate count query). The lazy iterator stops as soon as every
    incident has its window, so the fetch stays bounded to the largest requested
    first-page size rather than pulling every link of every batched incident.
    """
    incident_ids = [key[0] for key in keys]
    max_first = max(key[1] for key in keys)

    content_type = await sync_to_async(ContentType.objects.get_for_model)(
        CalendarIncident
    )

    links = SocialMediaLink.objects.filter(
        content_type=content_type,
        object_id__in=incident_ids,
    ).order_by("-created", "-id")

    target = max_first + 1
    by_incident = defaultdict(list)
    async for link in links:
        by_incident[link.object_id].append(link)
        if len(by_incident) == len(incident_ids) and all(
            len(rows) >= target for rows in by_incident.values()
        ):
            break

    return [by_incident.get(key[0], [])[: key[1] + 1] for key in keys]


IncidentContextLoaders = {
    "medias_from_calendar_incident_loader": DataLoader(
        load_fn=batch_load_medias_from_calendar_incident
    ),
    "vote_scores": DataLoader(batch_load_vote_scores),
    "vote_breakdown": DataLoader(batch_load_vote_breakdown),
    "user_vote_value": DataLoader(batch_load_user_vote_value),
    "incident_links": DataLoader(batch_load_incident_links),
}
