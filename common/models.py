import uuid

from django.conf import settings
from django.db import models
from django.utils.safestring import mark_safe
from model_utils.models import TimeStampedModel, UUIDModel

from common.enums import ClearanceType, TemporaryMediaStatus, TemporaryMediaType
from common.imgur_field import ImgurField
from common.imgur_storage import ImgurStorage

STORAGE = ImgurStorage()


class Media(TimeStampedModel, UUIDModel):
    file = ImgurField(
        upload_to=settings.IMGUR_ALBUM,
        storage=STORAGE,
        width_field="width",
        height_field="height",
    )
    width = models.IntegerField(
        null=True,
        blank=True,
        default=None,
    )
    height = models.IntegerField(
        null=True,
        blank=True,
        default=None,
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
    status = models.CharField(
        max_length=255,
        choices=TemporaryMediaStatus.choices,
        default=TemporaryMediaStatus.PENDING,
    )

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
    clearances = models.ManyToManyField(
        to="common.Clearance", through="common.UserClearance"
    )

    def __str__(self) -> str:
        return self.firebase_id[:8]


class UserClearance(TimeStampedModel):
    user = models.ForeignKey(to="common.User", on_delete=models.CASCADE)
    clearance = models.ForeignKey(to="common.Clearance", on_delete=models.CASCADE)


class Clearance(TimeStampedModel):
    name = models.CharField(max_length=128, unique=True, choices=ClearanceType.choices)
    description = models.TextField(blank=True, null=True, default=None)
    users = models.ManyToManyField(to="common.User", through="common.UserClearance")
