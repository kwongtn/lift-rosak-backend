"""Real-schema tests for the feed submit / line-status-report / link-vote mutations.

Executes the GraphQL schema (Query + Mutation) so the ``@strawberry.mutation``
wrappers, the ``IsLoggedIn`` permission class and the service-error translation
are all covered end to end.  ``transaction=True`` because the async resolvers
write through ``sync_to_async`` on another connection and must not leak rows
between tests (mirrors tests/incident/test_feed_link_submit.py).
"""

import copy

import pytest
import strawberry
from asgiref.sync import sync_to_async
from dotmap import DotMap

from common.models import User
from incident.models import LineStatusReport, SocialMediaLink
from incident.schema.loaders import IncidentContextLoaders
from operation.models import Line


def _build_schema():
    import django

    django.setup()
    from rosak.schema import Mutation, Query

    return strawberry.Schema(query=Query, mutation=Mutation)


def _context(user=None):
    return DotMap(
        {
            "loaders": {"incident": copy.deepcopy(IncidentContextLoaders)},
            "request": None,
            "response": None,
            "user": user,
        }
    )


async def _execute(query: str, variables: dict | None = None, user=None):
    schema = _build_schema()
    return await schema.execute(
        query, variable_values=variables, context_value=_context(user)
    )


async def _make_user(firebase_id: str) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=firebase_id)


async def _make_line(code: str) -> Line:
    return await sync_to_async(Line.objects.create)(
        code=code,
        display_name=f"Feed Mutation Line {code}",
        display_color="#FF0000",
    )


SUBMIT_FEED_LINK = """
mutation SubmitFeedLink($input: FeedLinkInput!) {
  submitFeedLink(input: $input) {
    ok
    isDuplicate
    duplicateOfId
    userVote
    link { id url normalizedUrl status }
  }
}
"""

SUBMIT_LINE_STATUS_REPORT = """
mutation SubmitLineStatusReport($input: LineStatusReportInput!) {
  submitLineStatusReport(input: $input) {
    ok
    id
  }
}
"""

UPVOTE_LINK = """
mutation UpvoteLink($id: ID!) {
  upvoteSocialMediaLink(socialMediaLinkId: $id) { ok }
}
"""

REMOVE_LINK_VOTE = """
mutation RemoveLinkVote($id: ID!) {
  removeSocialMediaLinkVote(socialMediaLinkId: $id) { ok }
}
"""

LINKS_QUERY = """
query {
  publicSocialMediaLinks {
    edges { node { id voteScore userVote } }
  }
}
"""


async def _link_node(user, link_id) -> dict:
    result = await _execute(LINKS_QUERY, user=user)
    assert result.errors is None, result.errors
    edges = result.data["publicSocialMediaLinks"]["edges"]
    return next(e["node"] for e in edges if e["node"]["id"] == str(link_id))


@pytest.mark.django_db(transaction=True)
async def test_submit_feed_link_creates_live_link():
    user = await _make_user("feed-mut-new")

    result = await _execute(
        SUBMIT_FEED_LINK,
        {
            "input": {
                "url": "https://example.com/mut-new?utm_source=twitter",
                "title": "A post",
            }
        },
        user=user,
    )

    assert result.errors is None, result.errors
    payload = result.data["submitFeedLink"]
    assert payload["ok"] is True
    assert payload["isDuplicate"] is False
    assert payload["duplicateOfId"] is None
    assert payload["userVote"] == 0
    assert payload["link"]["url"] == "https://example.com/mut-new?utm_source=twitter"
    assert payload["link"]["normalizedUrl"] == "https://example.com/mut-new"
    assert payload["link"]["status"] == "LIVE"


@pytest.mark.django_db(transaction=True)
async def test_duplicate_submit_returns_indicator_and_upvotes_without_new_row():
    user = await _make_user("feed-mut-dup")

    first = await _execute(
        SUBMIT_FEED_LINK,
        {"input": {"url": "https://example.com/mut-dup", "title": "First"}},
        user=user,
    )
    assert first.errors is None, first.errors
    first_link_id = first.data["submitFeedLink"]["link"]["id"]

    second = await _execute(
        SUBMIT_FEED_LINK,
        {
            "input": {
                "url": "https://example.com/mut-dup/?fbclid=abc&utm_source=x",
                "title": "Second",
            }
        },
        user=user,
    )

    assert second.errors is None, second.errors
    payload = second.data["submitFeedLink"]
    assert payload["isDuplicate"] is True
    assert payload["duplicateOfId"] == int(first_link_id)
    assert payload["userVote"] == 1
    assert payload["link"]["id"] == first_link_id

    assert (
        await SocialMediaLink.objects.filter(
            normalized_url="https://example.com/mut-dup"
        ).acount()
        == 1
    )


@pytest.mark.django_db(transaction=True)
async def test_status_without_line_ids_raises_graphql_error():
    user = await _make_user("feed-mut-noline")

    result = await _execute(
        SUBMIT_FEED_LINK,
        {
            "input": {
                "url": "https://example.com/mut-noline",
                "title": "Status only",
                "status": "DELAYED",
            }
        },
        user=user,
    )

    assert result.errors is not None
    assert result.data is None
    assert "line" in str(result.errors[0]).lower()


@pytest.mark.django_db(transaction=True)
async def test_submit_line_status_report_creates_link_less_report():
    user = await _make_user("feed-mut-report")
    line = await _make_line("FMUT1")

    result = await _execute(
        SUBMIT_LINE_STATUS_REPORT,
        {
            "input": {
                "lineId": str(line.id),
                "status": "DELAYED",
                "delayMinutes": 5,
                "notes": "signal fault",
            }
        },
        user=user,
    )

    assert result.errors is None, result.errors
    payload = result.data["submitLineStatusReport"]
    assert payload["ok"] is True
    assert payload["id"] is not None

    report = await LineStatusReport.objects.aget(id=int(payload["id"]))
    assert report.link_id is None
    assert report.line_id == line.id
    assert report.status == "DELAYED"
    assert report.delay_minutes == 5
    assert report.notes == "signal fault"


@pytest.mark.django_db(transaction=True)
async def test_upvote_then_remove_changes_score_and_user_vote():
    user = await _make_user("feed-mut-vote")

    submitted = await _execute(
        SUBMIT_FEED_LINK,
        {"input": {"url": "https://example.com/mut-vote", "title": "Votable"}},
        user=user,
    )
    assert submitted.errors is None, submitted.errors
    link_id = submitted.data["submitFeedLink"]["link"]["id"]

    upvoted = await _execute(UPVOTE_LINK, {"id": link_id}, user=user)
    assert upvoted.errors is None, upvoted.errors
    assert upvoted.data["upvoteSocialMediaLink"]["ok"] is True

    node = await _link_node(user, link_id)
    assert node["voteScore"] == 1
    assert node["userVote"] == 1

    removed = await _execute(REMOVE_LINK_VOTE, {"id": link_id}, user=user)
    assert removed.errors is None, removed.errors
    assert removed.data["removeSocialMediaLinkVote"]["ok"] is True

    node = await _link_node(user, link_id)
    assert node["voteScore"] == 0
    assert node["userVote"] == 0


@pytest.mark.django_db(transaction=True)
async def test_submit_feed_link_requires_login():
    result = await _execute(
        SUBMIT_FEED_LINK,
        {"input": {"url": "https://example.com/mut-anon", "title": "Anon"}},
        user=None,
    )

    assert result.errors is not None
    assert result.data is None
    assert "not logged in" in str(result.errors[0]).lower()
