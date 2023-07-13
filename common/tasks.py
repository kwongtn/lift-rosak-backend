import logging
import time

from django.core.files.base import ContentFile

from common.enums import TemporaryMediaType
from common.models import Media, TemporaryMedia
from rosak.celery import app as celery_app
from spotting.models import Event, EventMedia

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def convert_temporary_media_to_media_task(self, *, temporary_media_id: str | int):
    temp_media: TemporaryMedia = TemporaryMedia.objects.filter(
        id=temporary_media_id
    ).first()
    if not temp_media:
        logger.info("Temporary media not found, restarting task in 2 seconds")
        time.sleep(2)
        convert_temporary_media_to_media_task.apply_async(
            kwargs={
                "temporary_media_id": temporary_media_id,
            }
        )
        return

    if temp_media.upload_type not in [i[0] for i in TemporaryMediaType.choices]:
        raise RuntimeError(f"Invalid upload type: {temp_media.upload_type}")

    media = Media.objects.create(
        created=temp_media.created,
        file=ContentFile(temp_media.file.url, name=temp_media.file.name),
        uploader_id=temp_media.uploader_id,
    )

    if temp_media.upload_type == TemporaryMediaType.SPOTTING_EVENT:
        event: Event = Event.objects.get(id=temp_media.metadata["spotting_event_id"])
        if temp_media.uploader_id != event.reporter_id:
            raise RuntimeError(
                f"User {temp_media.uploader_id} is not the event reporter for event {event.id}"
            )

        EventMedia.objects.create(
            media_id=media.id,
            event_id=event.id,
        )

        temp_media.delete()
