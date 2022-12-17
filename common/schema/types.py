from typing import Optional

import strawberry


@strawberry.type
class UserSpottingTrend:
    date_key: str
    year: int
    month: Optional[int]
    day: Optional[int]
    event_type: Optional[str]
    count: int
