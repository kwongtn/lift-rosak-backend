from django.conf import settings
from django.db import models
from django.utils.safestring import mark_safe
from model_utils.models import TimeStampedModel, UUIDModel

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

    def image_widget(self):
        return mark_safe('<img src="%s" style="max-width: 45vw;" />' % (self.file.url))


class User(TimeStampedModel):
    firebase_id = models.TextField(unique=True)
    nickname = models.CharField(max_length=255, default="", blank=True)

    badges = models.ManyToManyField(to="mlptf.Badge", through="mlptf.UserBadge")

    def __str__(self) -> str:
        return self.firebase_id[:8]
