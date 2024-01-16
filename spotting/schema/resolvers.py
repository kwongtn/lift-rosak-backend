from spotting.models import Event


async def get_events_count(root) -> int:
    return await Event.objects.acount()
