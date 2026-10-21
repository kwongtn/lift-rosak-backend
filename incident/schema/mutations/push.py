"""Web push token registration (the bell on a saved line)."""

from typing import List

import strawberry
from strawberry.types import Info

from common.schema.scalars import GenericMutationReturn
from incident import services
from incident.services import push
from rosak.permissions import IsLoggedIn

from .shared import raise_service_error


@strawberry.type
class PushMutations:
    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def register_push_token(
        self, info: Info, token: str, line_ids: List[strawberry.ID]
    ) -> GenericMutationReturn:
        """Upsert this device's FCM token with exactly these lines (replace)."""
        try:
            await push.register(info.context.user, token, line_ids)
        except services.IncidentServiceError as exc:
            raise_service_error(exc)
        return GenericMutationReturn(ok=True)

    @strawberry.mutation(permission_classes=[IsLoggedIn])
    async def unregister_push_token(
        self, info: Info, token: str
    ) -> GenericMutationReturn:
        """Drop the caller's row for this token; ok even when there is none."""
        await push.unregister(info.context.user, token)
        return GenericMutationReturn(ok=True)
