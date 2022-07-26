from collections import defaultdict
from typing import List

from asgiref.sync import sync_to_async
from django.db.models import Count, Q
from strawberry.dataloader import DataLoader

from operation.models import Vehicle


@sync_to_async
def batch_load_vehicle_type_vehicle(keys):
    vehicles: List[Vehicle] = Vehicle.objects.filter(vehicle_type_id__in=keys)

    vehicle_type_dict = defaultdict()
    for vehicle in vehicles:
        if vehicle.vehicle_type_id not in vehicle_type_dict:
            vehicle_type_dict[vehicle.vehicle_type_id] = [vehicle]
        else:
            vehicle_type_dict[vehicle.vehicle_type_id].append(vehicle)

    return [list(vehicle_type_dict.get(key)) for key in keys]


@sync_to_async
def batch_load_line_vehicle_type(keys):
    vehicles: List[Vehicle] = Vehicle.objects.filter(line_id__in=keys).prefetch_related(
        "vehicle_type"
    )

    line_dict = defaultdict()
    for vehicle in vehicles:
        if vehicle.line_id not in line_dict:
            line_dict[vehicle.line_id] = {vehicle.vehicle_type}
        else:
            line_dict[vehicle.line_id].add(vehicle.vehicle_type)

    return [list(line_dict.get(key, {})) for key in keys]


@sync_to_async
def batch_load_vehicle_status_count_from_vehicle_type(keys):
    # Keys in format (vehicle_type_id, status)
    status_dict = defaultdict()
    for key in keys:
        status_dict[key] = Count("id", filter=Q(vehicle_type_id=key[0], status=key[1]))

    vehicle_object = Vehicle.objects.aggregate(
        **{
            str(dict_entry[0]) + str(dict_entry[1]): status_dict[dict_entry]
            for dict_entry in status_dict
        }
    )

    return [vehicle_object.get(str(key[0]) + str(key[1]), None) for key in keys]


vehicle_type_vehicle_loader = DataLoader(load_fn=batch_load_vehicle_type_vehicle)
line_vehicle_type_loader = DataLoader(load_fn=batch_load_line_vehicle_type)
vehicle_status_count_from_vehicle_type_loader = DataLoader(
    load_fn=batch_load_vehicle_status_count_from_vehicle_type
)
