"""Tests for incident edit/delete semantics (plan Tasks 2-5 + Option A)."""

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.models import Media, User
from incident import services
from incident.enums import CalendarIncidentStatus
from incident.models import (
    CalendarIncident,
    CalendarIncidentMedia,
)
from incident.services.access import is_author, may_edit


def _write(**overrides) -> services.IncidentWrite:
    defaults = dict(
        title="Test Incident",
        brief="Test brief",
        start_datetime=timezone.now(),
        severity="MINOR",
    )
    defaults.update(overrides)
    return services.IncidentWrite(**defaults)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(
        firebase_id=f"test-edit-semantics-{n}"
    )


async def _make_media(user: User, n: int) -> Media:
    return await sync_to_async(Media.objects.create)(
        uploader=user,
        file_id=f"file-{n}",
        file_name=f"image-{n}.png",
    )


# --- Task 2: one-open-draft rule + spec error ---


@pytest.mark.django_db
async def test_one_open_draft_blocks_second_editor():
    author = await _make_user(1)
    other = await _make_user(2)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    first = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="First edit"),
    )
    assert first.created_revision
    assert first.incident.status == CalendarIncidentStatus.DRAFT

    with pytest.raises(
        services.IncidentNotEditableError,
        match=(
            "An unapproved edit draft already exists for this incident. "
            "Please allow the draft to approve before proceeding."
        ),
    ):
        await services.update_incident(
            other,
            is_admin=False,
            incident_id=live.id,
            expected_version=live.version,
            data=_write(title="Second edit"),
        )


@pytest.mark.django_db
async def test_new_draft_allowed_after_approval():
    author = await _make_user(3)
    other = await _make_user(4)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    first = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="First edit"),
    )
    await services.approve_incident(author, incident_id=first.incident.id)

    await sync_to_async(live.refresh_from_db)()
    assert live.title == "First edit"

    second = await services.update_incident(
        other,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Second edit"),
    )
    assert second.created_revision
    assert second.incident.title == "Second edit"


@pytest.mark.django_db
async def test_new_draft_allowed_after_rejection():
    author = await _make_user(5)
    other = await _make_user(6)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    first = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="First edit"),
    )
    await services.reject_incident(author, incident_id=first.incident.id, reason="nope")

    second = await services.update_incident(
        other,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="After rejection"),
    )
    assert second.created_revision


# --- Task 3: revision author fix ---


@pytest.mark.django_db
async def test_revision_created_by_is_the_editor():
    author = await _make_user(7)
    editor = await _make_user(8)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    result = await services.update_incident(
        editor,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Edited by non-author"),
    )

    assert result.incident.created_by_id == editor.id
    assert result.incident.created_by_id != author.id


@pytest.mark.django_db
async def test_may_edit_grants_to_revision_editor():
    author = await _make_user(9)
    editor = await _make_user(10)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    result = await services.update_incident(
        editor,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Edited by non-author"),
    )
    revision = result.incident

    assert may_edit(editor, is_admin=False, incident=revision) is True
    assert may_edit(author, is_admin=False, incident=revision) is False
    assert is_author(editor, revision) is True
    assert is_author(author, revision) is False


# --- Task 4: pending deletion permission ---


