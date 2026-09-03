from typing import TYPE_CHECKING

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.db import models
from django.contrib.gis.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django_choices_field import TextChoicesField
from model_utils.models import TimeStampedModel
from ordered_model.models import OrderedModel, OrderedModelManager, OrderedModelQuerySet
from safedelete.managers import SafeDeleteManager, SafeDeleteQueryset
from safedelete.models import SOFT_DELETE, SafeDeleteModel
from simple_history.models import HistoricalRecords

from incident.enums import (
    CalendarIncidentChronologyIndicator,
    CalendarIncidentSeverity,
    CalendarIncidentStatus,
    IncidentSeverity,
    SocialMediaLinkStatus,
)

if TYPE_CHECKING:
    from common.models import Media


class SoftDeleteOrderedQueryset(SafeDeleteQueryset, OrderedModelQuerySet):
    """Safedelete visibility composed with ordered_model queryset helpers."""


class SoftDeleteOrderedManager(SafeDeleteManager, OrderedModelManager):
    """Default manager keeping soft-deleted rows out of `objects`.

    Without this re-declaration OrderedModel's generated manager would win
    the MRO and soft-deleted rows would stay publicly visible.
    """

    _queryset_class = SoftDeleteOrderedQueryset


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
                condition=Q(is_last=True),
            ),
        ]


class CalendarIncidentCategory(models.Model):
    name = models.CharField(
        max_length=64,
        unique=True,
    )

    def __str__(self):
        return self.name


class CalendarIncidentChronology(TimeStampedModel, OrderedModel, SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE

    objects = SoftDeleteOrderedManager()

    calendar_incident = models.ForeignKey(
        to="incident.CalendarIncident",
        on_delete=models.CASCADE,
        related_name="chronologies",
    )

    indicator = TextChoicesField(
        choices_enum=CalendarIncidentChronologyIndicator,
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

    # NEW: Independent status field (NOT inherited from parent)
    status = TextChoicesField(
        choices_enum=CalendarIncidentStatus,
        default=CalendarIncidentStatus.DRAFT,
    )

    # NEW: Optimistic concurrency control
    version = models.PositiveIntegerField(default=1)

    # NEW: Audit history
    history = HistoricalRecords(cascade_delete_history=False)

    # Hard-deleting a chronology cascades to its generic votes; soft delete does not.
    votes = GenericRelation(
        "common.Vote",
        related_query_name="calendar_incident_chronology",
    )

    def clean(self):
        super().clean()
        if self.status == CalendarIncidentStatus.LIVE:
            if self.calendar_incident.status != CalendarIncidentStatus.LIVE:
                raise ValidationError(
                    "Chronology cannot be LIVE if parent incident is not LIVE"
                )

    class Meta(OrderedModel.Meta):
        verbose_name_plural = "CalendarIncidentChronologies"


class CalendarIncident(TimeStampedModel, OrderedModel, SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE

    objects = SoftDeleteOrderedManager()

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

    severity = TextChoicesField(
        choices_enum=CalendarIncidentSeverity,
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
        related_name="incidents",
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

    # NEW: Status field using TextChoicesField
    status = TextChoicesField(
        choices_enum=CalendarIncidentStatus,
        default=CalendarIncidentStatus.DRAFT,
    )

    # Set when an admin rejects the incident; shown in the console queue.
    rejection_reason = models.TextField(
        blank=True,
        default="",
        help_text="Reason entered by the admin who rejected this incident.",
    )

    # Platform identity (common.User) of the submitter; null for legacy rows.
    # Governs author-scoped permissions: edit/delete own drafts, revise LIVE.
    created_by = models.ForeignKey(
        "common.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calendar_incidents",
    )

    # NEW: Draft/revision pattern
    parent_incident = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="draft_revisions",
    )

    # NEW: Optimistic concurrency control
    version = models.PositiveIntegerField(default=1)

    # NEW: Audit history (cascade_delete_history=False preserves tombstones)
    history = HistoricalRecords(cascade_delete_history=False)

    # Hard-deleting an incident cascades to its generic votes; soft delete does not.
    votes = GenericRelation(
        "common.Vote",
        related_query_name="calendar_incident",
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


class SocialMediaLink(TimeStampedModel):
    url = models.URLField()
    title = models.CharField(max_length=256, blank=True, default="")
    description = models.TextField(blank=True, default="")
    # common.User (platform identity from Firebase tokens), not django auth.User —
    # same rationale as common.Vote.user.
    user = models.ForeignKey("common.User", on_delete=models.CASCADE)
    # Approval status. DB-level default is PENDING_APPROVAL; the submit service
    # overrides it to LIVE for admin actors at creation time.
    status = TextChoicesField(
        choices_enum=SocialMediaLinkStatus,
        default=SocialMediaLinkStatus.PENDING_APPROVAL,
    )

    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    categories = models.ManyToManyField("incident.CalendarIncidentCategory", blank=True)
    lines = models.ManyToManyField("operation.Line", blank=True)
    vehicles = models.ManyToManyField("operation.Vehicle", blank=True)
    stations = models.ManyToManyField("operation.Station", blank=True)

    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "common.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_social_media_links",
    )
