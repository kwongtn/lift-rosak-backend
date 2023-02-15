from datetime import datetime
from typing import List, Optional

from strawberry_django_plus import gql

from jejak import models


@gql.django.type(models.BusType)
class BusType:
    id: gql.ID
    title: Optional[str]
    description: Optional[str]
    buses: List["Bus"]


@gql.django.type(models.Bus)
class Bus:
    id: gql.ID
    identifier: str
    type: Optional[BusType]


@gql.django.type(models.Location)
class Location:
    id: gql.ID
    dt_received: datetime
    dt_gps: datetime
    location: gql.auto
    dir: Optional[float]
    speed: Optional[float]
    angle: Optional[int]
    bus: Bus