@pytest.mark.django_db
async def test_author_can_delete_own_pending_incident():
    author = await _make_user(11)
    incident = await services.create_incident(author, is_admin=False, data=_write())
    await sync_to_async(incident.__setattr__)(
        "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(incident.save)()

    await services.delete_incident(author, is_admin=False, incident_id=incident.id)

    assert not await CalendarIncident.objects.filter(pk=incident.id).aexists()
    assert await CalendarIncident.all_objects.filter(pk=incident.id).aexists()


@pytest.mark.django_db
async def test_non_author_cannot_delete_pending():
    author = await _make_user(12)
    other = await _make_user(13)
    incident = await services.create_incident(author, is_admin=False, data=_write())
    await sync_to_async(incident.__setattr__)(
        "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(incident.save)()

    with pytest.raises(services.IncidentNotEditableError):
        await services.delete_incident(other, is_admin=False, incident_id=incident.id)


@pytest.mark.django_db
async def test_admin_can_delete_any_incident():
    author = await _make_user(14)
    admin = await _make_user(15)
    pending = await services.create_incident(author, is_admin=False, data=_write())
    await sync_to_async(pending.__setattr__)(
        "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(pending.save)()

    await services.delete_incident(admin, is_admin=True, incident_id=pending.id)

    assert not await CalendarIncident.objects.filter(pk=pending.id).aexists()


# --- Task 5: medias merge ---


@pytest.mark.django_db
async def test_merge_reparents_draft_medias_to_parent():
    author = await _make_user(16)
    m1 = await _make_media(author, 1)
    m2 = await _make_media(author, 2)
    m3 = await _make_media(author, 3)

    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )
    await sync_to_async(CalendarIncidentMedia.objects.create)(
        calendar_incident=live, media=m1
    )

    revision_result = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Revised"),
    )
    revision = revision_result.incident
    await sync_to_async(CalendarIncidentMedia.objects.create)(
        calendar_incident=revision, media=m2
    )
    await sync_to_async(CalendarIncidentMedia.objects.create)(
        calendar_incident=revision, media=m3
    )

    await services.approve_incident(author, incident_id=revision.id)

    await sync_to_async(live.refresh_from_db)()
    merged_media_ids = {m.id async for m in live.medias.all()}
    assert merged_media_ids == {m1.id, m2.id, m3.id}

    assert not await CalendarIncident.all_objects.filter(pk=revision.id).aexists()


@pytest.mark.django_db
async def test_merge_chronologies_reparented_regression():
    author = await _make_user(17)
    live = await services.create_incident(
        author,
        is_admin=True,
        data=_write(title="Original"),
        chronologies=(services.ChronologyWrite(indicator="GREEN", content="original"),),
    )

    revision_result = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Revised"),
        chronologies=(services.ChronologyWrite(indicator="RED", content="revised"),),
    )

    await services.approve_incident(author, incident_id=revision_result.incident.id)

    await sync_to_async(live.refresh_from_db)()
    chronologies = [c async for c in live.chronologies.all()]
    assert len(chronologies) == 1
    assert chronologies[0].content == "revised"


# --- Option A: admin in-place update ---


@pytest.mark.django_db
async def test_admin_updates_pending_in_place():
    admin = await _make_user(18)
    author = await _make_user(19)
    incident = await services.create_incident(
        author, is_admin=False, data=_write(title="Original")
    )
    await sync_to_async(incident.__setattr__)(
        "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(incident.save)()
    original_version = incident.version

    result = await services.update_incident(
        admin,
        is_admin=True,
        incident_id=incident.id,
        expected_version=original_version,
        data=_write(title="Admin edited"),
    )

    assert not result.created_revision
    assert result.incident.id == incident.id
    assert result.incident.title == "Admin edited"
    assert result.incident.status == CalendarIncidentStatus.PENDING_APPROVAL

    revisions = [
        r async for r in CalendarIncident.objects.filter(parent_incident=incident)
    ]
    assert len(revisions) == 0


@pytest.mark.django_db
async def test_admin_updates_live_in_place():
    admin = await _make_user(20)
    author = await _make_user(21)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )
    original_version = live.version

    result = await services.update_incident(
        admin,
        is_admin=True,
        incident_id=live.id,
        expected_version=original_version,
        data=_write(title="Admin live edit"),
    )

    assert not result.created_revision
    assert result.incident.id == live.id
    assert result.incident.title == "Admin live edit"
    assert result.incident.status == CalendarIncidentStatus.LIVE


@pytest.mark.django_db
async def test_admin_in_place_update_still_version_checked():
    admin = await _make_user(22)
    author = await _make_user(23)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    with pytest.raises(services.ConcurrencyConflictError):
        await services.update_incident(
            admin,
            is_admin=True,
            incident_id=live.id,
            expected_version=999,
            data=_write(title="Stale edit"),
        )


# --- Spec C1: author edits own PENDING_APPROVAL in place ---


