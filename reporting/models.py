from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel, UUIDModel

from reporting.enums import ReportType

# Create your models here.


class Report(TimeStampedModel, UUIDModel, SoftDeletableModel):
    asset = models.ForeignKey(to="operation.Asset")
    reporter = models.ForeignKey(to="common.User")
    description = models.TextField(default="")
    type = models.TextField(choices=ReportType)


class Resolution(TimeStampedModel, UUIDModel, SoftDeletableModel):
    reports = models.ManyToManyField()


class ReportVote(TimeStampedModel):
    report = models.ForeignKey(to="reporting.Report")
    user = models.ForeignKey(to="common.User")
    is_upvote = models.BooleanField()

    @property
    def is_downvote(self):
        return not self.is_upvote
