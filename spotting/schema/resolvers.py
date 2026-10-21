from strawberry.types import Info

from spotting.models import Event


async def get_events_count(root) -> int:
    return await Event.objects.acount()


async def viewer_can_see_location(info: Info, event: Event) -> bool:
    """Anonymous spottings hide their GPS from everyone but the reporter and admins.

    Every GraphQL path that returns an event's coordinates must go through this.
    """
    if not event.is_anonymous:
        return True

    user = info.context.user
    if not user:
        return False
    if user.id == event.reporter_id:
        return True

    return await info.context.loaders["common"]["is_admin_from_user_loader"].load(user)
