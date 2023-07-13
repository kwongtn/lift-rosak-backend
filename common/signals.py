from django.db.models.signals import post_save
from django.dispatch import receiver

from common.models import TemporaryMedia
from common.tasks import convert_temporary_media_to_media_task


@receiver(post_save, sender=TemporaryMedia)
def convert_temporary_media_to_media(sender, instance, created, **kwargs):
    if created:
        convert_temporary_media_to_media_task.apply_async(
            kwargs={
                "temporary_media_id": instance.id,
            }
        )
