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
    async for location_event in LocationEvent.objects.filter(event_id__in=keys):
        event_dict[location_event.event_id] = location_event

    return [event_dict.get(key, None) for key in keys]


async def batch_load_has_media_from_event(keys):
    query_dict = {str(key): Count("medias") for key in keys}
    query_dict_gt = {f"{key}__gt": 0 for key in keys}
    event_ids = []

    async for id in (
        Event.objects.annotate(**query_dict)
        .filter(**query_dict_gt)
        .values_list("id", flat=True)
    ):
        event_ids.append(id)

    return [int(key) in event_ids for key in keys]


async def batch_load_media_from_event(keys):
    event_dict = defaultdict(list)
    async for event_media in EventMedia.objects.filter(
        event_id__in=keys
    ).select_related("media"):
        event_dict[event_media.event_id].append(event_media.media)

    return [event_dict.get(key, []) for key in keys]


SpottingContextLoaders = {
    "is_read_from_event_loader": DataLoader(load_fn=batch_load_is_read_from_event),
    "location_event_from_event_loader": DataLoader(
        load_fn=batch_load_location_event_from_event
    ),
    "reporter_from_event_loader": DataLoader(load_fn=batch_load_reporter_from_event),
    "has_media_from_event_loader": DataLoader(load_fn=batch_load_has_media_from_event),
    "media_from_event_loader": DataLoader(load_fn=batch_load_media_from_event),
}
