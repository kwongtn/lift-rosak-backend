from asgiref.sync import sync_to_async
from django.db import models
from django.db.models import Q
from model_utils.models import SoftDeletableModel, TimeStampedModel, UUIDModel

from common.enums import CreditType, UserJejakTransactionCategory


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

    @property
    def free_credit_balance(self) -> int:
        balance = self.userjejaktransaction_set.filter(
            credit_type=CreditType.FREE
        ).aggregate(sum=models.Sum("credit_change"))["sum"]

        if balance is None:
            return 0
        else:
            return balance

    @property
    @sync_to_async
    def afree_credit_balance(self) -> int:
        return self.free_credit_balance

    @property
    def non_free_credit_balance(self) -> int:
        balance = self.userjejaktransaction_set.filter(
            ~Q(credit_type=CreditType.FREE)
        ).aggregate(sum=models.Sum("credit_change"))["sum"]

        if balance is None:
            return 0
        else:
            return balance

    @property
    @sync_to_async
    def anon_free_credit_balance(self) -> int:
        return self.non_free_credit_balance

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
    credit_type = models.CharField(
        choices=CreditType.choices,
        max_length=16,
    )
    credit_change = models.IntegerField()
    details = models.TextField(
        null=True,
        default=None,
        blank=True,
    )
