from django.contrib.postgres.indexes import BTreeIndex
from django.db import models
from django.db.models import Q
from django.utils.timezone import now
from django_choices_field import TextChoicesField
from model_utils.models import TimeStampedModel

from chartography.enums import DataSources
from operation.enums import VehicleStatus


class Source(models.Model):
    name = TextChoicesField(max_length=255, choices_enum=DataSources)
    description = models.TextField(blank=True, default="")
    official_site = models.URLField(null=True, blank=True, default=None)
    icon_url = models.URLField(null=True, blank=True, default=None)

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
    triggered_by = models.ForeignKey(
        "common.User",
        on_delete=models.SET_NULL,
        default=None,
        blank=True,
        null=True,
    )
    url = models.URLField(null=True, blank=True, default=None)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "source"],
                name="%(app_label)s_%(class)s_unique_date_source",
                condition=Q(triggered_by__isnull=True),
            ),
            models.UniqueConstraint(
                fields=["date", "source", "triggered_by"],
                name="%(app_label)s_%(class)s_unique_date_source_w_user",
                condition=Q(triggered_by__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date}_{self.source.name}"


class SourceCustomLine(models.Model):
    source = models.ForeignKey("chartography.Source", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "name"],
                name="%(app_label)s_%(class)s_unique_source_name",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source.name}_{self.name}"


class LineVehicleStatusCountHistory(models.Model):
    snapshot = models.ForeignKey("chartography.Snapshot", on_delete=models.CASCADE)
    line = models.ForeignKey(
        "operation.Line",
        on_delete=models.CASCADE,
        default=None,
        blank=True,
        null=True,
    )
    custom_line = models.ForeignKey(
        "chartography.SourceCustomLine",
        on_delete=models.CASCADE,
        default=None,
        blank=True,
        null=True,
    )
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
                condition=Q(line__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["snapshot", "custom_line", "status"],
                name="%(app_label)s_%(class)s_unique_snapshot_custom_line_status",
                condition=Q(custom_line__isnull=False),
            ),
            models.CheckConstraint(
                check=Q(line__isnull=True) | Q(custom_line__isnull=True),
                name="%(app_label)s_%(class)s_line_custom_line_mutually_exclusive",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["line", "status"]),
        ]

    def __str__(self) -> str:
        line_str = ""
        if self.line:
            line_str = self.line.code
        elif self.custom_line:
            line_str = f"Cust{self.custom_line.name}"

        return f"{self.snapshot.date}_{line_str}_{self.status}"
