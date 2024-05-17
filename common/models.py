import uuid
from random import randint

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from model_utils.models import TimeStampedModel, UUIDModel

from common.enums import (
    ClearanceType,
    FeatureFlagType,
    TemporaryMediaStatus,
    TemporaryMediaType,
)
from common.imgur_field import ImgurField
from common.imgur_storage import ImgurStorage
from common.mixins import MediaMixin

STORAGE = ImgurStorage()


class Media(TimeStampedModel, UUIDModel, MediaMixin):
    file = ImgurField(  # TODO: Deprecate in future version
        upload_to=settings.IMGUR_ALBUM,
        storage=STORAGE,
        width_field="width",
        height_field="height",
        null=True,
        blank=True,
        default=None,
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

    message_id = models.CharField(max_length=32, null=True, blank=True, default=None)
    file_id = models.CharField(max_length=32, null=True, blank=True, default=None)
    file_name = models.CharField(max_length=128, null=True, blank=True, default=None)
    content_type = models.CharField(max_length=16, null=True, blank=True, default=None)

    @property
    def discord_suffix(self) -> str:
        return (
            f"{settings.DISCORD_MEDIA_WEBHOOK_CHANNEL}/{self.file_id}/{self.file_name}"
        )

    @property
    def url(self) -> str:
        if self.file_id is None or self.file_name is None:
            return None

        return f"https://cdn.discordapp.com/attachments/{self.discord_suffix}"

    @property
    def resizer_url(self) -> str:
        if self.file_id is None or self.file_name is None:
            return None

        return f"https://media.discordapp.net/attachments/{self.discord_suffix}"


def get_temporary_media_file_name(instance, filename: str) -> str:
    extension = filename.split(".")[-1]
    return f"temporary_media/{uuid.uuid4()}.{extension}"


class TemporaryMedia(TimeStampedModel, UUIDModel, MediaMixin):
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


class User(TimeStampedModel):
    firebase_id = models.TextField(unique=True)
    nickname = models.CharField(max_length=255, default="", blank=True)

    badges = models.ManyToManyField(to="mlptf.Badge", through="mlptf.UserBadge")
    clearances = models.ManyToManyField(
        to="common.Clearance", through="common.UserClearance"
    )
    telegram_id = models.TextField(
        unique=True,
        default=None,
        null=True,
        blank=True,
    )

    def __str__(self) -> str:
        return self.firebase_id[:8]

    @property
    def display_name(self) -> str:
        return self.nickname or self.firebase_id[:8]


def get_verification_code():
    return randint(100000, 999999)


class UserVerificationCode(TimeStampedModel):
    user = models.ForeignKey(to="common.User", on_delete=models.CASCADE)
    code = models.PositiveIntegerField(
        unique=True,
        default=get_verification_code,
        validators=[MinValueValidator(100000), MaxValueValidator(999999)],
    )


class UserClearance(TimeStampedModel):
    user = models.ForeignKey(to="common.User", on_delete=models.CASCADE)
    clearance = models.ForeignKey(to="common.Clearance", on_delete=models.CASCADE)


class Clearance(TimeStampedModel):
    name = models.CharField(max_length=128, unique=True, choices=ClearanceType.choices)
    description = models.TextField(blank=True, null=True, default=None)
    users = models.ManyToManyField(to="common.User", through="common.UserClearance")


class FeatureFlag(TimeStampedModel):
    name = models.CharField(
        max_length=128, unique=True, choices=FeatureFlagType.choices
    )
    description = models.TextField(blank=True, null=True, default=None)
    enabled = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.name}-{'Enabled' if self.enabled else 'Disabled'}"
