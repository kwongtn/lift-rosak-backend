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
    day_of_week: Optional[int]
    week_of_month: Optional[int]
    week_of_year: Optional[int]
    is_last_day_of_month: Optional[bool]
    is_last_week_of_month: Optional[bool]
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
