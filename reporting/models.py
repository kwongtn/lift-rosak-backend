from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel, UUIDModel

from reporting.enums import ReportType

# Create your models here.


class Report(TimeStampedModel, UUIDModel, SoftDeletableModel):
    asset = models.ForeignKey(
        to="operation.Asset",
        on_delete=models.PROTECT,
    )
    reporter = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )
    description = models.TextField(default="")
    type = models.TextField(choices=ReportType.choices)


class Resolution(TimeStampedModel, UUIDModel, SoftDeletableModel):
    reports = models.ManyToManyField(
        to="reporting.Report",
        through="reporting.ReportResolution",
    )
    user = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )


class ReportResolution(models.Model):
    resolution = models.ForeignKey(
        to="reporting.Resolution",
        on_delete=models.PROTECT,
    )
    report = models.ForeignKey(
        to="reporting.Report",
        on_delete=models.PROTECT,
    )


class Vote(TimeStampedModel):
    report = models.ForeignKey(
        to="reporting.Report",
        on_delete=models.PROTECT,
    )
    user = models.ForeignKey(
        to="common.User",
        on_delete=models.PROTECT,
    )
    is_upvote = models.BooleanField()

    @property
    def is_downvote(self):
        return not self.is_upvote
