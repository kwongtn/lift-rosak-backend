from datetime import date
from typing import Optional

import strawberry


@strawberry.type
class UserSpottingTrend:
    spotting_date: Optional[date]
    year: Optional[int]
    month: Optional[int]
    day: Optional[int]
    count: int
