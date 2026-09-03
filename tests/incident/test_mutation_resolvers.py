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
    monkeypatch.setattr(
        "incident.schema.mutations.interactions.has_admin_claim", _false
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
async def test_social_link_resolvers_submit_and_complete(no_admin_claim):
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
async def test_social_link_resolver_title_null_and_unset_coerce_to_empty(
    no_admin_claim,
):
    user = await _make_user(8)
    info = _Info(user)
    links = SocialMediaLinkMutations()

    ok_null = await links.submit_social_media_link(
        info,
        input=SocialMediaLinkInput(
            url="https://www.facebook.com/groups/developerkaki/permalink/2951657628513464",
            title=strawberry.Some(None),
            category_ids=strawberry.Some([]),
            line_ids=strawberry.Some([]),
            vehicle_ids=strawberry.Some([]),
            station_ids=strawberry.Some([]),
        ),
    )
    assert ok_null.ok is True
    link_null = await SocialMediaLink.objects.filter(
        url="https://www.facebook.com/groups/developerkaki/permalink/2951657628513464"
    ).afirst()
    assert link_null is not None
    assert link_null.title == ""

    ok_unset = await links.submit_social_media_link(
        info,
        input=SocialMediaLinkInput(
            url="https://www.facebook.com/groups/developerkaki/permalink/2951657628513465",
            category_ids=strawberry.Some([]),
        ),
    )
    assert ok_unset.ok is True
    link_unset = await SocialMediaLink.objects.filter(
        url="https://www.facebook.com/groups/developerkaki/permalink/2951657628513465"
    ).afirst()
    assert link_unset is not None
    assert link_unset.title == ""


@pytest.mark.django_db
async def test_create_calendar_incident_details_null_and_unset_coerce_to_empty(
    no_admin_claim,
):
    user = await _make_user(9)
    info = _Info(user)
    crud = IncidentCrudMutations()

    ok_null = await crud.create_calendar_incident(
        info,
        input=CalendarIncidentInput(
            title="Test",
            brief="Test",
            start_datetime=dt.datetime(2026, 8, 31, 16, 33, tzinfo=dt.timezone.utc),
            severity="MAJOR",
            details=strawberry.Some(None),
            end_datetime=strawberry.Some(None),
            line_ids=strawberry.Some([]),
            vehicle_ids=strawberry.Some([]),
            station_ids=strawberry.Some([]),
            chronologies=strawberry.Some([]),
        ),
    )
    assert ok_null.ok is True
    incident_null = await crud.create_calendar_incident(
        info,
        input=CalendarIncidentInput(
            title="Test2",
            brief="Test2",
            start_datetime=dt.datetime(2026, 8, 31, 16, 33, tzinfo=dt.timezone.utc),
            severity="MAJOR",
        ),
    )
    assert incident_null.ok is True
    # verify via service that details defaults to ""
    from incident.models import CalendarIncident

    incidents = [
        i
        async for i in CalendarIncident.objects.filter(
            title__in=["Test", "Test2"]
        ).order_by("id")
    ]
    assert len(incidents) == 2
    for inc in incidents:
        assert inc.details == ""


@pytest.mark.django_db
async def test_update_mutation_returns_id_for_revision_path(no_admin_claim):
    """Non-admin edit of LIVE creates a draft revision → id returned for chaining."""
    from incident.models import CalendarIncident

    author = await _make_user(100)
    info = _Info(author)
    crud = IncidentCrudMutations()

    live = await services.create_incident(author, is_admin=True, data=_service_write())

    updated = await crud.update_calendar_incident(
        info,
        calendar_incident_id=strawberry_id(live.id),
        input=_incident_input(title="Edited"),
    )
    assert updated.ok is True
    assert updated.id is not None

    draft = await CalendarIncident.objects.filter(
        parent_incident=live, status=CalendarIncidentStatus.DRAFT
    ).afirst()
    assert draft is not None
    assert updated.id == draft.id


@pytest.mark.django_db
async def test_update_mutation_returns_id_for_same_actor_resume(no_admin_claim):
    """Same-actor resume returns the existing draft's id."""
    author = await _make_user(101)
    info = _Info(author)
    crud = IncidentCrudMutations()

    live = await services.create_incident(author, is_admin=True, data=_service_write())

    first = await crud.update_calendar_incident(
        info,
        calendar_incident_id=strawberry_id(live.id),
        input=_incident_input(title="First"),
    )
    assert first.id is not None
    draft_id = first.id

    second = await crud.update_calendar_incident(
        info,
        calendar_incident_id=strawberry_id(live.id),
        input=_incident_input(title="Resumed"),
    )
    assert second.id == draft_id


@pytest.mark.django_db
async def test_update_mutation_returns_none_for_in_place_paths(no_admin_claim):
    """DRAFT in-place → id is None (frontend branches on it)."""
    author = await _make_user(102)
    info = _Info(author)
    crud = IncidentCrudMutations()

    # DRAFT in-place
    draft = await services.create_incident(
        author, is_admin=False, data=_service_write()
    )
    updated = await crud.update_calendar_incident(
        info,
        calendar_incident_id=strawberry_id(draft.id),
        input=_incident_input(title="Draft revised"),
    )
    assert updated.ok is True
    assert updated.id is None


@pytest.mark.django_db
async def test_update_mutation_returns_none_for_admin_in_place(monkeypatch):
    """Admin in-place on LIVE → id is None."""

    async def _true(user) -> bool:
        return True

    monkeypatch.setattr("incident.schema.mutations.incidents.has_admin_claim", _true)

    admin = await _make_user(103)
    info = _Info(admin)
    crud = IncidentCrudMutations()

    live = await services.create_incident(admin, is_admin=True, data=_service_write())
    admin_updated = await crud.update_calendar_incident(
        info,
        calendar_incident_id=strawberry_id(live.id),
        input=_incident_input(title="Admin edit"),
    )
    assert admin_updated.ok is True
    assert admin_updated.id is None


@pytest.mark.django_db
async def test_update_mutation_returns_id_for_author_pending_in_place(no_admin_claim):
    """Author editing own PENDING_APPROVAL in-place → id is None."""
    author = await _make_user(104)
    info = _Info(author)
    crud = IncidentCrudMutations()

    incident = await services.create_incident(
        author, is_admin=False, data=_service_write()
    )
    await services.submit_incident(author, is_admin=False, incident_id=incident.id)

    updated = await crud.update_calendar_incident(
        info,
        calendar_incident_id=strawberry_id(incident.id),
        input=_incident_input(title="Pending revised"),
    )
    assert updated.ok is True
    assert updated.id is None


@pytest.mark.django_db
async def test_update_calendar_incident_details_null_coerced(no_admin_claim):
    author = await _make_user(10)
    info = _Info(author)
    crud = IncidentCrudMutations()
    draft = await services.create_incident(
        author, is_admin=False, data=_service_write()
    )
    # update with explicit null details should coerce to ""
    updated = await crud.update_calendar_incident(
        info,
        calendar_incident_id=strawberry_id(draft.id),
        input=CalendarIncidentInput(
            title="Updated",
            brief="Updated brief",
            start_datetime=dt.datetime(2026, 8, 1, 8, 0, tzinfo=dt.timezone.utc),
            severity="MINOR",
            details=strawberry.Some(None),
        ),
    )
    assert updated.ok is True
    from asgiref.sync import sync_to_async

    await sync_to_async(draft.refresh_from_db)()
    assert draft.details == ""


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
