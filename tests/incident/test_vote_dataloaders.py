import pytest
from collections import defaultdict
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from common.models import User, Vote
from incident.models import CalendarIncident


@pytest.mark.django_db
async def test_vote_score_aggregation():
    """5 upvotes + 2 downvotes = +3 net score (from different users)"""
    # Use sync_to_async for ORM calls within async test
    from asgiref.sync import sync_to_async

    users = []
    for i in range(7):
        user = await sync_to_async(User.objects.create)(firebase_id=f"test-user-vote-agg-{i}")
        users.append(user)

    incident = await sync_to_async(CalendarIncident.objects.create)(
        title="Vote Test Incident",
        brief="Test incident for vote aggregation",
        severity="MINOR",
        start_datetime="2026-01-01T00:00:00Z",
    )
    ct = await sync_to_async(ContentType.objects.get)(app_label="incident", model="calendarincident")

    # 5 upvotes from users 0-4
    for i in range(5):
        await sync_to_async(Vote.objects.create)(user_id=users[i].id, content_type=ct, object_id=incident.id, value=1)

    # 2 downvotes from users 5-6
    for i in range(5, 7):
        await sync_to_async(Vote.objects.create)(user_id=users[i].id, content_type=ct, object_id=incident.id, value=-1)

    from strawberry.dataloader import DataLoader

    async def batch_load_vote_scores(keys):
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

        scores = {
            (v["content_type_id"], v["object_id"]): v["score"] or 0 for v in votes
        }
        return [scores.get(k, 0) for k in keys]

    loader = DataLoader(batch_load_vote_scores)
    score = await loader.load((ct.id, incident.id))
    assert score == 3


@pytest.mark.django_db
async def test_vote_breakdown_loader():
    """Separate upvote/downvote counts"""
    from asgiref.sync import sync_to_async

    users = []
    for i in range(7):
        user = await sync_to_async(User.objects.create)(firebase_id=f"test-user-vote-brk-{i}")
        users.append(user)

    incident = await sync_to_async(CalendarIncident.objects.create)(
        title="Vote Breakdown Test Incident",
        brief="Test incident for vote breakdown",
        severity="MINOR",
        start_datetime="2026-01-01T00:00:00Z",
    )
    ct = await sync_to_async(ContentType.objects.get)(app_label="incident", model="calendarincident")

    # 5 upvotes from users 0-4
    for i in range(5):
        await sync_to_async(Vote.objects.create)(user_id=users[i].id, content_type=ct, object_id=incident.id, value=1)

    # 2 downvotes from users 5-6
    for i in range(5, 7):
        await sync_to_async(Vote.objects.create)(user_id=users[i].id, content_type=ct, object_id=incident.id, value=-1)

    from strawberry.dataloader import DataLoader

    async def batch_load_vote_breakdown(keys):
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

    loader = DataLoader(batch_load_vote_breakdown)
    breakdown = await loader.load((ct.id, incident.id))
    assert breakdown["upvotes"] == 5
    assert breakdown["downvotes"] == 2


@pytest.mark.django_db
async def test_user_vote_value_loader():
    """Current user's vote value for objects"""
    from asgiref.sync import sync_to_async

    user1 = await sync_to_async(User.objects.create)(firebase_id="test-user-vote-value-1")
    user2 = await sync_to_async(User.objects.create)(firebase_id="test-user-vote-value-2")
    incident = await sync_to_async(CalendarIncident.objects.create)(
        title="Vote Value Test Incident",
        brief="Test incident for vote value",
        severity="MINOR",
        start_datetime="2026-01-01T00:00:00Z",
    )
    ct = await sync_to_async(ContentType.objects.get)(app_label="incident", model="calendarincident")

    # user1 upvotes
    await sync_to_async(Vote.objects.create)(user_id=user1.id, content_type=ct, object_id=incident.id, value=1)
    # user2 downvotes
    await sync_to_async(Vote.objects.create)(user_id=user2.id, content_type=ct, object_id=incident.id, value=-1)

    from strawberry.dataloader import DataLoader

    async def batch_load_user_vote_value(keys):
        user_ids = [k[0] for k in keys]
        content_type_ids = [k[1] for k in keys]
        object_ids = [k[2] for k in keys]

        votes = await sync_to_async(list)(
            Vote.objects.filter(
                user_id__in=user_ids,
                content_type_id__in=content_type_ids,
                object_id__in=object_ids,
            )
            .values("user_id", "content_type_id", "object_id", "value")
        )

        vote_map = {
            (v["user_id"], v["content_type_id"], v["object_id"]): v["value"]
            for v in votes
        }
        return [vote_map.get(k, 0) for k in keys]

    loader = DataLoader(batch_load_user_vote_value)

    # Load user1's vote value
    score = await loader.load((user1.id, ct.id, incident.id))
    assert score == 1

    # Load user2's vote value
    score = await loader.load((user2.id, ct.id, incident.id))
    assert score == -1

    # Load a user who hasn't voted
    user3 = await sync_to_async(User.objects.create)(firebase_id="test-user-vote-value-3")
    score = await loader.load((user3.id, ct.id, incident.id))
    assert score == 0