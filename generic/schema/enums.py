from enum import Enum

import strawberry


@strawberry.enum
class DateGroupings(Enum):
    YEAR = "YEAR"
    MONTH = "MONTH"
    WEEK = "WEEK"
    DAY = "DAY"
