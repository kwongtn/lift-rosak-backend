from collections import defaultdict
from datetime import date
from typing import List, Optional, Tuple

from django.contrib.gis.db.models import Subquery
from django.db.models import Count, Max, Q
from strawberry.dataloader import DataLoader

from incident.models import VehicleIncident
from operation.models import Vehicle, VehicleLine
from spotting.enums import SpottingVehicleStatus
from spotting.models import Event


async def batch_load_vehicle_from_vehicle_type(keys):
    vehicle_type_dict = defaultdict(set)
    async for vehicle in Vehicle.objects.filter(vehicle_type_id__in=keys).order_by(
        "identification_no"
    ):
        vehicle_type_dict[vehicle.vehicle_type_id].add(vehicle)

    return [list(vehicle_type_dict.get(key, {})) for key in keys]


async def batch_load_vehicle_type_from_line(keys):
    vehicle_lines: List[Vehicle] = VehicleLine.objects.filter(
        line_id__in=keys
    ).prefetch_related("vehicle", "vehicle__vehicle_type")

    line_dict = defaultdict(set)
    async for vehicle_line in vehicle_lines:
        line_dict[vehicle_line.line_id].add(vehicle_line.vehicle.vehicle_type)

    return [list(line_dict.get(key, {})) for key in keys]


async def batch_load_vehicle_status_count_from_vehicle_type(keys):
    # Keys in format (vehicle_type_id, status)
    vehicle_object = await Vehicle.objects.aaggregate(
        **{
            str(key[0]) + str(key[1]): Count(
                "id", filter=Q(vehicle_type_id=key[0], status=key[1])
            )
            for key in keys
        }
    )

    return [vehicle_object.get(str(key[0]) + str(key[1]), None) for key in keys]


async def batch_load_vehicle_count_from_vehicle_type(keys):
    vehicle_object = await Vehicle.objects.aaggregate(
        **{str(key): Count("id", filter=Q(vehicle_type_id=key)) for key in keys}
    )

    return [vehicle_object.get(str(key), None) for key in keys]


async def batch_load_last_spotting_date_from_vehicle_id(keys):
    event_object = await Event.objects.filter(
        ~Q(
            status__in=[
                SpottingVehicleStatus.NOT_SPOTTED,
                SpottingVehicleStatus.DECOMMISSIONED,
                SpottingVehicleStatus.UNKNOWN,
            ]
        )
    ).aaggregate(
        **{str(key): Max("spotting_date", filter=Q(vehicle_id=key)) for key in keys}
    )

    return [event_object.get(str(key), None) for key in keys]


async def batch_load_spotting_count_from_vehicle(keys):
    # Keys in format (vehicle_id, filter)
    event_object = await Event.objects.aaggregate(
        **{str(key[0]): Count("id", filter=key[1]) for key in keys}
    )

    return [event_object.get(str(key[0]), None) for key in keys]


async def batch_load_spottings_from_vehicle(keys):
    spotting_events: List[Event] = Event.objects.filter(
        vehicle_id__in=keys
    ).prefetch_related("vehicle")

    vehicle_dict = defaultdict(set)
    async for spotting_event in spotting_events:
        vehicle_dict[spotting_event.vehicle_id].add(spotting_event)

    return [list(vehicle_dict.get(key, {})) for key in keys]


async def batch_load_incident_from_vehicle(keys):
    vehicle_incidents: List[VehicleIncident] = VehicleIncident.objects.filter(
        vehicle_id__in=keys
    ).prefetch_related("vehicle")

    vehicle_dict = defaultdict(set)
    async for vehicle_incident in vehicle_incidents:
        vehicle_dict[vehicle_incident.vehicle_id].add(vehicle_incident)

    return [list(vehicle_dict.get(key, {})) for key in keys]


async def batch_load_incident_count_from_vehicle(keys):
    incident_object = await VehicleIncident.objects.aaggregate(
        **{str(key): Count("id", filter=Q(vehicle_id=key)) for key in keys}
    )

    return [incident_object.get(str(key), None) for key in keys]


async def batch_load_vehicle_from_line(keys: List[Tuple[int, Optional[bool]]]):
    # keys: (line_id, is_spotted_today)
    # We assume that is_spotted_today is same for all requests in same loop cause
    # there is only one point of instantation
    is_spotted_today = keys[0][1]

    spotted_vehicle_ids_today = (
        Event.objects.filter(spotting_date=date.today())
        .distinct("vehicle_id")
        .values_list("vehicle_id", flat=True)
    )

    vehicle_lines: List[Vehicle] = VehicleLine.objects.filter(
        line_id__in=[key[0] for key in keys]
    )

    if is_spotted_today is True:
        vehicle_lines = vehicle_lines.filter(
            vehicle_id__in=Subquery(spotted_vehicle_ids_today)
        )
    elif is_spotted_today is False:
        vehicle_lines = vehicle_lines.filter(
            ~Q(vehicle_id__in=Subquery(spotted_vehicle_ids_today))
        )

    vehicle_lines = vehicle_lines.prefetch_related("vehicle", "line")

    line_dict = defaultdict(set)
    async for vehicle_line in vehicle_lines:
        line_dict[vehicle_line.line_id].add(vehicle_line.vehicle)

    return [list(line_dict.get(key[0], {})) for key in keys]


OperationContextLoaders = {
    "vehicle_from_vehicle_type_loader": DataLoader(
        load_fn=batch_load_vehicle_from_vehicle_type
    ),
    "vehicle_type_from_line_loader": DataLoader(
        load_fn=batch_load_vehicle_type_from_line
    ),
    "vehicle_from_line_loader": DataLoader(load_fn=batch_load_vehicle_from_line),
    "vehicle_status_count_from_vehicle_type_loader": DataLoader(
        load_fn=batch_load_vehicle_status_count_from_vehicle_type
    ),
    "vehicle_count_from_vehicle_type_loader": DataLoader(
        load_fn=batch_load_vehicle_count_from_vehicle_type
    ),
    "last_spotting_date_from_vehicle_loader": DataLoader(
        load_fn=batch_load_last_spotting_date_from_vehicle_id
    ),
    "spotting_count_from_vehicle_loader": DataLoader(
        load_fn=batch_load_spotting_count_from_vehicle
    ),
    "spottings_from_vehicle_loader": DataLoader(
        load_fn=batch_load_spottings_from_vehicle
    ),
    "incident_from_vehicle_loader": DataLoader(
        load_fn=batch_load_incident_from_vehicle
    ),
    "incident_count_from_vehicle_loader": DataLoader(
        load_fn=batch_load_incident_count_from_vehicle
    ),
}
