from typing import List

import strawberry
import strawberry.django
from strawberry import auto

from generic.schema.scalars import GeoPoint
from operation import models
from operation.schema.enums import VehicleStatus


@strawberry.django.type(models.Station)
class Station:
    id: auto
    display_name: str
    location: "GeoPoint"
    lines: List["Line"]
    assets: List["Asset"]


@strawberry.django.type(models.Line)
class Line:
    id: auto
    code: str
    display_name: str
    display_color: str
    stations: List["Station"]


@strawberry.django.type(models.Asset)
class Asset:
    id: auto
    asset_type: auto
    officialid: str
    short_description: str
    long_description: str
    stations: List["Station"]


@strawberry.django.type(models.VehicleType)
class VehicleType:
    id: auto


@strawberry.django.type(models.Vehicle)
class Vehicle:
    id: auto
    identification_no: str
    vehicle_type: "VehicleType"
    status: "VehicleStatus"
    line: "Line"
    notes: str
