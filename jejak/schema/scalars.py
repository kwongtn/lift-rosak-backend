from datetime import datetime
from typing import List, Optional

import strawberry
import strawberry_django

from jejak import models


@strawberry_django.type(models.BusType)
class BusType:
    id: strawberry.ID
    title: Optional[str]
    description: Optional[str]
    buses: List["Bus"]


@strawberry_django.type(models.Bus)
class Bus:
    id: strawberry.ID
    identifier: str
    type: Optional[BusType]


@strawberry_django.type(models.Location)
class Location:
    id: strawberry.ID
    dt_received: datetime
    dt_gps: datetime
    location: strawberry.auto
    dir: Optional[float]
    speed: Optional[float]
    angle: Optional[int]
    bus: Bus
