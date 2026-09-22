"""Real-schema tests for `SocialMediaLinkScalar.voteBreakdown`.

Executes the GraphQL schema over `publicSocialMediaLinks` and asserts the
resolved up/down counts — 0/0 for an unvoted link, real counts after votes.
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


def _context():
    return DotMap(
        {
            "loaders": {"incident": copy.deepcopy(IncidentContextLoaders)},
            "request": None,
            "response": None,
            "user": None,
        }
    )


async def _node(link_id):
    schema = _build_schema()
    result = await schema.execute(
        """
        query {
          publicSocialMediaLinks {
            edges {
              node {
                id
                voteBreakdown {
                  upvotes
                  downvotes
                }
              }
            }
          }
        }
        """,
        context_value=_context(),
    )
    assert result.errors is None, result.errors
    edges = result.data["publicSocialMediaLinks"]["edges"]
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
async def test_vote_breakdown_zero_when_no_votes():
    user = await _make_user("breakdown-novote")
    link = await _make_link(user, "https://example.com/breakdown-novote?v=1")

    node = await _node(link.id)

    assert node["voteBreakdown"] == {"upvotes": 0, "downvotes": 0}


@pytest.mark.django_db
async def test_vote_breakdown_counts_up_and_down():
    submitter = await _make_user("breakdown-owner")
    up1 = await _make_user("breakdown-up1")
    up2 = await _make_user("breakdown-up2")
    down = await _make_user("breakdown-down")
    link = await _make_link(submitter, "https://example.com/breakdown-count?v=1")

    await _cast_vote(up1, link, 1)
    await _cast_vote(up2, link, 1)
    await _cast_vote(down, link, -1)

    node = await _node(link.id)

    assert node["voteBreakdown"] == {"upvotes": 2, "downvotes": 1}
