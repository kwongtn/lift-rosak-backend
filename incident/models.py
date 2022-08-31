from django.contrib.gis.db import models
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
    description = models.TextField(
        blank=True,
        null=True,
        default=None,
    )

    class Meta:
        abstract = True


class VehicleIncident(IncidentAbstractModel):
    vehicle = models.ForeignKey(
        to="operation.Vehicle",
        on_delete=models.CASCADE,
    )
    medias = models.ManyToManyField(
        to="common.Media",
    )


class StationIncident(IncidentAbstractModel):
    station = models.ForeignKey(
        to="operation.Station",
        on_delete=models.CASCADE,
    )
    medias = models.ManyToManyField(
        to="common.Media",
    )


# class LineIncident(IncidentAbstractModel):
#     line = models.ForeignKey(
#         to="operation.Line",
#         on_delete=models.CASCADE,
#     )
#     medias = models.ManyToManyField(
#         to="common.Media",
#     )
