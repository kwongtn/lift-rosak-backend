from django.db.models.signals import post_save
from django.dispatch import receiver

from common.enums import ClearanceType, TemporaryMediaStatus
from common.models import TemporaryMedia
from common.tasks import (  # check_temporary_media_nsfw,
    convert_temporary_media_to_media_task,
)


@receiver(post_save, sender=TemporaryMedia)
def convert_temporary_media_to_media(
    sender, instance: TemporaryMedia, created, **kwargs
):
    if not created:
        return

    if instance.uploader.clearances.filter(
        name=ClearanceType.TRUSTED_MEDIA_UPLOADER
    ).exists():
        instance.status = TemporaryMediaStatus.TRUSTED_CLEARED
        instance.save()
        convert_temporary_media_to_media_task.apply_async(
            kwargs={
                "temporary_media_id": instance.id,
            }
        )

    else:
        if instance.status == TemporaryMediaStatus.PENDING:
            convert_temporary_media_to_media_task.apply_async(
                kwargs={
                    "temporary_media_id": instance.id,
                }
            )
            # check_temporary_media_nsfw.apply_async(
            #     kwargs={
            #         "temporary_media_id": instance.id,
            #     }
            # )
