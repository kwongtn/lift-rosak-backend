"""Real-schema tests for `SocialMediaLinkScalar` vote state + canonical URL.

Executes the GraphQL schema over `publicSocialMediaLinks` and asserts the
resolved `voteScore` / `userVote` / `normalizedUrl` values, including the
anonymous-viewer default (`userVote` = 0, never null).
"""

import copy

import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from dotmap import DotMap

from common.models import User, Vote
from incident.models import SocialMediaLink
from incident.schema.loaders import IncidentContextLoaders


def _build_schema():
    import django

    django.setup()
    from rosak.schema import Query

    return strawberry.Schema(query=Query)


def _context(user=None):
    return DotMap(
        {
            "loaders": {"incident": copy.deepcopy(IncidentContextLoaders)},
            "request": None,
            "response": None,
            "user": user,
        }
    )


async def _links(user=None):
    schema = _build_schema()
    result = await schema.execute(
        """
        query {
          publicSocialMediaLinks {
            edges {
              node {
                id
                normalizedUrl
                voteScore
                userVote
              }
            }
          }
        }
        """,
        context_value=_context(user),
    )
    assert result.errors is None, result.errors
    return result.data["publicSocialMediaLinks"]["edges"]


def _node(edges, link_id):
    return next(e["node"] for e in edges if e["node"]["id"] == str(link_id))


async def _make_user(firebase_id: str) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=firebase_id)


async def _make_link(user: User, url: str) -> SocialMediaLink:
    return await sync_to_async(SocialMediaLink.objects.create)(url=url, user=user)


async def _cast_vote(user: User, link: SocialMediaLink, value: int) -> None:
    ct = await sync_to_async(ContentType.objects.get_for_model)(SocialMediaLink)
    await Vote.objects.acreate(
        user=user, content_type=ct, object_id=link.id, value=value
    )


@pytest.mark.django_db
async def test_vote_score_zero_when_no_votes():
    user = await _make_user("link-scalar-novote")
    link = await _make_link(user, "https://example.com/scalar-novote?v=1")

    edges = await _links()

    assert _node(edges, link.id)["voteScore"] == 0


@pytest.mark.django_db
async def test_vote_score_reflects_cast_votes():
    submitter = await _make_user("link-scalar-score-owner")
    up = await _make_user("link-scalar-score-up")
    down = await _make_user("link-scalar-score-down")
    link = await _make_link(submitter, "https://example.com/scalar-score?v=1")

    await _cast_vote(up, link, 1)
    await _cast_vote(down, link, -1)
    assert _node(await _links(), link.id)["voteScore"] == 0

    extra_up = await _make_user("link-scalar-score-up2")
    await _cast_vote(extra_up, link, 1)
    assert _node(await _links(), link.id)["voteScore"] == 1


@pytest.mark.django_db
async def test_user_vote_zero_for_anonymous_viewer():
    submitter = await _make_user("link-scalar-anon-owner")
    voter = await _make_user("link-scalar-anon-voter")
    link = await _make_link(submitter, "https://example.com/scalar-anon?v=1")
    await _cast_vote(voter, link, 1)

    node = _node(await _links(), link.id)

    assert node["userVote"] == 0


@pytest.mark.django_db
async def test_user_vote_value_for_logged_in_voter():
    submitter = await _make_user("link-scalar-voter-owner")
    voter = await _make_user("link-scalar-voter")
    link = await _make_link(submitter, "https://example.com/scalar-user-vote?v=1")
    await _cast_vote(voter, link, 1)

    node = _node(await _links(user=voter), link.id)

    assert node["userVote"] == 1


@pytest.mark.django_db
async def test_normalized_url_exposed_and_matches_model():
    user = await _make_user("link-scalar-normalized")
    link = await _make_link(
        user, "https://example.com/scalar-normalized?utm_source=newsletter&id=5"
    )

    node = _node(await _links(), link.id)

    assert node["normalizedUrl"] == link.normalized_url
    assert node["normalizedUrl"] is not None
