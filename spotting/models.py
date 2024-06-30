from datetime import timedelta

from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BTreeIndex
from django.db.models import F, Q
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from django_choices_field import TextChoicesField
from model_utils.models import TimeStampedModel

from generic.models import WebLocationModel
from spotting.enums import SpottingEventType, SpottingVehicleStatus, SpottingWheelStatus


class LocationEvent(WebLocationModel):
    event = models.ForeignKey(
        to="spotting.Event",
        on_delete=models.CASCADE,
    )

    # Override to be not null
    location = models.PointField(
        blank=False,
        null=False,
    )


class Event(TimeStampedModel):
    spotting_date = models.DateField()
    reporter = models.ForeignKey(
        to="common.User",
        on_delete=models.CASCADE,
    )
    vehicle = models.ForeignKey(
        to="operation.Vehicle",
        on_delete=models.CASCADE,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )
    status = TextChoicesField(
        choices_enum=SpottingVehicleStatus,
        max_length=32,
    )

    run_number = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        default=None,
    )

    type = TextChoicesField(
        choices_enum=SpottingEventType,
        max_length=32,
    )

    wheel_status = TextChoicesField(
        choices_enum=SpottingWheelStatus,
        max_length=16,
        blank=True,
        null=True,
        default=None,
    )

    is_anonymous = models.BooleanField(default=False)

    origin_station = models.ForeignKey(
        to="operation.Station",
        null=True,
        default=None,
        blank=True,
        on_delete=models.PROTECT,
        related_name="origin_station_event",
    )
    destination_station = models.ForeignKey(
        to="operation.Station",
        null=True,
        default=None,
        blank=True,
        on_delete=models.PROTECT,
        related_name="destination_station_event",
    )

    medias = models.ManyToManyField(
        to="common.Media",
        blank=True,
        through="spotting.EventMedia",
    )

    data_source = models.ForeignKey(
        to="spotting.EventSource",
        null=True,
        default=None,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(
                    Q(type=SpottingEventType.BETWEEN_STATIONS)
                    & Q(origin_station__isnull=False)
                    & Q(destination_station__isnull=False)
                    & ~Q(origin_station=F("destination_station"))
                    & ~Q(destination_station=F("origin_station"))
                )
                | Q(
                    Q(type=SpottingEventType.AT_STATION)
                    & Q(origin_station__isnull=False)
                    & Q(destination_station__isnull=True)
                )
                | Q(
                    Q(
                        type__in=[
                            SpottingEventType.DEPOT,
                            SpottingEventType.JUST_SPOTTING,
                            SpottingEventType.LOCATION,
                        ]
                    )
                    & Q(origin_station__isnull=True)
                    & Q(destination_station__isnull=True)
                ),
                name="%(app_label)s_%(class)s_value_relevant",
            ),
        ]
        indexes = [
            BTreeIndex(fields=["vehicle", "-spotting_date"]),
            BTreeIndex(fields=["vehicle", "run_number", "-spotting_date"]),
        ]

    async def auser_deletion(self):
        if self.created + timedelta(days=3) < now():
            raise Exception("Event deletion is not allowed after 3 days of creation")
        return await self.adelete()

    def images_widget(self):
        html = '<div style="display: flex;\
            flex-flow: row wrap; align-items: flex-start;\
            align-content: space-between;">'

        for media in self.medias.all():
            html += f'<a href="/admin/common/media/{media.id}/change" target="_blank">'
            html += media.image_widget_html(style="max-width: 200px; padding: 5px;")
            html += "</a>"

        html += "</div>"
        return mark_safe(html)


class EventRead(TimeStampedModel):
    reader = models.ForeignKey(
        to="common.User",
        on_delete=models.CASCADE,
    )
    event = models.ForeignKey(
        to="spotting.Event",
        on_delete=models.CASCADE,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("reader_id", "event_id"),
                name="%(app_label)s_%(class)s_reader_event_unique",
            ),
        ]


class EventMedia(TimeStampedModel):
    event = models.ForeignKey(
        to="spotting.Event",
        on_delete=models.CASCADE,
    )
    media = models.ForeignKey(
        to="common.Media",
        on_delete=models.CASCADE,
    )


class EventSource(TimeStampedModel):
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True, null=True, default=None)

    def __str__(self) -> str:
        return f"{self.name}"
