import datetime
import logging
import time

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.timezone import now
from imgurpython import ImgurClient
from PIL import ExifTags, Image, TiffImagePlugin

from common.enums import TemporaryMediaType
from incident.models import CalendarIncidentMedia
from rosak.celery import app as celery_app
from spotting.models import Event, EventMedia

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def convert_temporary_media_to_media_task(self, *, temporary_media_id: str | int):
    from common.models import Media, TemporaryMedia

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
        temp_media.can_retry = False
        temp_media.save()

        raise RuntimeError(f"Invalid upload type: {temp_media.upload_type}")

    try:
        with transaction.atomic(), temp_media.file.open() as stream:
            image_open = Image.open(stream)
            image_open.verify()
            image_get_exif = image_open.getexif()

            exif = {}
            if image_get_exif:
                exif = {
                    # Ensure we're not getting "TypeError: Object of type IFDRational is not JSON serializable".
                    ExifTags.TAGS[k]: v
                    for k, v in image_get_exif.items()
                    if k in ExifTags.TAGS
                    and type(v) not in [bytes, TiffImagePlugin.IFDRational]
                }

            logger.info(exif)

            media = Media.objects.create(
                created=temp_media.created,
                file=ContentFile(temp_media.file.url, name=temp_media.file.name),
                uploader_id=temp_media.uploader_id,
            )

            if temp_media.upload_type == TemporaryMediaType.SPOTTING_EVENT:
                event: Event = Event.objects.get(
                    id=temp_media.metadata["spotting_event_id"]
                )
                if temp_media.uploader_id != event.reporter_id:
                    raise RuntimeError(
                        f"User {temp_media.uploader_id} is not the event reporter for event {event.id}"
                    )

                EventMedia.objects.create(
                    media_id=media.id,
                    event_id=event.id,
                )

            elif (
                temp_media.upload_type == TemporaryMediaType.INCIDENT_CALENDAR_INCIDENT
            ):
                CalendarIncidentMedia.objects.create(
                    media_id=media.id,
                    calendar_incident_id=temp_media.metadata["calendar_incident_id"],
                    timestamp=image_get_exif.get(ExifTags.Base.DateTime, None),
                )

            else:
                raise RuntimeError(f"Invalid upload type: {temp_media.upload_type}")

            temp_media.delete()

    except Exception as e:
        logger.exception(e)
        temp_media.fail_count += 1
        temp_media.save()


@celery_app.task(bind=True)
def cleanup_temporary_media_task(self, *args, **kwargs):
    from common.models import TemporaryMedia

    for temp_media in TemporaryMedia.objects.filter(
        created__lte=now() - datetime.timedelta(minutes=5),
        fail_count__lt=5,
        can_retry=True,
    ).filter():
        convert_temporary_media_to_media_task.apply_async(
            kwargs={
                "temporary_media_id": temp_media.id,
            }
        )


@celery_app.task(bind=True)
def add_width_height_to_media_task(self, *, filename, width, height, **kwargs):
    from common.models import Media

    # We assume that filename is unique
    media: Media = Media.objects.filter(file=filename).first()
    if not media:
        logger.info(f"Media '{filename}' not found, restarting task in 2 seconds")
        time.sleep(2)
        add_width_height_to_media_task.apply_async(
            kwargs={
                "filename": filename,
                "width": width,
                "height": height,
            }
        )
        return

    media.width = width
    media.height = height
    media.save()


@celery_app.task(bind=True)
def cleanup_add_width_height_to_media_task(self, *args, **kwargs):
    from common.models import Media

    # We attempt to fix the entire media library 1 at a time
    media = Media.objects.filter(
        width__isnull=True,
        height__isnull=True,
    ).first()

    imgur_client = ImgurClient(
        client_id=settings.IMGUR_CONSUMER_ID,
        client_secret=settings.IMGUR_CONSUMER_SECRET,
        access_token=settings.IMGUR_ACCESS_TOKEN,
        refresh_token=settings.IMGUR_ACCESS_TOKEN_REFRESH,
    )

    metadata = imgur_client.get_image(media.name)

    media.width = metadata.width
    media.height = metadata.height
    media.save()
