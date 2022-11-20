from collections import defaultdict

from django.db.models import Q
from strawberry.dataloader import DataLoader

from spotting.models import EventRead, LocationEvent


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


SpottingContextLoaders = {
    "is_read_from_event_loader": DataLoader(load_fn=batch_load_is_read_from_event),
    "location_event_from_event_loader": DataLoader(
        load_fn=batch_load_location_event_from_event
    ),
}
