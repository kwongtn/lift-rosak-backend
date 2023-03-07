from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel, UUIDModel

from common.enums import UserJejakTransactionCategory


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

    badges = models.ManyToManyField(to="mlptf.Badge", through="mlptf.UserBadge")

    @property
    def credit_balance(self) -> int:
        balance = self.userjejaktransaction_set.aggregate(
            sum=models.Sum("credit_change")
        )["sum"]

        if balance is None:
            return 0
        else:
            return balance

    def __str__(self) -> str:
        return self.firebase_id[:8]


class UserJejakTransaction(TimeStampedModel):
    user = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )
    category = models.CharField(
        choices=UserJejakTransactionCategory.choices,
        max_length=32,
    )
    credit_change = models.IntegerField()
    details = models.TextField(
        null=True,
        default=None,
        blank=True,
    )
