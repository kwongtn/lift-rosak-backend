"""DB-level tests for the social-media-link vote service wrappers."""

import pytest
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType

from common.models import User, Vote
from incident import services
from incident.models import SocialMediaLink


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=f"test-user-link-vote-{n}"
    )


async def _make_link(user: User, url: str) -> SocialMediaLink:
    return await sync_to_async(SocialMediaLink.objects.create)(url=url, user=user)


async def _link_content_type() -> ContentType:
    return await sync_to_async(ContentType.objects.get_for_model)(SocialMediaLink)


async def _vote_for(user: User, link: SocialMediaLink) -> Vote | None:
    ct = await _link_content_type()
    return await Vote.objects.filter(
        user=user, content_type=ct, object_id=link.id
    ).afirst()


async def _vote_count(link: SocialMediaLink) -> int:
    ct = await _link_content_type()
    return await Vote.objects.filter(content_type=ct, object_id=link.id).acount()


@pytest.mark.django_db
async def test_set_creates_upvote():
    user = await _make_user(1)
    link = await _make_link(user, "https://example.com/link-vote-1")

    await services.set_social_media_link_vote(user, link_id=link.id, value=1)

    vote = await _vote_for(user, link)
    assert vote is not None
    assert vote.value == 1


@pytest.mark.django_db
async def test_set_updates_existing_vote_not_inserts():
    user = await _make_user(2)
    link = await _make_link(user, "https://example.com/link-vote-2")
    await services.set_social_media_link_vote(user, link_id=link.id, value=1)

    await services.set_social_media_link_vote(user, link_id=link.id, value=-1)

    assert await _vote_count(link) == 1
    vote = await _vote_for(user, link)
    assert vote is not None
    assert vote.value == -1


@pytest.mark.django_db
async def test_remove_deletes_vote():
    user = await _make_user(3)
    link = await _make_link(user, "https://example.com/link-vote-3")
    await services.set_social_media_link_vote(user, link_id=link.id, value=1)

    removed = await services.remove_social_media_link_vote(user, link_id=link.id)

    assert removed
    assert await _vote_for(user, link) is None

    removed_again = await services.remove_social_media_link_vote(user, link_id=link.id)
    assert not removed_again


@pytest.mark.django_db
async def test_missing_link_raises_service_error():
    user = await _make_user(4)

    with pytest.raises(services.IncidentServiceError, match="does not exist"):
        await services.set_social_media_link_vote(user, link_id=999_999, value=1)

    with pytest.raises(services.IncidentServiceError, match="does not exist"):
        await services.remove_social_media_link_vote(user, link_id=999_999)