@pytest.mark.django_db
async def test_author_edits_own_pending_in_place():
    author = await _make_user(24)
    incident = await services.create_incident(
        author, is_admin=False, data=_write(title="Original")
    )
    await sync_to_async(incident.__setattr__)(
        "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(incident.save)()

    result = await services.update_incident(
        author,
        is_admin=False,
        incident_id=incident.id,
        expected_version=incident.version,
        data=_write(title="Author revised"),
    )

    assert not result.created_revision
    assert result.incident.id == incident.id
    assert result.incident.title == "Author revised"
    assert result.incident.status == CalendarIncidentStatus.PENDING_APPROVAL

    revisions = [
        r async for r in CalendarIncident.objects.filter(parent_incident=incident)
    ]
    assert len(revisions) == 0


# --- Same-actor draft resume ---


@pytest.mark.django_db
async def test_same_actor_resumes_own_draft():
    author = await _make_user(25)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    first = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="First edit"),
    )
    assert first.created_revision
    draft_id = first.incident.id

    # Same actor retries (e.g. submit failed) — should resume the SAME draft.
    second = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Resumed edit"),
    )
    assert second.created_revision
    assert second.incident.id == draft_id
    assert second.incident.title == "Resumed edit"

    drafts = [
        d
        async for d in CalendarIncident.objects.filter(
            parent_incident=live, status=CalendarIncidentStatus.DRAFT
        )
    ]
    assert len(drafts) == 1


@pytest.mark.django_db
async def test_different_actor_draft_blocked_still_raises():
    author = await _make_user(26)
    other = await _make_user(27)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="First edit"),
    )

    with pytest.raises(
        services.IncidentNotEditableError,
        match=(
            "An unapproved edit draft already exists for this incident. "
            "Please allow the draft to approve before proceeding."
        ),
    ):
        await services.update_incident(
            other,
            is_admin=False,
            incident_id=live.id,
            expected_version=live.version,
            data=_write(title="Blocked edit"),
        )


@pytest.mark.django_db
async def test_author_edits_live_creates_revision():
    """Author editing a LIVE row creates a new pending object (not in-place)."""
    author = await _make_user(28)
    live = await services.create_incident(
        author, is_admin=True, data=_write(title="Original")
    )

    result = await services.update_incident(
        author,
        is_admin=False,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Author live edit"),
    )
    assert result.created_revision
    assert result.incident.id != live.id
    assert result.incident.status == CalendarIncidentStatus.DRAFT


# --- F2 fix: replace_chronologies preserves pending-moderation statuses ---


@pytest.mark.django_db
async def test_admin_in_place_update_preserves_pending_deletion():
    """Admin saving a LIVE incident with a PENDING_DELETION chronology
    (content untouched) → chronology recreated AND still PENDING_DELETION.
    """
    author = await _make_user(40)
    admin = await _make_user(41)
    live = await services.create_incident(
        author,
        is_admin=True,
        data=_write(title="Original"),
        chronologies=(
            services.ChronologyWrite(
                indicator="GREEN", content="train stalled at KL Sentral"
            ),
        ),
    )
    # Mark the LIVE chronology for deletion.
    chronology = [c async for c in live.chronologies.all()][0]
    await services.request_chronology_deletion(
        author, is_admin=False, chronology_id=chronology.id
    )

    # Admin in-place update (title only — chronology content unchanged).
    await services.update_incident(
        admin,
        is_admin=True,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Admin revised"),
        chronologies=(
            services.ChronologyWrite(
                indicator="GREEN", content="train stalled at KL Sentral"
            ),
        ),
    )

    await sync_to_async(live.refresh_from_db)()
    chronologies = [c async for c in live.chronologies.all()]
    assert len(chronologies) == 1
    assert chronologies[0].status == CalendarIncidentStatus.PENDING_DELETION


