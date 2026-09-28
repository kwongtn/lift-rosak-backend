from typing import TYPE_CHECKING, Any

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
    IngestPlatform,
    PassengerStatus,
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


class Agency(TimeStampedModel):
    """A transport operator whose official social accounts are tracked.

    The DB registry is the single source of truth for which accounts the
    official-post pipeline poll/webhook and follows: ``settings`` holds no
    handle list. ``Unassigned`` is the target agency for auto-registered
    accounts (see ``services/official_posts.resolve_account``) pending a human
    mapping against a real operator.
    """

    name = models.CharField(max_length=128, unique=True)
    short_name = models.CharField(max_length=32, blank=True, default="")
    description = models.TextField(blank=True, default="")
    website = models.URLField(blank=True, default="")

    def __str__(self) -> str:
        return self.short_name or self.name

    class Meta:
        verbose_name_plural = "agencies"
        ordering = ("name",)


class SocMedAccount(TimeStampedModel):
    """One tracked social account on a platform, owned by an :class:`Agency`."""

    agency = models.ForeignKey(
        Agency,
        on_delete=models.PROTECT,
        related_name="socmed_accounts",
    )
    platform = TextChoicesField(choices_enum=IngestPlatform)
    handle = models.CharField(max_length=64)
    user_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    display_name = models.CharField(max_length=128, blank=True, default="")
    # The entire provider user object (``GET /2/users/by/username/{handle}``'s
    # ``data``), kept for export fidelity and offline re-seeding.
    raw_payload = models.JSONField(default=dict, blank=True)
    # Gates POLLING only: webhook webhooks ingest regardless, and
    # ``ensure_user_profile`` / ``sync_account_profiles`` still resolve rows the
    # polling side skips.
    is_enabled = models.BooleanField(default=True, db_index=True)
    # When the provider profile was last persisted (seeded by migration 0029,
    # refreshed by ``ensure_user_profile`` / ``resolve_account``).
    resolved_at = models.DateTimeField(null=True, blank=True, default=None)

    def __str__(self) -> str:
        return f"@{self.handle} ({self.platform})"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "handle"],
                name="socmedaccount_unique_platform_handle",
            ),
            # Empty ``user_id`` is the "not yet resolved" state; only rows that
            # actually carry an id must be unique by it.
            models.UniqueConstraint(
                fields=["platform", "user_id"],
                condition=Q(user_id__gt=""),
                name="socmedaccount_unique_platform_user_id",
            ),
        ]
        ordering = ("platform", "handle")


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

    # Tracking-stripped form of ``url``, kept as a plain indexed column. NOT
    # unique: legacy rows may already share a canonical URL, and a UNIQUE
    # constraint would abort the backfill migration and raise IntegrityError on
    # Telegram/admin ingestion. Cross-row dedup is enforced in a service later.
    normalized_url = models.CharField(
        max_length=2048,
        null=True,
        blank=True,
        default=None,
        db_index=True,
    )

    # Hard-deleting a link cascades to its generic votes; soft delete does not.
    votes = GenericRelation(
        "common.Vote",
        related_query_name="social_media_link",
    )

    # --- Automated official-post ingestion (services/official_posts.py) -----
    # Nullable so every community-submitted link predating ingestion keeps
    # working; the partial constraint below only applies where both are set.
    # The registry account (incident.SocMedAccount) replaces the old denormalized
    # ``platform`` + ``source_handle`` pair; platform lives on the account now.
    socmed_account = models.ForeignKey(
        "incident.SocMedAccount",
        null=True,
        blank=True,
        default=None,
        on_delete=models.PROTECT,
        related_name="links",
    )
    # Provider post id as a string: X snowflakes exceed 32-bit int in practice,
    # so they are stored verbatim and ordered numerically in the service layer.
    post_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        default=None,
        db_index=True,
    )
    # Post time, NOT ingest time (that is ``created``).
    posted_at = models.DateTimeField(null=True, blank=True, default=None)
    is_automated = models.BooleanField(default=False, db_index=True)
    # Untouched provider payload, kept for export fidelity. No raw-audit table.
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            # Structural idempotency backstop for re-scrape; the service also
            # re-reads on IntegrityError (no advisory lock, unlike feed_links).
            models.UniqueConstraint(
                fields=["socmed_account", "post_id"],
                condition=Q(socmed_account__isnull=False, post_id__isnull=False),
                name="socialmedialink_unique_account_post",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.url:
            # Local import breaks the incident.models <-> incident.services cycle.
            from incident.services.urls import canonicalize_url

            self.normalized_url = canonicalize_url(self.url) or None
        super().save(*args, **kwargs)


class LineStatusReport(TimeStampedModel):
    line = models.ForeignKey(
        to="operation.Line",
        on_delete=models.PROTECT,
        related_name="status_reports",
    )
    stations = models.ManyToManyField(
        to="operation.Station",
        blank=True,
    )
    status = TextChoicesField(
        choices_enum=PassengerStatus,
    )
    delay_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        default=None,
    )
    notes = models.TextField(blank=True, default="")
    user = models.ForeignKey(
        "common.User",
        on_delete=models.CASCADE,
        related_name="line_status_reports",
    )
    link = models.ForeignKey(
        "incident.SocialMediaLink",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="status_reports",
    )

    def __str__(self) -> str:
        return f"{self.line} - {self.status}"

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["line", "created"]),
        ]
