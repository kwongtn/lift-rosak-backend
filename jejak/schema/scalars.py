from datetime import datetime
from typing import Optional

from strawberry_django_plus import gql

from jejak import models


@gql.django.type(models.Location)
class Location:
    id: gql.ID
    dt_received: datetime
    dt_gps: datetime
    location: gql.auto
    dir: Optional[int]
    speed: Optional[float]
    angle: Optional[int]
    # bus
