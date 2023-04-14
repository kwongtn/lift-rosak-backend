from django.contrib.gis.db import models
from django.contrib.gis.db.models import Q
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from ordered_model.models import OrderedModel

from incident.enums import IncidentSeverity


class IncidentAbstractModel(TimeStampedModel, OrderedModel):
    date = models.DateField()
    severity = models.CharField(
        max_length=16,
        choices=IncidentSeverity.choices,
    )
    location = models.PointField(
        blank=True,
        null=True,
        default=None,
    )

    title = models.CharField(
        blank=False,
        null=False,
        default=None,
        max_length=64,
    )
    brief = models.CharField(
        blank=False,
        null=False,
        default=None,
        max_length=256,
    )

    is_last = models.BooleanField(default=False)

    # Remove after beta
    order = models.PositiveIntegerField(_("order"), editable=True, db_index=True)

    class Meta:
        abstract = True


class VehicleIncident(IncidentAbstractModel):
    vehicle = models.ForeignKey(
        to="operation.Vehicle",
        on_delete=models.CASCADE,
    )
    medias = models.ManyToManyField(
        to="common.Media",
        blank=True,
    )

    order_with_respect_to = "vehicle"

    class Meta(OrderedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["is_last", "vehicle"],
                name="%(app_label)s_%(class)s_unique_is_last_vehicle",
                condition=Q(is_last=True),
            ),
        ]


class StationIncident(IncidentAbstractModel):
    station = models.ForeignKey(
        to="operation.Station",
        on_delete=models.CASCADE,
    )
    medias = models.ManyToManyField(
        to="common.Media",
        blank=True,
    )

    order_with_respect_to = "station"

    class Meta(OrderedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["is_last", "station"],
                name="%(app_label)s_%(class)s_unique_is_last_station",
            ),
        ]


# class LineIncident(IncidentAbstractModel):
#     line = models.ForeignKey(
#         to="operation.Line",
#         on_delete=models.CASCADE,
#     )
#     medias = models.ManyToManyField(
#         to="common.Media",
#     )
