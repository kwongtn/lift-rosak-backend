"""Edge-case unit tests filling the Wave 5 coverage gaps (services, models, loaders, extraction)."""

import httpx
import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings
from django.utils import timezone

from common.models import Media, User
from incident import extraction, services
from incident.enums import CalendarIncidentStatus
from incident.models import (
    CalendarIncident,
    CalendarIncidentCategory,
    CalendarIncidentMedia,
)
from incident.schema.loaders import batch_load_medias_from_calendar_incident


def _write(**overrides) -> services.IncidentWrite:
    defaults = dict(
        title="Gap Incident",
        brief="gap brief",
        start_datetime=timezone.now(),
        severity="MINOR",
    )
    defaults.update(overrides)
    return services.IncidentWrite(**defaults)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"test-user-gaps-{n}")


@pytest.mark.django_db
async def test_update_incident_denied_for_non_author_non_admin():
    author = await _make_user(1)
    outsider = await _make_user(2)
    draft = await services.create_incident(author, is_admin=False, data=_write())

    with pytest.raises(services.IncidentNotEditableError, match="author or an admin"):
        await services.update_incident(
            outsider,
            is_admin=False,
            incident_id=draft.id,
            expected_version=None,
            data=_write(title="Hijacked"),
        )

    await sync_to_async(draft.refresh_from_db)()
    assert draft.title == "Gap Incident"


@pytest.mark.django_db
async def test_submit_incident_denied_for_non_author_draft():
    author = await _make_user(3)
    outsider = await _make_user(4)
    draft = await services.create_incident(author, is_admin=False, data=_write())

    with pytest.raises(services.IncidentNotEditableError, match="author or an admin"):
        await services.submit_incident(outsider, is_admin=False, incident_id=draft.id)

    await sync_to_async(draft.refresh_from_db)()
    assert draft.status == CalendarIncidentStatus.DRAFT


@pytest.mark.django_db
async def test_reject_live_incident_raises():
    author = await _make_user(5)
    live = await services.create_incident(author, is_admin=True, data=_write())

    with pytest.raises(
        services.IncidentNotEditableError, match="DRAFT or PENDING_APPROVAL"
    ):
        await services.reject_incident(
            author, incident_id=live.id, reason="not allowed"
        )


@pytest.mark.django_db
async def test_admin_can_submit_any_draft():
    author = await _make_user(6)
    admin = await _make_user(7)
    draft = await services.create_incident(author, is_admin=False, data=_write())

    submitted = await services.submit_incident(
        admin, is_admin=True, incident_id=draft.id
    )

    assert submitted.status == CalendarIncidentStatus.PENDING_APPROVAL


@override_settings(
    EXTRACT_INCIDENT_DATA_URL=(
        "https://asia-southeast1-test.cloudfunctions.net/extractIncidentData"
    )
)
@pytest.mark.django_db
async def test_non_json_response_raises_extraction_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    with pytest.raises(extraction.ExtractionError, match="non-JSON"):
        await extraction.extract_data_from_url(
            url="https://example.com/news",
            id_token=None,
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.django_db
async def test_medias_loader_groups_by_incident_and_defaults_empty():
    author = await _make_user(8)
    with_media = await services.create_incident(author, is_admin=True, data=_write())
    without_media = await services.create_incident(
        author, is_admin=True, data=_write(title="No media")
    )
    media = await sync_to_async(Media.objects.create)(uploader=author)
    await sync_to_async(CalendarIncidentMedia.objects.create)(
        calendar_incident=with_media, media=media
    )

    result = await batch_load_medias_from_calendar_incident(
        [with_media.id, without_media.id]
    )

    assert {m.id for m in result[0]} == {media.id}
    assert result[1] == set()


@pytest.mark.django_db
def test_model_str_and_admin_widget_render():
    category = CalendarIncidentCategory.objects.create(name="Gap Disruption")
    assert str(category) == "Gap Disruption"

    incident = CalendarIncident.objects.create(
        title="KL Sentral platform flooded after storm",
        brief="flood",
        start_datetime=timezone.now(),
        severity="MAJOR",
        status=CalendarIncidentStatus.LIVE,
    )
    assert str(incident).startswith(f"{incident.id} - KL Sentral platform flooded")

    widget = incident.images_widget()
    assert 'href="/admin/common/media/' not in widget
    assert "display: flex" in widget
