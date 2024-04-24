import asyncio
from datetime import date
from typing import TYPE_CHECKING, Any

from django.db.models import Q

from operation.enums import VehicleStatus
from operation.models import VehicleLine
from spotting.models import Event

if TYPE_CHECKING:
    from typing import Coroutine


async def infinite_retry_on_error(
    source_obj: Any, fn_name: "str", *args, **kwargs
) -> "Coroutine":
    while True:
        if source_obj is None:
            print(f"Source obj is None: {source_obj}")
            return

        try:
            return await getattr(source_obj, fn_name)(*args, **kwargs)
        except Exception as e:
            print(e)
            await asyncio.sleep(10)


def get_daily_updates(line_id: int) -> str:
    spotted_today_vehicle_ids = (
        Event.objects.filter(spotting_date=date.today())
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

    base_criteria = Q(vehicle__id__in=spotted_today_vehicle_ids)
    no_review_criteria = Q(vehicle__status__in=[VehicleStatus.IN_SERVICE])
    sections_criteria = {
        "Not Spotted": ~base_criteria,
        "Spotted Today": base_criteria & no_review_criteria,
        "Spotted Today, to review": base_criteria & ~no_review_criteria,
    }

    output_str_arr = [
        f"<b><u>{date.today().isoformat()}</u></b>",
        "",
    ]

    for title, criteria in sections_criteria.items():
        output_str_arr.append(f"<u>{title}</u>")
        results = query_prefix.filter(criteria)

        output_str_arr.append(
            ", ".join(x.vehicle.identification_no for x in results)
            if results
            else "<i>None</i>"
        )
        output_str_arr.append("")

    return "\n".join(
        [
            *output_str_arr,
            "",
            "",
            '<i>* Does not include vehicles marked "Decommissioned" or "Married"</i>',
        ]
    )
