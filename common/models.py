from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel, UUIDModel


class Media(TimeStampedModel, UUIDModel, SoftDeletableModel):
    file = models.FileField()
    uploader = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )

    def __str__(self) -> str:
        return self.id[:8]


class User(TimeStampedModel):
    firebase_id = models.TextField(unique=True)
    nickname = models.CharField(max_length=255, default="")

    badges = models.ManyToManyField(to="mlptf.Badge", through="mlptf.UserBadge")

    def __str__(self) -> str:
        return self.firebase_id[:8]
