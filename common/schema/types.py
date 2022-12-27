from typing import Optional

import strawberry

from generic.schema.enums import DateGroupings
from operation.schema.scalars import Vehicle


@strawberry.type
class UserSpottingTrend:
    date_key: str
    year: int
    month: Optional[int]
    day: Optional[int]
    event_type: Optional[str]
    count: int


@strawberry.type
class WithMostEntriesData:
    type: DateGroupings
    date_key: str
    year: int
    month: Optional[int]
    day: Optional[int]
    count: int


@strawberry.type
class FavouriteVehicleData:
    vehicle: Vehicle
    count: int
