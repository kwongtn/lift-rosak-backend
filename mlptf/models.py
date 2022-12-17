from django.db import models
from model_utils.models import TimeStampedModel


class Badge(TimeStampedModel):
    name = models.CharField(max_length=64)
    description = models.TextField(default="", blank=True, null=False)
    released = models.DateField()
    sprite_url = models.URLField()

    users = models.ManyToManyField(to="common.User", through="mlptf.UserBadge")


class UserBadge(TimeStampedModel):
    user = models.ForeignKey(
        "common.User",
        on_delete=models.CASCADE,
    )
    badge = models.ForeignKey(
        "mlptf.Badge",
        on_delete=models.CASCADE,
    )
