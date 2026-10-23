from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from django.db.models import Count, F, Q
from graphql import GraphQLError
from strawberry.permission import BasePermission, PermissionExtension
from strawberry.types import Info

from common import models
from common import models as common_models
from common.schema.loaders import FILELESS_MEDIA
from common.schema.orderings import MediaOrder
from common.schema.types import (
    FavouriteVehicleData,
    UserSpottingTrend,
    WithMostEntriesData,
)
from common.utils import get_date_key, get_default_start_time, get_trends
from generic.schema.enums import DateGroupings
from operation import models as operation_models
from rosak.permissions import IsAdmin
from spotting import models as spotting_models
from spotting.enums import SpottingEventType
from spotting.schema.resolvers import viewer_can_see_uploader, viewer_is_owner_or_admin


class CanSeeUploader(BasePermission):
    async def has_permission(self, source, info: Info, **kwargs) -> bool:
        return await viewer_can_see_uploader(info, source.id)


def uploader_field():
    """`Media.uploader` for every type over Media: a photo on an anonymous spotting
    keeps its file but resolves its uploader to null (not an error, so the photo still
    renders) for all but that user and admins.
    """
    return strawberry_django.field(
        extensions=[
            PermissionExtension(
                [CanSeeUploader()], use_directives=False, fail_silently=True
            )
        ]
    )


@strawberry_django.type(models.Media, pagination=True)
class MediaScalar:
    id: strawberry.ID
    uploader: Optional["UserScalar"] = uploader_field()
    file: Optional[strawberry_django.DjangoImageType]
    width: int
    height: int
    url: Optional[str]
    discord_suffix: str
    caption: str
    duration: Optional[int]
    content_type: Optional[str]
    file_name: Optional[str]


@strawberry.type
class MediasGroupByPeriodScalar:
    type: DateGroupings
    date_key: str
    year: int
    month: Optional[int]
    day: Optional[int]
    count: int

    @strawberry.field
    async def medias(self, info: Info) -> List["MediaScalar"]:
        # Lazy: only a query that selects `medias` pays for loading the rows.
        return await info.context.loaders["common"]["medias_from_period_loader"].load(
            (self.year, self.month, self.day)
        )


@strawberry_django.type(models.Media, order=MediaOrder, pagination=True)
class MediaType(strawberry.relay.Node):
    id: strawberry.relay.NodeID[str]
    created: datetime
    uploader: Optional["UserScalar"] = uploader_field()
    file: strawberry_django.DjangoFileType
    width: int
    height: int

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):
        # `file` is non-null here, but legacy rows hold '' (or NULL), which fails the
        # whole page that contains one. Hide them from `medias` and `media(id)`, like
        # `mediasGroupByPeriod` does.
        # The pk is the order of a feed asked for no `order`. An `order` replaces it,
        # and `MediaOrder` puts the pk back as its last key.
        return queryset.exclude(FILELESS_MEDIA).order_by("pk")

    # `only=` keeps `created` out of the optimizer's deferred columns; a bare field
    # re-fetched it once per photo.
    @strawberry_django.field(only=["created"])
    def created_date(self) -> str:
        return self.created.date()


# The most spottings one `UserScalar.spottings` page may ask for.
MAX_SPOTTINGS_PAGE = 200


async def _events_shown_to_viewer(info: Info, user_id) -> Q:
    """The events of `user_id` the viewer may see or count on that user's profile.

    An anonymous spotting is listed and counted only for its reporter and admins, so a
    stranger cannot link it to the profile. Every per-user spotting figure goes through
    this, so the list and the numbers agree.
    """
    shown = Q(reporter_id=user_id)
    if not await viewer_is_owner_or_admin(info, user_id):
        shown &= Q(is_anonymous=False)

    return shown


