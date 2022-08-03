from collections import defaultdict
from typing import List

from asgiref.sync import sync_to_async
from django.db.models import Count, Max, Q
from strawberry.dataloader import DataLoader

from operation.models import Vehicle
from spotting.models import Event


@sync_to_async
def batch_load_vehicle_from_vehicle_type(keys):
    vehicle_type_dict = defaultdict()
    for vehicle in Vehicle.objects.filter(vehicle_type_id__in=keys).iterator():
        if vehicle.vehicle_type_id not in vehicle_type_dict:
            vehicle_type_dict[vehicle.vehicle_type_id] = {vehicle}
        else:
            vehicle_type_dict[vehicle.vehicle_type_id].add(vehicle)

    return [list(vehicle_type_dict.get(key, {})) for key in keys]


@sync_to_async
def batch_load_vehicle_type_from_line(keys):
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
    vehicle_object = Vehicle.objects.aggregate(
        **{
            str(key[0])
            + str(key[1]): Count("id", filter=Q(vehicle_type_id=key[0], status=key[1]))
            for key in keys
        }
    )

    return [vehicle_object.get(str(key[0]) + str(key[1]), None) for key in keys]


@sync_to_async
def batch_load_vehicle_count_from_vehicle_type(keys):
    vehicle_object = Vehicle.objects.aggregate(
        **{str(key): Count("id", filter=Q(vehicle_type_id=key)) for key in keys}
    )

    return [vehicle_object.get(str(key), None) for key in keys]


@sync_to_async
def batch_load_last_spotting_date_from_vehicle_id(keys):
    event_object = Event.objects.aggregate(
        **{str(key): Max("spotting_date", filter=Q(vehicle_id=key)) for key in keys}
    )

    return [event_object.get(str(key), None) for key in keys]


@sync_to_async
def batch_load_spotting_count_from_vehicle(keys):
    # Keys in format (vehicle_id, filter)
    event_object = Event.objects.aggregate(
        **{str(key[0]): Count("id", filter=key[1]) for key in keys}
    )

    return [event_object.get(str(key[0]), None) for key in keys]


class OperationContextLoaders:
    vehicle_from_vehicle_type_loader = DataLoader(
        load_fn=batch_load_vehicle_from_vehicle_type
    )
    vehicle_type_from_line_loader = DataLoader(
        load_fn=batch_load_vehicle_type_from_line
    )
    vehicle_status_count_from_vehicle_type_loader = DataLoader(
        load_fn=batch_load_vehicle_status_count_from_vehicle_type
    )
    vehicle_count_from_vehicle_type_loader = DataLoader(
        load_fn=batch_load_vehicle_count_from_vehicle_type
    )
    last_spotting_date_from_vehicle_loader = DataLoader(
        load_fn=batch_load_last_spotting_date_from_vehicle_id
    )
    spotting_count_from_vehicle_loader = DataLoader(
        load_fn=batch_load_spotting_count_from_vehicle
    )
