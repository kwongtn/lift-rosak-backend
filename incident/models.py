from typing import TYPE_CHECKING

from django.contrib.gis.db import models
from django.contrib.gis.db.models import Q
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from ordered_model.models import OrderedModel

from incident.enums import (
    CalendarIncidentChronologyIndicator,
    CalendarIncidentSeverity,
    IncidentSeverity,
)

if TYPE_CHECKING:
    from common.models import Media


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


class CalendarIncidentCategory(models.Model):
    name = models.CharField(
        max_length=64,
        unique=True,
    )


class CalendarIncidentChronology(TimeStampedModel, OrderedModel):
    calendar_incident = models.ForeignKey(
        to="incident.CalendarIncident",
        on_delete=models.CASCADE,
        related_name="chronologies",
    )

    indicator = models.CharField(
        max_length=16,
        choices=CalendarIncidentChronologyIndicator.choices,
        help_text="Set the color of circles. Green means completed or success status, Red means warning or error, and Blue means ongoing or other default status, Gray for unfinished or disabled status, Loading for in progress status.",
    )
    datetime = models.DateTimeField(
        blank=True,
        null=True,
    )
    source_url = models.URLField(
        blank=True,
        null=True,
        default="",
    )
    content = models.TextField(
        blank=True,
        default="",
    )

    order = models.PositiveIntegerField(_("order"), editable=True, db_index=True)

    order_with_respect_to = "calendar_incident"

    class Meta(OrderedModel.Meta):
        verbose_name_plural = "CalendarIncidentChronologies"


class CalendarIncident(TimeStampedModel, OrderedModel):
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(
        blank=True,
        null=True,
    )

    long_term = models.BooleanField(
        default=False,
        help_text="If the incident is long-term, only start date will be shown in the month calendar view.",
    )
    inaccurate = models.BooleanField(
        default=False,
        help_text="Displays the 'inaccurate' indicator.",
    )

    severity = models.CharField(
        max_length=16,
        choices=CalendarIncidentSeverity.choices,
    )
    impact_factor = models.DecimalField(
        default=0,
        blank=True,
        decimal_places=2,
        max_digits=5,
        help_text="Scores to deduct from full score of 100 per day. Will be prorated based on usual service hours when consolidating.",
    )

    title = models.CharField(
        blank=False,
        null=False,
        default=None,
        max_length=64,
    )
    brief = models.TextField(
        blank=False,
        null=False,
        default=None,
    )

    details = models.TextField(blank=True, default="")

    lines = models.ManyToManyField(
        to="operation.Line",
        blank=True,
    )
    vehicles = models.ManyToManyField(
        to="operation.Vehicle",
        blank=True,
    )
    stations = models.ManyToManyField(
        to="operation.Station",
        blank=True,
    )
    categories = models.ManyToManyField(
        to="incident.CalendarIncidentCategory",
        blank=True,
    )

    medias = models.ManyToManyField(
        to="common.Media",
        blank=True,
        through="incident.CalendarIncidentMedia",
    )

    def __str__(self):
        return f"{self.id} - {self.title[:48]}"

    class Meta(OrderedModel.Meta):
        pass

    def images_widget(self):
        html = '<div style="display: flex;\
            flex-flow: row wrap; align-items: flex-start;\
            align-content: space-between;">'

        media: Media
        for media in self.medias.all():
            html += f'<a href="/admin/common/media/{media.id}/change" target="_blank">'
            html += media.image_widget_html(style="max-width: 200px; padding: 5px;")
            html += "</a>"

        html += "</div>"
        return mark_safe(html)


class CalendarIncidentMedia(TimeStampedModel):
    timestamp = models.DateTimeField(
        blank=True,
        null=True,
        default=None,
    )
    calendar_incident = models.ForeignKey(
        to="incident.CalendarIncident",
        on_delete=models.CASCADE,
    )
    media = models.ForeignKey(
        to="common.Media",
        on_delete=models.CASCADE,
    )
