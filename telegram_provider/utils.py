import asyncio
from datetime import date
from typing import TYPE_CHECKING

from django.db.models import Q

from operation.enums import VehicleStatus
from operation.models import VehicleLine
from spotting.models import Event

if TYPE_CHECKING:
    from typing import Coroutine


async def infinite_retry_on_error(fn: "Coroutine", *args, **kwargs) -> "Coroutine":
    while True:
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            print(e)
            await asyncio.sleep(10)


def get_daily_updates(line_id: int) -> str:
    spotted_today_vehicle_ids = (
        Event.objects.filter(created__date=date.today())
        .distinct("vehicle")
        .values_list("vehicle_id", flat=True)
    )

    query_prefix = (
        VehicleLine.objects.select_related("vehicle", "line")
        .filter(
            Q(line_id=line_id),
            ~Q(
                vehicle__status__in=[
                    VehicleStatus.MARRIED,
                    VehicleStatus.DECOMMISSIONED,
                ]
            ),
        )
        .order_by("vehicle__identification_no")
    )

    criteria = Q(vehicle__id__in=spotted_today_vehicle_ids)
    spotted_vehicle_lines = query_prefix.filter(criteria)
    not_spotted_vehicle_lines = query_prefix.filter(~criteria)

    spotted = ", ".join(x.vehicle.identification_no for x in spotted_vehicle_lines)
    not_spotted = ", ".join(
        x.vehicle.identification_no for x in not_spotted_vehicle_lines
    )

    return "\n".join(
        [
            f"<b><u>{date.today().isoformat()}</u></b>",
            "",
            "<u>Not Spotted</u>",
            not_spotted if not_spotted else "<i>None</i>",
            "",
            "<u>Spotted Today</u>",
            spotted if spotted else "<i>None</i>",
            "",
            '<i>* Does not include vehicles marked "Decommissioned" or "Married"</i>',
        ]
    )
