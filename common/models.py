import uuid

from django.conf import settings
from django.db import models
from django.utils.safestring import mark_safe
from model_utils.models import TimeStampedModel, UUIDModel

from common.enums import TemporaryMediaType
from common.imgur_storage import ImgurStorage

STORAGE = ImgurStorage()


class Media(TimeStampedModel, UUIDModel):
    file = models.ImageField(
        upload_to=settings.IMGUR_ALBUM,
        storage=STORAGE,
    )
    uploader = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )

    def __str__(self) -> str:
        return self.file.name

    def image_widget_html(self, style: str = "max-width: 45vw;") -> str:
        return f'<img src="{self.file.url}" style="{style}" />'

    def image_widget(self, *args, **kwargs):
        return mark_safe(self.image_widget_html(*args, **kwargs))


def get_temporary_media_file_name(instance, filename: str) -> str:
    extension = filename.split(".")[-1]
    return f"temporary_media/{uuid.uuid4()}.{extension}"


class TemporaryMedia(TimeStampedModel, UUIDModel):
    file = models.FileField(
        upload_to=get_temporary_media_file_name,
    )
    uploader = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )
    upload_type = models.CharField(
        max_length=255,
        choices=TemporaryMediaType.choices,
    )
    metadata = models.JSONField(default=dict, blank=True)
    fail_count = models.IntegerField(default=0)
    can_retry = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.file.name

    def image_widget_html(self, style: str = "max-width: 45vw;") -> str:
        return f'<img src="{self.file.url}" style="{style}" />'

    def image_widget(self, *args, **kwargs):
        return mark_safe(self.image_widget_html(*args, **kwargs))


class User(TimeStampedModel):
    firebase_id = models.TextField(unique=True)
    nickname = models.CharField(max_length=255, default="", blank=True)

    badges = models.ManyToManyField(to="mlptf.Badge", through="mlptf.UserBadge")

    def __str__(self) -> str:
        return self.firebase_id[:8]
