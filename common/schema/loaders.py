from collections import defaultdict
from typing import List
from uuid import UUID

from strawberry.dataloader import DataLoader

from common.models import Media
from spotting.models import Event


async def batch_load_spottings_from_user(keys):
    events = Event.objects.filter(
        reporter_id__in=[key for key in keys],
    ).select_related("reporter")

    reporter_dict = defaultdict(set)
    async for event in events:
        reporter_dict[event.reporter_id].add(event)

    return [reporter_dict.get(key, set()) for key in keys]


async def batch_load_media_from_id(keys: List[UUID]):
    media_dict = await Media.objects.filter(id__in=set(keys)).ain_bulk()
    return [media_dict.get(key, None) for key in keys]


CommonContextLoaders = {
    "spottings_from_user_loader": DataLoader(load_fn=batch_load_spottings_from_user),
    "media_from_id_loader": DataLoader(load_fn=batch_load_media_from_id),
}
