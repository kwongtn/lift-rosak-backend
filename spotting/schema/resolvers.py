from strawberry.types import Info

from spotting.models import Event


async def get_events_count(root) -> int:
    return await Event.objects.acount()


async def viewer_is_owner_or_admin(info: Info, owner_id) -> bool:
    """True for the user `owner_id` themself and for admins; false for everyone else.

    The admin claim is an uncached Firebase call, so it goes through the per-request
    `is_admin_from_user_loader`: however many rows ask, a viewer costs one lookup.
    """
    user = info.context.user
    if not user:
        return False
    if user.id == owner_id:
        return True

    return await info.context.loaders["common"]["is_admin_from_user_loader"].load(user)


async def viewer_can_see_location(info: Info, event: Event) -> bool:
    """Anonymous spottings hide their GPS from everyone but the reporter and admins.

    Every GraphQL path that returns an event's coordinates must go through this.
    """
    if not event.is_anonymous:
        return True

    return await viewer_is_owner_or_admin(info, event.reporter_id)