@pytest.mark.django_db
async def test_admin_update_edited_content_loses_pending_deletion_flag():
    """Admin editing BOTH the incident AND the chronology's content → flag NOT
    preserved (documented caveat: content change = no match → inherits LIVE).
    """
    author = await _make_user(42)
    admin = await _make_user(43)
    live = await services.create_incident(
        author,
        is_admin=True,
        data=_write(title="Original"),
        chronologies=(
            services.ChronologyWrite(
                indicator="GREEN", content="train stalled at KL Sentral"
            ),
        ),
    )
    chronology = [c async for c in live.chronologies.all()][0]
    await services.request_chronology_deletion(
        author, is_admin=False, chronology_id=chronology.id
    )

    # Admin updates the chronology's content too → no match → inherits LIVE.
    await services.update_incident(
        admin,
        is_admin=True,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Admin revised"),
        chronologies=(
            services.ChronologyWrite(
                indicator="GREEN", content="train departed KL Sentral"
            ),
        ),
    )

    await sync_to_async(live.refresh_from_db)()
    chronologies = [c async for c in live.chronologies.all()]
    assert len(chronologies) == 1
    assert chronologies[0].status == CalendarIncidentStatus.LIVE


@pytest.mark.django_db
async def test_admin_in_place_update_preserves_pending_approval():
    """PENDING_APPROVAL chronology on a LIVE parent survives an admin in-place
    update (chronology status is independent per AC1).
    """
    author = await _make_user(44)
    admin = await _make_user(45)
    live = await services.create_incident(
        author,
        is_admin=True,
        data=_write(title="Original"),
        chronologies=(
            services.ChronologyWrite(
                indicator="GREEN", content="train stalled at KL Sentral"
            ),
        ),
    )
    # Set the chronology to PENDING_APPROVAL directly (independent status).
    chronology = [c async for c in live.chronologies.all()][0]
    await sync_to_async(chronology.__setattr__)(
        "status", CalendarIncidentStatus.PENDING_APPROVAL
    )
    await sync_to_async(chronology.save)()

    await services.update_incident(
        admin,
        is_admin=True,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Admin revised"),
        chronologies=(
            services.ChronologyWrite(
                indicator="GREEN", content="train stalled at KL Sentral"
            ),
        ),
    )

    await sync_to_async(live.refresh_from_db)()
    chronologies = [c async for c in live.chronologies.all()]
    assert len(chronologies) == 1
    assert chronologies[0].status == CalendarIncidentStatus.PENDING_APPROVAL


@pytest.mark.django_db
async def test_replace_chronologies_regression_live_and_draft():
    """Regression: ordinary LIVE chronologies still become LIVE after replace;
    DRAFT-parent flow unchanged (status inherits DRAFT).
    """
    author = await _make_user(46)
    admin = await _make_user(47)

    # LIVE parent → LIVE chronology survives replace.
    live = await services.create_incident(
        author,
        is_admin=True,
        data=_write(title="Live"),
        chronologies=(
            services.ChronologyWrite(indicator="GREEN", content="live chronology"),
        ),
    )
    await services.update_incident(
        admin,
        is_admin=True,
        incident_id=live.id,
        expected_version=live.version,
        data=_write(title="Live revised"),
        chronologies=(
            services.ChronologyWrite(indicator="GREEN", content="live chronology"),
        ),
    )
    await sync_to_async(live.refresh_from_db)()
    live_chronologies = [c async for c in live.chronologies.all()]
    assert len(live_chronologies) == 1
    assert live_chronologies[0].status == CalendarIncidentStatus.LIVE

    # DRAFT parent → DRAFT chronology inherits DRAFT.
    draft = await services.create_incident(
        author,
        is_admin=False,
        data=_write(title="Draft"),
        chronologies=(
            services.ChronologyWrite(indicator="RED", content="draft chronology"),
        ),
    )
    await services.update_incident(
        author,
        is_admin=False,
        incident_id=draft.id,
        expected_version=draft.version,
        data=_write(title="Draft revised"),
        chronologies=(
            services.ChronologyWrite(indicator="RED", content="draft chronology"),
        ),
    )
    await sync_to_async(draft.refresh_from_db)()
    draft_chronologies = [c async for c in draft.chronologies.all()]
    assert len(draft_chronologies) == 1
    assert draft_chronologies[0].status == CalendarIncidentStatus.DRAFT
