from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel, UUIDModel

# Create your models here.


class Media(TimeStampedModel, UUIDModel, SoftDeletableModel):
    file = models.FileField()
    uploader = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )


class User(TimeStampedModel):
    firebase_id = models.TextField(unique=True)
