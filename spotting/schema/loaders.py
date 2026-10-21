from collections import defaultdict

from django.db.models import Count, Q
from strawberry.dataloader import DataLoader

from spotting.models import Event, EventMedia, EventRead, LocationEvent


async def batch_load_reporter_from_event(keys):
    events = Event.objects.filter(
        id__in=[key for key in keys],
        is_anonymous=False,
    ).select_related("reporter")

    event_dict = defaultdict()
    async for event in events:
        event_dict[event.id] = event.reporter

    return [event_dict.get(key, None) for key in keys]


async def batch_load_is_read_from_event(keys):
    filter = Q()
    for key in keys:
        filter |= Q(Q(event_id=key[0]) & Q(reader_id=key[1]))

    event_read_list = []
    async for read_obj in EventRead.objects.filter(filter):
        event_read_list.append((read_obj.event_id, read_obj.reader_id))

    return [(key[0], key[1]) in event_read_list for key in keys]


async def batch_load_location_event_from_event(keys):
    event_dict = defaultdict()
    # select_related: the resolver needs event.is_anonymous / reporter_id to decide
    # visibility, and this keeps that to the same single query.
    async for location_event in LocationEvent.objects.select_related("event").filter(
        event_id__in=keys
    ):
        event_dict[location_event.event_id] = location_event

    return [event_dict.get(key, None) for key in keys]


async def batch_load_media_count_from_event(keys):
    query_dict = {f"{key}_count": Count("medias") for key in keys}
    query_dict_gt = {f"{key}_count__gt": 0 for key in keys}
    event_dict = defaultdict()

    async for event in Event.objects.annotate(**query_dict).filter(**query_dict_gt):
        event_dict[str(event.id)] = getattr(event, f"{event.id}_count", 0)

    return [event_dict.get(str(key), 0) for key in keys]


async def batch_load_media_from_event(keys):
    event_dict = defaultdict(list)
    async for event_media in EventMedia.objects.filter(
        event_id__in=keys
    ).select_related("media"):
        event_dict[event_media.event_id].append(event_media.media)

    return [event_dict.get(key, []) for key in keys]


async def batch_load_anonymous_uploader_from_media(keys):
    """media id -> uploader id, for media attached to an anonymous event; else None.

    One query however many photos a request lists. It only says WHOSE photo it is;
    the viewer check stays in `viewer_can_see_uploader`.
    """
    rows = {
        media_id: uploader_id
        async for media_id, uploader_id in EventMedia.objects.filter(
            media_id__in=keys, event__is_anonymous=True
        ).values_list("media_id", "media__uploader_id")
    }

    return [rows.get(key) for key in keys]


SpottingContextLoaders = {
    "is_read_from_event_loader": DataLoader(load_fn=batch_load_is_read_from_event),
    "location_event_from_event_loader": DataLoader(
        load_fn=batch_load_location_event_from_event
    ),
    "reporter_from_event_loader": DataLoader(load_fn=batch_load_reporter_from_event),
    "media_count_from_event_loader": DataLoader(
        load_fn=batch_load_media_count_from_event
    ),
    "media_from_event_loader": DataLoader(load_fn=batch_load_media_from_event),
    "anonymous_uploader_from_media_loader": DataLoader(
        load_fn=batch_load_anonymous_uploader_from_media
    ),
}
