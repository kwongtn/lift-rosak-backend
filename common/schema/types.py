from datetime import date
from typing import Optional

import strawberry


@strawberry.type
class UserSpottingTrend:
    spotting_date: Optional[date]
    year: Optional[int]
    month: Optional[int]
    day: Optional[int]
    event_type: Optional[str]
    count: int
