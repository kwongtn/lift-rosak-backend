from collections import defaultdict

from django.db.models import Q
from strawberry.dataloader import DataLoader

from common.models import Media
from rosak.permissions import has_admin_claim
from spotting.models import Event


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
    medias = Media.objects.filter(
        ~Q(file=""), created__year__in={year for year, _, _ in keys}
    ).order_by("id")
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
    return [await has_admin_claim(user) for user in keys]


CommonContextLoaders = {
    "spottings_from_user_loader": DataLoader(load_fn=batch_load_spottings_from_user),
    "medias_from_period_loader": DataLoader(load_fn=batch_load_medias_from_period),
    "is_admin_from_user_loader": DataLoader(load_fn=batch_load_is_admin_from_user),
}
