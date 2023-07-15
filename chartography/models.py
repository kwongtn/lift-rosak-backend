from django.contrib.postgres.indexes import BTreeIndex
from django.db import models
from django.utils.timezone import now
from django_choices_field import TextChoicesField
from model_utils.models import TimeStampedModel

from operation.enums import VehicleStatus


class Source(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="%(app_label)s_%(class)s_unique_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Snapshot(TimeStampedModel):
    date = models.DateField(default=now)
    source = models.ForeignKey("chartography.Source", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "source"],
                name="%(app_label)s_%(class)s_unique_date_source",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date}_{self.source.name}"


class LineVehicleStatusCountHistory(models.Model):
    snapshot = models.ForeignKey("chartography.Snapshot", on_delete=models.CASCADE)
    line = models.ForeignKey("operation.Line", on_delete=models.CASCADE)
    status = TextChoicesField(
        max_length=32,
        choices_enum=VehicleStatus,
    )

    count = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "line", "status"],
                name="%(app_label)s_%(class)s_unique_snapshot_line_status",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["line", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.snapshot.date}_{self.line.code}_{self.status}"
