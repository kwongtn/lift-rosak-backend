"""GraphQL mutation-layer tests: the thin resolver wrappers around the services.

These execute the @strawberry.type mutation methods directly with a stub Info,
covering input translation (Maybe unwrapping), error translation
(IncidentServiceError -> GraphQLError), and the happy paths the service tests
do not reach through this layer.
"""

import datetime as dt

import pytest
import strawberry
from graphql.error import GraphQLError

from common.models import User
from incident import services
from incident.enums import CalendarIncidentStatus
from incident.models import SocialMediaLink
from incident.schema.inputs import (
    CalendarIncidentChronologyInput,
    CalendarIncidentInput,
    ExtractDataInput,
    SocialMediaLinkInput,
)
from incident.schema.mutations.chronologies import ChronologyMutations
from incident.schema.mutations.incidents import IncidentCrudMutations
from incident.schema.mutations.interactions import (
    ExtractionMutations,
    SocialMediaLinkMutations,
    VoteMutations,
)


class _Context:
    def __init__(self, user, headers=None):
        self.user = user
        self.request = type("Request", (), {"headers": headers or {}})()


class _Info:
    def __init__(self, user, headers=None):
        self.context = _Context(user, headers)


async def _make_user(n: int) -> User:
    from asgiref.sync import sync_to_async

    return await sync_to_async(User.objects.create)(
        firebase_id=f"test-user-resolver-{n}"
    )


def _incident_input(**overrides) -> CalendarIncidentInput:
    defaults = dict(
        title="Resolver Incident",
        brief="resolver brief",
        start_datetime=dt.datetime(2026, 8, 1, 8, 0),
        severity="MINOR",
        chronologies=strawberry.Some(
            [
                CalendarIncidentChronologyInput(
                    indicator="RED",
                    datetime=strawberry.Some(dt.datetime(2026, 8, 1, 9, 0)),
                    source_url=strawberry.Some("https://example.com/a"),
                    content=strawberry.Some("line down"),
                )
            ]
        ),
    )
    defaults.update(overrides)
    return CalendarIncidentInput(**defaults)


@pytest.fixture
def no_admin_claim(monkeypatch):
    async def _false(user) -> bool:
        return False

    monkeypatch.setattr("incident.schema.mutations.incidents.has_admin_claim", _false)
    monkeypatch.setattr(
        "incident.schema.mutations.chronologies.has_admin_claim", _false
    )
    return _false


@pytest.mark.django_db
async def test_create_and_submit_through_resolver_layer(no_admin_claim):
    user = await _make_user(1)
    info = _Info(user)
    crud = IncidentCrudMutations()

    created = await crud.create_calendar_incident(info, input=_incident_input())

    assert created.ok is True
    assert created.id is not None

    submitted = await crud.submit_calendar_incident(
        info, calendar_incident_id=strawberry_id(created.id)
    )
    assert submitted.ok is True


@pytest.mark.django_db
async def test_create_resolver_translates_service_error(no_admin_claim):
    user = await _make_user(2)
    info = _Info(user)

    with pytest.raises(GraphQLError, match="does not exist"):
        await IncidentCrudMutations().submit_calendar_incident(
            info, calendar_incident_id=strawberry_id(999_999)
        )


def strawberry_id(value: int):
    return strawberry.ID(str(value))


@pytest.mark.django_db
async def test_update_delete_reject_flow_through_resolvers(no_admin_claim):
    author = await _make_user(3)
    info = _Info(author)
    crud = IncidentCrudMutations()

    draft = await services.create_incident(
        author, is_admin=False, data=_service_write()
    )

    updated = await crud.update_calendar_incident(
        info,
        calendar_incident_id=strawberry_id(draft.id),
        input=_incident_input(title="Updated by resolver"),
    )
    assert updated.ok is True

    deleted = await crud.delete_calendar_incident(
        info, calendar_incident_id=strawberry_id(draft.id)
    )
    assert deleted.ok is True

    second = await services.create_incident(
        author, is_admin=False, data=_service_write()
    )
    rejected = await crud.reject_calendar_incident(
        info, calendar_incident_id=strawberry_id(second.id), reason="dup"
    )
    assert rejected.ok is True


