import strawberry
from strawberry.permission import PermissionExtension
from strawberry.types import Info

from chartography.schema.inputs import TriggerInput
from common.schema.scalars import GenericMutationReturn
from rosak.permissions import IsAdmin, IsLoggedIn


@strawberry.type
class ChartographyScalars:
    pass


@strawberry.type
class ChartographyMutations:
    @strawberry.mutation(
        extensions=[PermissionExtension(permissions=[IsLoggedIn(), IsAdmin()])]
    )
    async def trigger_line_vehicle_status_snapshot(
        self,
        input: TriggerInput,
        info: Info,
    ) -> GenericMutationReturn:
        from chartography.tasks import aggregate_line_vehicle_status_mlptf_task

        aggregate_line_vehicle_status_mlptf_task.apply_async(
            kwargs={
                "triggered_by_id": info.context.user.id,
                "force": input.force,
            }
        )

        return GenericMutationReturn(ok=True)
