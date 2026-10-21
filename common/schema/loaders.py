import logging
from collections import defaultdict

from django.db.models import Q
from firebase_admin.exceptions import FirebaseError
from strawberry.dataloader import DataLoader

from common.models import Media
from rosak.permissions import has_admin_claim
from spotting.models import Event

logger = logging.getLogger(__name__)

# Legacy rows hold '' or NULL instead of a file. `~Q(file="")` alone keeps the NULL
# ones (SQL: NOT (file = '' AND file IS NOT NULL)), so the feed and its counts must
# exclude both with this.
FILELESS_MEDIA = Q(file="") | Q(file__isnull=True)


async def batch_load_spottings_from_user(keys):
    events = Event.objects.filter(
        reporter_id__in=[key for key in keys],
    ).select_related("reporter")

    reporter_dict = defaultdict(set)
    async for event in events:
        reporter_dict[event.reporter_id].add(event)

    return [reporter_dict.get(key, set()) for key in keys]


async def batch_load_medias_from_period(keys):
    """The media of each (year, month, day) period, in id order.

    `month` / `day` are None for the coarser groupings of `mediasGroupByPeriod`, and
    the keys of one request can mix groupings, so each row is filed under the year,
    month and day key it matches.
    """
    buckets = {key: [] for key in keys}
    medias = (
        Media.objects.exclude(FILELESS_MEDIA)
        .filter(created__year__in={year for year, _, _ in keys})
        .order_by("id")
    )
    async for media in medias:
        created = media.created
        for key in (
            (created.year, None, None),
            (created.year, created.month, None),
            (created.year, created.month, created.day),
        ):
            if key in buckets:
                buckets[key].append(media)

    return [buckets[key] for key in keys]


async def batch_load_is_admin_from_user(keys):
    # has_admin_claim is an uncached Firebase call; loading it keeps that to one
    # call per viewer per request, however many rows ask.
    # Fail closed: a Firebase outage (quota, network, unavailable) must not fail the
    # field. The viewer just gets the non-admin view; nothing hidden is ever shown.
    is_admin = []
    for user in keys:
        try:
            is_admin.append(await has_admin_claim(user))
        except FirebaseError as exc:
            logger.warning(
                "Admin claim lookup failed; treating viewer as non-admin: %s", exc
            )
            is_admin.append(False)
    return is_admin


CommonContextLoaders = {
    "spottings_from_user_loader": DataLoader(load_fn=batch_load_spottings_from_user),
    "medias_from_period_loader": DataLoader(load_fn=batch_load_medias_from_period),
    "is_admin_from_user_loader": DataLoader(load_fn=batch_load_is_admin_from_user),
}
