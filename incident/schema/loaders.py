from collections import defaultdict

from asgiref.sync import sync_to_async
from django.db.models import Count, Sum
from strawberry.dataloader import DataLoader

from common.models import Vote
from incident.models import CalendarIncidentMedia


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


IncidentContextLoaders = {
    "medias_from_calendar_incident_loader": DataLoader(
        load_fn=batch_load_medias_from_calendar_incident
    ),
    "vote_scores": DataLoader(batch_load_vote_scores),
    "vote_breakdown": DataLoader(batch_load_vote_breakdown),
    "user_vote_value": DataLoader(batch_load_user_vote_value),
}