@strawberry_django.type(models.User)
class UserScalar:
    if TYPE_CHECKING:
        from spotting.schema.scalars import EventScalar

    firebase_id: str = strawberry_django.field(permission_classes=[IsAdmin])
    nickname: str
    credit_balance: int
    free_credit_balance: int
    non_free_credit_balance: int

    @strawberry_django.field
    def short_id(self) -> str:
        return self.firebase_id[:8]

    @strawberry_django.field
    def spotting_data_public(self) -> bool:
        return self.spotting_data_public

    @strawberry_django.field
    async def favourite_vehicles(
        self, info: Info, count: Optional[int] = 1
    ) -> List[FavouriteVehicleData]:
        vehicle_count_dict = [
            row
            async for row in spotting_models.Event.objects.filter(
                await _events_shown_to_viewer(info, self.id)
            )
            .values("vehicle")
            .annotate(Count("vehicle"))
            .order_by("-vehicle__count")[0:count]
        ]

        vehicles = await operation_models.Vehicle.objects.filter(
            id__in=[elem["vehicle"] for elem in vehicle_count_dict]
        ).ain_bulk()

        return [
            FavouriteVehicleData(
                vehicle=vehicles[elem["vehicle"]],
                count=elem["vehicle__count"],
            )
            for elem in vehicle_count_dict
        ]

    @strawberry_django.field
    async def with_most_entries(
        self, info: Info, type: DateGroupings
    ) -> Optional[WithMostEntriesData]:
        groupings = {"year": F("created__year")}

        if type in [DateGroupings.MONTH, DateGroupings.DAY]:
            groupings["month"] = F("created__month")

            if type == DateGroupings.DAY:
                groupings["day"] = F("created__day")

        rows = [
            row
            async for row in spotting_models.Event.objects.filter(
                await _events_shown_to_viewer(info, self.id)
            )
            .annotate(**groupings)
            .values(*groupings.keys())
            .annotate(count=Count("id"))
            .order_by("-count")[:1]
        ]
        # Nothing visible to this viewer (no spottings, or only anonymous ones).
        if not rows:
            return None

        max = rows[0]

        return WithMostEntriesData(
            type=type,
            date_key=get_date_key(
                year=max["year"],
                month=max.get("month", None),
                day=max.get("day", None),
            ),
            year=max["year"],
            month=max.get("month", None),
            day=max.get("day", None),
            count=max["count"],
        )

    @strawberry_django.field
    async def spottings(
        self, info: Info, limit: Optional[int] = None, offset: int = 0
    ) -> Optional[
        List[Annotated["EventScalar", strawberry.lazy("spotting.schema.scalars")]]
    ]:
        """The user's spottings, or null when the viewer may not see the history.

        No `limit`: every spotting, in no promised order, as one dataloader batch.
        A `limit` (1 to 200): one page after the first `offset` rows, newest
        submission first (`created`, then `id`, so rows that tie never skip or
        repeat between pages). `offset` without a `limit` is rejected, not ignored.
        """
        if limit is not None and not 1 <= limit <= MAX_SPOTTINGS_PAGE:
            raise GraphQLError(f"limit must be from 1 to {MAX_SPOTTINGS_PAGE}.")
        if offset < 0 or (offset and limit is None):
            raise GraphQLError("offset must be 0 or more, and needs a limit.")

        if limit is not None:
            # Who may see the history is the rule of the full list below: the owner
            # always, anyone else only on a public one. `_events_shown_to_viewer`
            # then hides the anonymous spottings from all but the owner and admins.
            is_owner = bool(info.context.user) and info.context.user.id == self.id
            if not (is_owner or self.spotting_data_public):
                return None

            # A queryset, not a list, so the optimizer joins `vehicle` and prefetches
            # `lines` (a page of 30 is 4 queries, not 93). `reporter` is joined by
            # hand, as the loader does, because it cannot see that `isMine` reads it.
            return (
                spotting_models.Event.objects.filter(
                    await _events_shown_to_viewer(info, self.id)
                )
                .select_related("reporter")
                .order_by("-created", "-id")[offset : offset + limit]
            )

        # Owner always sees their own spottings
        if info.context.user and info.context.user.id == self.id:
            return await info.context.loaders["common"][
                "spottings_from_user_loader"
            ].load(self.id)

        # Non-owners only see spottings if data is public, minus the anonymous ones
        # (admins keep those).
        if self.spotting_data_public:
            spottings = await info.context.loaders["common"][
                "spottings_from_user_loader"
            ].load(self.id)
            if await viewer_is_owner_or_admin(info, self.id):
                return spottings

            return [event for event in spottings if not event.is_anonymous]

        # Private data - return None
        return None

    @strawberry_django.field
    async def spottings_count(self, info: Info) -> int:
        return await spotting_models.Event.objects.filter(
            await _events_shown_to_viewer(info, self.id)
        ).acount()

    @strawberry_django.field
    async def media_count(self, info: Info) -> int:
        medias = common_models.Media.objects.filter(uploader_id=self.id)
        # Photos on anonymous spottings count only for the uploader and admins, like
        # the spotting counts, so the number does not give away a hidden photo.
        if not await viewer_is_owner_or_admin(info, self.id):
            medias = medias.exclude(eventmedia__event__is_anonymous=True)

        return await medias.acount()

    @strawberry_django.field
    async def spotting_trends(
        self,
        info: Info,
        start: strawberry.Maybe[date] = None,
        end: strawberry.Maybe[date] = None,
        date_group: Optional[DateGroupings] = DateGroupings.DAY,
        type_group: Optional[bool] = False,
        free_range: Optional[bool] = False,
    ) -> List["UserSpottingTrend"]:
        if start is None:
            start = get_default_start_time(type=date_group)
        else:
            start = start.value

        if end is None:
            end = date.today()
        else:
            end = end.value

        results = await sync_to_async(get_trends)(
            groupby_field="spotting_date",
            count_model=spotting_models.Event,
            filters=await _events_shown_to_viewer(info, self.id),
            start=start,
            end=end,
            add_zero=True,
            additional_groupby={
                "type": [event_type.value for event_type in SpottingEventType],
            }
            if type_group
            else {},
            date_group=date_group,
            free_range=free_range,
        )

        return [
            UserSpottingTrend(
                date_key=value["date_key"],
                count=value["count"],
                event_type=value.get("type", None),
                year=value.get("spotting_date__year", None),
                month=value.get("spotting_date__month", None),
                day=value.get("spotting_date__day", None),
                day_of_week=value.get("day_of_week", None),
                week_of_month=value.get("week_of_month", None),
                week_of_year=value.get("week_of_year", None),
                is_last_day_of_month=value.get("is_last_day_of_month", None),
                is_last_week_of_month=value.get("is_last_week_of_month", None),
            )
            for value in results
        ]


@strawberry_django.type(models.UserVerificationCode)
class UserVerificationCodeScalar:
    user: "UserScalar"
    created: datetime
    code: int


@strawberry.type
class GenericMutationReturn:
    ok: bool
    # Populated only by mutations that create a row and need to hand back its
    # id (e.g. createCalendarIncident → submitCalendarIncident chaining).
    id: int | None = None