@pytest.mark.django_db
async def test_approve_resolver_promotes_pending(no_admin_claim):
    author = await _make_user(4)
    info = _Info(author)
    pending = await services.create_incident(
        author, is_admin=False, data=_service_write()
    )
    await services.submit_incident(author, is_admin=False, incident_id=pending.id)

    result = await IncidentCrudMutations().approve_calendar_incident(
        info, calendar_incident_id=strawberry_id(pending.id)
    )

    assert result.ok is True
    from asgiref.sync import sync_to_async

    await sync_to_async(pending.refresh_from_db)()
    assert pending.status == CalendarIncidentStatus.LIVE


def _service_write():
    from django.utils import timezone

    return services.IncidentWrite(
        title="Resolver flow",
        brief="flow",
        start_datetime=timezone.now(),
        severity="MINOR",
    )


@pytest.mark.django_db
async def test_chronology_resolvers_crud_and_reorder(no_admin_claim):
    author = await _make_user(5)
    info = _Info(author)
    incident = await services.create_incident(
        author, is_admin=False, data=_service_write()
    )
    mutations = ChronologyMutations()

    created = await mutations.create_chronology(
        info,
        calendar_incident_id=strawberry_id(incident.id),
        input=CalendarIncidentChronologyInput(indicator="BLUE"),
    )
    assert created.ok is True

    chronology = await incident.chronologies.afirst()

    reordered = await mutations.reorder_chronology(
        info, chronology_id=strawberry_id(chronology.id), target_order=0
    )
    assert reordered.ok is True

    updated = await mutations.update_chronology(
        info,
        chronology_id=strawberry_id(chronology.id),
        input=CalendarIncidentChronologyInput(
            indicator="GREEN", content=strawberry.Some("revised")
        ),
    )
    assert updated.ok is True

    deleted = await mutations.delete_chronology(
        info, chronology_id=strawberry_id(chronology.id)
    )
    assert deleted.ok is True


@pytest.mark.django_db
async def test_vote_resolvers_set_switch_remove():
    user = await _make_user(6)
    info = _Info(user)
    incident = await services.create_incident(
        user, is_admin=True, data=_service_write()
    )
    votes = VoteMutations()

    assert (
        await votes.upvote(info, calendar_incident_id=strawberry_id(incident.id))
    ).ok
    assert (
        await votes.downvote(info, calendar_incident_id=strawberry_id(incident.id))
    ).ok
    assert (
        await votes.remove_vote(info, calendar_incident_id=strawberry_id(incident.id))
    ).ok


@pytest.mark.django_db
async def test_social_link_resolvers_submit_and_complete():
    user = await _make_user(7)
    info = _Info(user)
    links = SocialMediaLinkMutations()

    submitted = await links.submit_social_media_link(
        info,
        input=SocialMediaLinkInput(
            url="https://x.com/resolver/status/1",
            title=strawberry.Some("alert"),
            incident_id=strawberry.Some(None),
        ),
    )
    assert submitted.ok is True

    link = await SocialMediaLink.objects.afirst()
    completed = await links.mark_social_media_link_completed(
        info, social_media_link_id=strawberry_id(link.id)
    )
    assert completed.ok is True


@pytest.mark.django_db
async def test_extract_resolver_returns_scalar(monkeypatch):
    async def fake_extract(url: str, id_token: str | None):
        return {"requestId": "rid-1", "data": {"title": "extracted"}}

    monkeypatch.setattr("incident.extraction.extract_data_from_url", fake_extract)
    info = _Info(None, headers={"Authorization": "Bearer token-123"})

    result = await ExtractionMutations().extract_data_from_url(
        info, input=ExtractDataInput(url="https://example.com")
    )

    assert result.request_id == "rid-1"
    assert result.data == {"title": "extracted"}


@pytest.mark.django_db
async def test_extract_resolver_translates_extraction_error(monkeypatch):
    from incident.extraction import ExtractionError

    async def failing_extract(url: str, id_token: str | None):
        raise ExtractionError("Extraction service unreachable")

    monkeypatch.setattr("incident.extraction.extract_data_from_url", failing_extract)
    info = _Info(None, headers={})

    with pytest.raises(GraphQLError, match="unreachable"):
        await ExtractionMutations().extract_data_from_url(
            info, input=ExtractDataInput(url="https://example.com")
        )
